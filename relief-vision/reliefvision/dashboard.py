"""Coordinator-dashboard output: PeopleCount / CameraFeed records (the dashboard's data contracts).

Separate from schema.Event: the dashboard polls these over HTTP (server.py) instead of receiving
webhook events. People counts come from passes along a line (passcount.PassCounter): a robot or
phone sweeps the line and every tracked person is counted once per pass.

Frames only leave the module when video is enabled (--serve-video); otherwise the dashboard gets
counts and camera status alone.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Deque, Dict, List, Optional, Tuple

import cv2
import numpy as np
from pydantic import BaseModel, Field

from .passcount import PassCounter

JPEG_EVERY_S = 0.1          # stream at most 10 frames per second
JPEG_MAX_WIDTH = 640
PUBLISH_EVERY_S = 1.0       # heartbeat so the dashboard sees fresh timestamps


# --------------------------------------------------------------------------- contracts
# Field-for-field copies of the shared TypeScript contracts in the root CLAUDE.md.

class PeopleCount(BaseModel):
    site_id: str
    camera_id: str
    timestamp: str
    people_count: int = Field(ge=0)
    confidence: float = Field(ge=0, le=1)


class CameraFeed(BaseModel):
    camera_id: str
    site_id: str
    stream_url: Optional[str] = None
    snapshot_url: Optional[str] = None
    online: bool
    last_frame_at: str


def iso_from_epoch(seconds: float) -> str:
    """UTC ISO 8601 with milliseconds and 'Z', identical to JS Date.toISOString().

    The dashboard compares timestamps as strings, so the format must match exactly.
    """
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value: str) -> float:
    """Epoch seconds from an ISO 8601 string ('Z' or offset)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def is_due(last: float, interval: float, now: float) -> bool:
    """True once `interval` has passed, allowing 10% early.

    Frames arrive at fixed gaps (33 ms at 30 fps), so three of them span 99.9 ms; without the
    slack a 0.1 s interval would wait for a fourth frame and run at 7.5 fps.
    """
    return now - last >= interval * 0.9


def encode_jpeg(frame: np.ndarray) -> bytes:
    h, w = frame.shape[:2]
    if w > JPEG_MAX_WIDTH:
        frame = cv2.resize(frame, (JPEG_MAX_WIDTH, int(h * JPEG_MAX_WIDTH / w)))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()


# --------------------------------------------------------------------------- state
class _Camera:
    def __init__(self, camera_id: str, site_id: str):
        self.camera_id, self.site_id = camera_id, site_id
        self.jpeg: Optional[bytes] = None
        self.frame_seq = 0
        self.last_frame_at: Optional[float] = None


class DashboardState:
    """Thread-safe store shared by camera bridges (writers) and the HTTP server (readers)."""

    def __init__(self, cameras: List[Tuple[str, str]], public_url: str = "http://localhost:8001",
                 video: bool = False, offline_after_s: float = 10.0, history_s: float = 600.0,
                 clock: Callable[[], float] = time.time):
        self.public_url = public_url.rstrip("/")
        self.video = video
        self.offline_after_s = offline_after_s
        self._clock = clock
        self._started_at = clock()
        self._history_s = history_s
        self._cameras: Dict[str, _Camera] = {cid: _Camera(cid, site) for cid, site in cameras}
        self._counts: Deque[Tuple[float, PeopleCount]] = deque()
        self._cond = threading.Condition()

    def has_camera(self, camera_id: str) -> bool:
        return camera_id in self._cameras

    # --- writers ---
    def record_frame(self, camera_id: str, jpeg: Optional[bytes], at: Optional[float] = None) -> None:
        """Marks the camera as alive; stores the JPEG only when video is enabled."""
        with self._cond:
            cam = self._cameras[camera_id]
            if jpeg is not None:
                cam.jpeg = jpeg
                cam.frame_seq += 1
            cam.last_frame_at = self._clock() if at is None else at
            self._cond.notify_all()

    def record_count(self, count: PeopleCount) -> None:
        at = parse_iso(count.timestamp)
        with self._cond:
            self._counts.append((at, count))
            cutoff = self._clock() - self._history_s
            while self._counts and self._counts[0][0] < cutoff:
                self._counts.popleft()

    # --- readers ---
    def latest_frame(self, camera_id: str) -> Tuple[int, Optional[bytes]]:
        with self._cond:
            cam = self._cameras[camera_id]
            return cam.frame_seq, cam.jpeg

    def wait_for_frame(self, camera_id: str, after_seq: int, timeout: float) -> Tuple[int, Optional[bytes]]:
        """Blocks until a frame newer than `after_seq` arrives or the timeout passes."""
        with self._cond:
            self._cond.wait_for(lambda: self._cameras[camera_id].frame_seq > after_seq, timeout=timeout)
            cam = self._cameras[camera_id]
            return cam.frame_seq, cam.jpeg

    def people_counts(self, since: Optional[float] = None) -> List[PeopleCount]:
        """Counts newer than `since` (epoch seconds), or the latest per camera when omitted."""
        with self._cond:
            if since is not None:
                return [c for at, c in self._counts if at > since]
            latest: Dict[str, PeopleCount] = {}
            for _, c in self._counts:
                latest[c.camera_id] = c
            return list(latest.values())

    def cameras(self) -> List[CameraFeed]:
        now = self._clock()
        with self._cond:
            feeds = []
            for cam in self._cameras.values():
                base = f"{self.public_url}/api/cameras/{cam.camera_id}"
                online = cam.last_frame_at is not None and now - cam.last_frame_at <= self.offline_after_s
                # Never-seen cameras report the service start time, so they go stale on the dashboard.
                last = cam.last_frame_at if cam.last_frame_at is not None else self._started_at
                video = self.video and cam.jpeg is not None
                feeds.append(CameraFeed(
                    camera_id=cam.camera_id,
                    site_id=cam.site_id,
                    stream_url=f"{base}/stream.mjpg" if video else None,
                    # Changes with every frame so a polling <img> reloads.
                    snapshot_url=f"{base}/snapshot.jpg?t={int(last * 1000)}" if video else None,
                    online=online,
                    last_frame_at=iso_from_epoch(last),
                ))
            return feeds

    def online_count(self) -> int:
        now = self._clock()
        with self._cond:
            return sum(1 for c in self._cameras.values()
                       if c.last_frame_at is not None and now - c.last_frame_at <= self.offline_after_s)


