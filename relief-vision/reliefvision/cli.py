"""Command line entry point.

Examples:
    reliefvision --source crowd.mp4
    reliefvision --source 0                                  # laptop webcam
    reliefvision --source rtsp://phone:8554/live --webhook http://localhost:8000/events
    reliefvision --source cam_a.mp4 --source cam_b.mp4       # several cameras
    reliefvision --source "ros2:/camera/image_raw/compressed?odom=/odom"
    reliefvision --config config.yaml --no-display --save-video out/
"""
from __future__ import annotations

import argparse
import sys
import time

import cv2

from .config import load_config
from .events import EventSink
from .observers import ObserverGroup
from .pipeline import CameraWorker, build_detectors


def authorize_webcams(cameras) -> None:
    """Opens each webcam once on the main thread before the workers start.

    macOS only shows the camera-permission prompt from the main thread; opening the webcam
    for the first time inside a worker thread fails instead.
    """
    if sys.platform != "darwin":
        return
    for c in cameras:
        if str(c["source"]).isdigit():
            cap = cv2.VideoCapture(int(c["source"]))
            cap.release()


def prepare_dashboard(cfg):
    """Dashboard pieces (--serve) the camera workers need: state, per-camera bridges, phone push sources."""
    from .dashboard import DashboardBridge, DashboardState
    from .sources import PushSource

    cams = cfg["cameras"]
    site = lambda c: c.get("site_id", cfg["site_id"])  # noqa: E731
    state = DashboardState([(c["id"], site(c)) for c in cams], public_url=cfg["server"]["public_url"],
                           video=cfg["server"]["video"])
    bridges = {c["id"]: DashboardBridge(c["id"], site(c), state, conf=cfg["person"]["conf"],
                                        min_track_hits=cfg["pass"]["min_track_hits"], pass_gap_s=cfg["pass"]["gap_s"])
               for c in cams}
    push_sources = {c["id"]: PushSource(cfg["process_fps"]) for c in cams if str(c["source"]) == "push"}
    return state, bridges, push_sources


def prepare_turtlebots(cfg):
    """TurtleBot cameras (`source: turtlebot:<url>`): frame sources and, unless disabled, the
    reporters that show reliefvision's person boxes on the robot operator's video."""
    from .missioncontrol import MissionControlReporter, MissionControlSource, is_turtlebot_spec

    sources, reporters = {}, {}
    for c in cfg["cameras"]:
        if not is_turtlebot_spec(c["source"]):
            continue
        src = MissionControlSource(str(c["source"]), cfg["process_fps"], token_file=c.get("token_file"),
                                   poll_fps=float(c.get("poll_fps", 5.0)))
        sources[c["id"]] = src
        if c.get("report_detections", True):
            reporters[c["id"]] = MissionControlReporter(src)
        print(f"[reliefvision] {c['id']}: TurtleBot camera via {src.base_url}"
              + (" (people boxes shown in Mission Control)" if c["id"] in reporters else ""))
    return sources, reporters


