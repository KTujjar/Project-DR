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
from .pipeline import CameraWorker, build_detectors


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
    ap.add_argument("--no-display", action="store_true")
    ap.add_argument("--save-video", metavar="DIR", help="write annotated video per camera into DIR")
    ap.add_argument("--max-frames", type=int, help="stop after N processed frames per camera")
    ap.add_argument("--device", help="cpu / cuda:0 / mps")
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
    if args.device:
        cfg["device"] = args.device

    person, aid = build_detectors(cfg)
    sink = EventSink(cfg["events"]["jsonl"], cfg["events"]["webhook"], cfg["events"]["outbox_db"])
    workers = [CameraWorker(c, cfg, person, aid, sink, args.save_video, args.max_frames)
               for c in cfg["cameras"]]
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