# --------------------------------------------------------------------------- per-camera bridge
class DashboardBridge:
    """Observer for one pipeline.CameraWorker: counts people per pass and feeds DashboardState.

    `on_frame` is called by the worker thread; start/end/status by the HTTP server thread.
    """

    def __init__(self, camera_id: str, site_id: str, state: DashboardState, conf: float = 0.35,
                 min_track_hits: int = 3, pass_gap_s: float = 5.0,
                 clock: Callable[[], float] = time.time):
        self.camera_id, self.site_id = camera_id, site_id
        self._state = state
        self._clock = clock
        self._lock = threading.Lock()
        self._counter = PassCounter(conf=conf, min_hits=min_track_hits, gap_s=pass_gap_s)
        self._last_ts = 0.0          # pipeline time (simulated for video files), used for pass gaps
        self._last_publish = float("-inf")
        self._last_jpeg = float("-inf")

    def on_frame(self, frame: np.ndarray, dets, ts: float) -> None:
        now = self._clock()
        ids = dets.tracker_id if len(dets) and dets.tracker_id is not None else [None] * len(dets)
        scores = dets.confidence if len(dets) and dets.confidence is not None else [1.0] * len(dets)
        # ByteTrack labels not-yet-confirmed people -1; they aren't a person yet, so count them as untracked.
        observations = [(None if t is None or int(t) < 0 else int(t), float(s)) for t, s in zip(ids, scores)]
        with self._lock:
            self._last_ts = ts
            passes_before = self._counter.passes_completed
            self._counter.observe(observations, ts)
            if self._counter.passes_completed != passes_before or now - self._last_publish >= PUBLISH_EVERY_S:
                self._publish(now)
            jpeg = None
            if self._state.video and is_due(self._last_jpeg, JPEG_EVERY_S, now):
                self._last_jpeg = now
                jpeg = encode_jpeg(frame)
        self._state.record_frame(self.camera_id, jpeg, at=now)

    # --- pass control (HTTP server thread) ---
    def start_pass(self) -> dict:
        with self._lock:
            self._counter.start(self._last_ts)
            return self._status()

    def end_pass(self) -> dict:
        with self._lock:
            self._counter.end()
            self._publish(self._clock())
            return self._status()

    def pass_status(self) -> dict:
        with self._lock:
            return self._status()

    def _status(self) -> dict:
        c = self._counter
        return {
            "camera_id": self.camera_id,
            "in_pass": c.in_pass,
            "managed": c.managed,
            "running_count": c.running(),
            "last_pass_count": c.last_total,
            "passes_completed": c.passes_completed,
        }

    def _publish(self, now: float) -> None:
        people, confidence = self._counter.published()
        self._last_publish = now
        self._state.record_count(PeopleCount(
            site_id=self.site_id, camera_id=self.camera_id, timestamp=iso_from_epoch(now),
            people_count=people, confidence=confidence,
        ))
