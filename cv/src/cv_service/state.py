"""Thread-safe store shared by camera workers (writers) and the API (readers)."""

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from .config import CameraConfig
from .schemas import CameraFeed, PeopleCount
from .timeutil import iso_from_epoch, parse_iso


@dataclass
class _Camera:
    config: CameraConfig
    jpeg: bytes | None = None
    frame_seq: int = 0
    last_frame_at: float | None = None


class Store:
    def __init__(self, cameras: list[CameraConfig], history_s: float = 600.0, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._started_at = clock()
        self._history_s = history_s
        self._cameras = {c.camera_id: _Camera(c) for c in cameras}
        self._counts: deque[tuple[float, PeopleCount]] = deque()
        self._cond = threading.Condition()

    @property
    def camera_ids(self) -> list[str]:
        return list(self._cameras)

    def has_camera(self, camera_id: str) -> bool:
        return camera_id in self._cameras

    # --- writers (camera workers) ---

    def record_frame(self, camera_id: str, jpeg: bytes, at: float | None = None) -> None:
        with self._cond:
            cam = self._cameras[camera_id]
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

    # --- readers (API) ---

    def latest_frame(self, camera_id: str) -> tuple[int, bytes | None]:
        with self._cond:
            cam = self._cameras[camera_id]
            return cam.frame_seq, cam.jpeg

    def wait_for_frame(self, camera_id: str, after_seq: int, timeout: float) -> tuple[int, bytes | None]:
        """Blocks until a frame newer than `after_seq` arrives or the timeout passes."""
        with self._cond:
            self._cond.wait_for(lambda: self._cameras[camera_id].frame_seq > after_seq, timeout=timeout)
            cam = self._cameras[camera_id]
            return cam.frame_seq, cam.jpeg

    def people_counts(self, since: float | None = None) -> list[PeopleCount]:
        """Counts newer than `since` (epoch seconds), or the latest per camera when omitted."""
        with self._cond:
            if since is not None:
                return [c for at, c in self._counts if at > since]
            latest: dict[str, PeopleCount] = {}
            for _, c in self._counts:
                latest[c.camera_id] = c
            return list(latest.values())

    def cameras(self, public_url: str, offline_after_s: float) -> list[CameraFeed]:
        now = self._clock()
        with self._cond:
            feeds = []
            for cam in self._cameras.values():
                base = f"{public_url}/api/cameras/{cam.config.camera_id}"
                online = cam.last_frame_at is not None and now - cam.last_frame_at <= offline_after_s
                # Never-seen cameras report the service start time, so they go stale on the dashboard.
                last = cam.last_frame_at if cam.last_frame_at is not None else self._started_at
                feeds.append(
                    CameraFeed(
                        camera_id=cam.config.camera_id,
                        site_id=cam.config.site_id,
                        stream_url=f"{base}/stream.mjpg",
                        # Changes with every frame so the dashboard's <img> reloads on each poll.
                        snapshot_url=f"{base}/snapshot.jpg?t={int(last * 1000)}" if cam.jpeg else None,
                        online=online,
                        last_frame_at=iso_from_epoch(last),
                    )
                )
            return feeds

    def online_count(self, offline_after_s: float) -> int:
        now = self._clock()
        with self._cond:
            return sum(1 for c in self._cameras.values() if c.last_frame_at is not None and now - c.last_frame_at <= offline_after_s)
