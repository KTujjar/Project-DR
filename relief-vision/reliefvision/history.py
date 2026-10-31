"""Rolling per-camera memory for the camera chatbot (only used with --serve).

Keeps the last `window_s` seconds of each camera's Events, finished passes and scene-log notes,
plus its latest annotated frame. Everything is in memory: nothing is written to disk, and the
frame is only ever sent to the AI model (chat.py), never served.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, List, Optional, Tuple

from .schema import Event


@dataclass(frozen=True)
class PassRecord:
    ts: float       # wall-clock time the pass ended
    total: int      # unique people counted in that pass


@dataclass(frozen=True)
class SceneNote:
    ts: float
    text: str       # 1-2 sentences describing what the camera showed at `ts`


class _Camera:
    def __init__(self) -> None:
        self.events: Deque[Event] = deque()
        self.passes: Deque[PassRecord] = deque()
        self.notes: Deque[SceneNote] = deque()
        self.frame: Optional[bytes] = None
        self.frame_ts: Optional[float] = None


class CameraHistory:
    def __init__(self, window_s: float = 1800.0, clock: Callable[[], float] = time.time):
        self.window_s = window_s
        self._clock = clock
        self._lock = threading.Lock()
        self._cams: Dict[str, _Camera] = {}

    def _cam(self, camera_id: str) -> _Camera:
        return self._cams.setdefault(camera_id, _Camera())

    def _prune(self, cam: _Camera) -> None:
        cutoff = self._clock() - self.window_s
        for q, ts in ((cam.events, lambda e: e.ts), (cam.passes, lambda p: p.ts), (cam.notes, lambda n: n.ts)):
            while q and ts(q[0]) < cutoff:
                q.popleft()

    # --- writers ---
    def record_event(self, ev: Event) -> None:
        with self._lock:
            cam = self._cam(ev.camera_id)
            cam.events.append(ev)
            self._prune(cam)

    def record_pass(self, camera_id: str, total: int, ts: Optional[float] = None) -> None:
        with self._lock:
            cam = self._cam(camera_id)
            cam.passes.append(PassRecord(self._clock() if ts is None else ts, total))
            self._prune(cam)

    def add_note(self, camera_id: str, text: str, ts: Optional[float] = None) -> None:
        with self._lock:
            cam = self._cam(camera_id)
            cam.notes.append(SceneNote(self._clock() if ts is None else ts, text))
            self._prune(cam)

    def set_frame(self, camera_id: str, jpeg: bytes, ts: Optional[float] = None) -> None:
        with self._lock:
            cam = self._cam(camera_id)
            cam.frame, cam.frame_ts = jpeg, (self._clock() if ts is None else ts)

    # --- readers ---
    def camera_ids(self) -> List[str]:
        with self._lock:
            return list(self._cams)

    def events(self, camera_id: str) -> List[Event]:
        with self._lock:
            cam = self._cam(camera_id)
            self._prune(cam)
            return list(cam.events)

    def latest_event(self, camera_id: str) -> Optional[Event]:
        with self._lock:
            cam = self._cams.get(camera_id)
            return cam.events[-1] if cam and cam.events else None

    def passes(self, camera_id: str) -> List[PassRecord]:
        with self._lock:
            cam = self._cam(camera_id)
            self._prune(cam)
            return list(cam.passes)

    def notes(self, camera_id: str) -> List[SceneNote]:
        with self._lock:
            cam = self._cam(camera_id)
            self._prune(cam)
            return list(cam.notes)

    def latest_frame(self, camera_id: str) -> Tuple[Optional[bytes], Optional[float]]:
        with self._lock:
            cam = self._cams.get(camera_id)
            return (cam.frame, cam.frame_ts) if cam else (None, None)


class RecordingSink:
    """Wraps the EventSink so every emitted Event is also kept in the chat history.

    Lets the chatbot see the event stream without changing pipeline.py.
    """

    def __init__(self, sink, history: CameraHistory):
        self._sink, self._history = sink, history

    def emit(self, ev: Event) -> None:
        self._history.record_event(ev)
        self._sink.emit(ev)

    def __getattr__(self, name):  # close(), pending(), webhook, ... behave as before
        return getattr(self._sink, name)