def serve_dashboard(cfg, state, bridges, push_sources, workers) -> None:
    """Starts the dashboard API in a background thread once the workers exist."""
    from .server import create_app, run_in_thread

    srv = cfg["server"]
    crowd_events = {w.cam["id"]: (lambda w=w: w.last_event) for w in workers}
    run_in_thread(create_app(state, bridges, push_sources, srv["cors_origins"], crowd_events), srv["host"], srv["port"])
    print(f"[reliefvision] dashboard API on http://{srv['host']}:{srv['port']}"
          + (" (with video)" if srv["video"] else " (counts only; --serve-video to stream frames)")
          + (f". Phone page: {srv['public_url']}/phone" if push_sources else ""))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="reliefvision", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="YAML config (see config.yaml)")
    ap.add_argument("--source", action="append", help="video file / webcam index / rtsp url / ros2:topic (repeatable)")
    ap.add_argument("--mode", choices=["auto", "fixed", "mobile"], help="override camera mode for all cameras")
    ap.add_argument("--site-id")
    ap.add_argument("--webhook", help="POST events here (buffered in a local outbox if offline)")
    ap.add_argument("--events", help="JSONL output path (default events.jsonl)")
    ap.add_argument("--no-aids", action="store_true", help="skip the wheelchair/walker detector")
    ap.add_argument("--grid", action="store_true", help="shade crowded grid cells on the video (off by default)")
    ap.add_argument("--heat", nargs="?", const="recent", choices=["recent", "cumulative"],
                    help="live heat layer: 'recent' (fades, default) or 'cumulative' (builds up). Fixed camera only")
    ap.add_argument("--heat-half-life", type=float, help="seconds for 'recent' heat to fade by half (default 10)")
    ap.add_argument("--follow-camera", action="store_true",
                    help="with --heat: keep the heat pinned to the scene while the camera moves (pan/tilt/walk)")
    ap.add_argument("--no-display", action="store_true")
    ap.add_argument("--save-video", metavar="DIR", help="write annotated video per camera into DIR")
    ap.add_argument("--max-frames", type=int, help="stop after N processed frames per camera")
    ap.add_argument("--device", help="cpu / cuda:0 / mps")
    ap.add_argument("--serve", nargs="?", const=-1, type=int, metavar="PORT",
                    help="serve the coordinator-dashboard API (default port 8001): people counts per pass, "
                         "camera status, pass start/end, iPhone /phone page")
    ap.add_argument("--serve-video", action="store_true",
                    help="with --serve: also stream annotated video (frames then leave the module)")
    ap.add_argument("--public-url", help="with --serve: base URL browsers use for snapshot/stream links")
    ap.add_argument("--cors-origin", action="append", help="with --serve: allowed browser origin (repeatable)")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if args.source:
        cfg["cameras"] = [{"id": f"cam{i + 1}", "source": s, "mode": args.mode or "auto"}
                          for i, s in enumerate(args.source)]
    elif args.mode:
        for c in cfg["cameras"]:
            c["mode"] = args.mode
    if args.site_id:
        cfg["site_id"] = args.site_id
    if args.webhook:
        cfg["events"]["webhook"] = args.webhook
    if args.events:
        cfg["events"]["jsonl"] = args.events
    if args.no_aids:
        cfg["aids"]["enabled"] = False
    if args.grid:
        cfg["overlay"]["grid"] = True
    if args.heat:
        cfg["overlay"]["heat"] = args.heat
    if args.heat_half_life:
        cfg["overlay"]["heat_half_life_s"] = args.heat_half_life
    if args.follow_camera:
        cfg["overlay"]["heat_follow"] = True
        if not cfg["overlay"]["heat"]:
            cfg["overlay"]["heat"] = "cumulative"      # --follow-camera alone implies a heat layer
    if args.device:
        cfg["device"] = args.device
    srv = cfg["server"]
    if args.serve is not None:
        srv["enabled"] = True
        if args.serve > 0:
            srv["port"] = args.serve
    if args.serve_video:
        srv["video"] = True
    if args.public_url:
        srv["public_url"] = args.public_url
    if args.cors_origin:
        srv["cors_origins"] = args.cors_origin
    if not srv["enabled"] and any(str(c["source"]) == "push" for c in cfg["cameras"]):
        ap.error('cameras with "source: push" need --serve (the phone sends frames to the API)')

    authorize_webcams(cfg["cameras"])
    person, aid = build_detectors(cfg)
    sink = EventSink(cfg["events"]["jsonl"], cfg["events"]["webhook"], cfg["events"]["outbox_db"])
    state, bridges, push_sources = prepare_dashboard(cfg) if srv["enabled"] else (None, {}, {})
    robot_sources, reporters = prepare_turtlebots(cfg)

    def observer_for(cam_id):
        found = [o for o in (bridges.get(cam_id), reporters.get(cam_id)) if o is not None]
        return found[0] if len(found) == 1 else (ObserverGroup(*found) if found else None)

    workers = [CameraWorker(c, cfg, person, aid, sink, args.save_video, args.max_frames,
                            source=push_sources.get(c["id"]) or robot_sources.get(c["id"]),
                            observer=observer_for(c["id"]))
               for c in cfg["cameras"]]
    if srv["enabled"]:
        serve_dashboard(cfg, state, bridges, push_sources, workers)
    for w in workers:
        w.start()
    print(f"[reliefvision] {len(workers)} camera(s) running. Events -> {cfg['events']['jsonl']}"
          + (f" and {cfg['events']['webhook']}" if cfg["events"]["webhook"] else "")
          + ("" if args.no_display else ". Press q in a video window to quit."))

    show = not args.no_display
    try:
        while any(not w.done for w in workers):
            if show:
                try:
                    for w in workers:
                        if w.latest is not None:
                            cv2.imshow(w.cam["id"], w.latest)
                    if cv2.waitKey(30) & 0xFF == ord("q"):
                        break
                except cv2.error:
                    print("[reliefvision] no display available; continuing headless.")
                    show = False
            else:
                time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        for w in workers:
            w.stop_flag.set()
        for w in workers:
            w.join(timeout=5)
        sink.close()
        cv2.destroyAllWindows() if show else None

    status = 0
    for w in workers:
        if w.error:
            print(f"[reliefvision] {w.cam['id']} failed:\n{w.error}", file=sys.stderr)
            status = 1
        else:
            print(f"[reliefvision] {w.cam['id']}: {w.frames_processed} frames processed")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
