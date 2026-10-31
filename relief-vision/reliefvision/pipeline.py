"""One CameraWorker per camera; detectors are shared (and lock-protected) across workers."""
from __future__ import annotations

import os
import threading
import time
import traceback
from typing import Any, Dict, Optional

import cv2
import numpy as np
import supervision as sv

from . import overlay
from .heatmap import LiveHeat
from .camera_motion import CameraMotionEstimator
from .detector import AidDetector, YoloPersonDetector
from .events import EventSink
from .metrics import SceneAnalyzer
from .schema import Event
from .sources import open_source


def build_tracker(fps: float, conf: float):
    """ByteTrack. Lives in Roboflow's `trackers` package now (supervision dropped its copy)."""
    try:
        from trackers import ByteTrackTracker

        return ByteTrackTracker(
            lost_track_buffer=int(fps * 3), frame_rate=float(fps),
            track_activation_threshold=max(conf, 0.4), high_conf_det_threshold=max(conf, 0.5),
            minimum_consecutive_frames=2,
        )
    except ImportError:
        return sv.ByteTrack(track_activation_threshold=conf, lost_track_buffer=int(fps * 3),
                            frame_rate=int(fps))


class CameraWorker(threading.Thread):
    def __init__(self, cam: Dict[str, Any], cfg: Dict[str, Any], person_det, aid_det: Optional[AidDetector],
                 sink: EventSink, save_dir: Optional[str] = None, max_frames: Optional[int] = None):
        super().__init__(daemon=True, name=f"cam-{cam['id']}")
        self.cam, self.cfg, self.person_det, self.aid_det, self.sink = cam, cfg, person_det, aid_det, sink
        self.save_dir, self.max_frames = save_dir, max_frames
        self.latest = None
        self.error: Optional[str] = None
        self.done = False
        self.last_event: Optional[Event] = None
        self.stop_flag = threading.Event()
        self.frames_processed = 0

    def run(self) -> None:
        cfg, cam = self.cfg, self.cam
        fps = cfg["process_fps"]
        writer = None
        src = None
        try:
            src = open_source(cam["source"], fps)
            tracker = build_tracker(fps, cfg["person"]["conf"])
            motion = CameraMotionEstimator(**cfg["camera_motion"])
            analyzer = SceneAnalyzer(cfg)
            mode_cfg = cam.get("mode", "auto")
            ov = cfg["overlay"]
            live_heat = (LiveHeat(ov["heat"], ov["heat_half_life_s"], follow=bool(ov.get("heat_follow")))
                         if ov.get("heat") else None)
            last_emit = None
            for frame, ts in src.frames():
                if self.stop_flag.is_set():
                    break
                raw = self.person_det.detect(frame)
                dets = (tracker.update(raw) if hasattr(tracker, "update")
                        else tracker.update_with_detections(raw))

                auto_mode = motion.update(frame, dets.xyxy, ts, hint=src.motion_hint())   # also tracks camera motion
                mode = mode_cfg if mode_cfg in ("fixed", "mobile") else auto_mode

                aid_counts, aid_dets = (None, [])
                if self.aid_det is not None:
                    aid_counts, aid_dets = self.aid_det.update(frame, ts)

                res = analyzer.update(dets, frame.shape, ts, mode, aid_counts)

                if last_emit is None or ts - last_emit >= cfg["emit_interval_s"] or ts < last_emit:
                    last_emit = ts
                    ev = Event(site_id=cfg["site_id"], camera_id=cam["id"], ts=time.time(),
                               video_ts=round(ts, 2), pose=cam.get("pose"), **res["event"])
                    self.last_event = ev
                    self.sink.emit(ev)

                base = frame
                if live_heat is not None:
                    feet = (np.c_[(dets.xyxy[:, 0] + dets.xyxy[:, 2]) / 2, dets.xyxy[:, 3]]
                            if len(dets) else np.zeros((0, 2)))
                    if live_heat.follow:             # heat pinned to the scene while the camera moves
                        cam_motion = None if auto_mode == "fixed" else motion.last_H   # steady => don't integrate noise
                        live_heat.update(feet, ts, frame.shape, cam_motion)
                        base = live_heat.apply(frame)
                    elif mode == "fixed":            # otherwise heat only makes sense while the view is steady
                        live_heat.update(feet, ts, frame.shape)
                        base = live_heat.apply(frame)
                    else:
                        live_heat.reset()
                self.latest = overlay.draw(base, dets, res["event"], res["child_ids"], aid_dets,
                                           show_grid=cfg["overlay"]["grid"])
                if self.save_dir:
                    if writer is None:
                        os.makedirs(self.save_dir, exist_ok=True)
                        h, w = self.latest.shape[:2]
                        writer = cv2.VideoWriter(os.path.join(self.save_dir, f"{cam['id']}.mp4"),
                                                 cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
                    writer.write(self.latest)
                self.frames_processed += 1
                if self.max_frames and self.frames_processed >= self.max_frames:
                    break
        except Exception:
            self.error = traceback.format_exc()
        finally:
            if writer is not None:
                writer.release()
            if src is not None:
                src.close()
            self.done = True


def build_detectors(cfg: Dict[str, Any]):
    person = YoloPersonDetector(cfg["person"]["weights"], cfg["person"]["conf"],
                                cfg["person"]["imgsz"], cfg["device"])
    aid = None
    a = cfg["aids"]
    if a["enabled"]:
        try:
            aid_model = AidDetector(a["weights"], a["conf"], a["imgsz"], a["interval_s"], cfg["device"])
            aid = aid_model
        except Exception as e:  # missing text encoder / no network / weights unavailable
            print(f"[reliefvision] mobility-aid detector disabled: {type(e).__name__}: {e}")
    return person, aid
