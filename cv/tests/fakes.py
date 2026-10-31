"""Test doubles: no camera or model weights needed."""

import numpy as np

from cv_service.detector import Detection


class FakeDetector:
    """Returns scripted tracked people, one list per call (the last list repeats).

    Each entry is a track id (scored 0.9) or a (track_id, score) pair.
    """

    def __init__(self, *frames: list[int | tuple[int | None, float]]):
        self._script = list(frames) or [[]]
        self.calls = 0

    def detect(self, frame: np.ndarray) -> list[Detection]:
        people = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        out = []
        for i, p in enumerate(people):
            tid, score = p if isinstance(p, tuple) else (p, 0.9)
            out.append(Detection(box=(10 + 20 * i, 10, 30 + 20 * i, 60), score=score, track_id=tid))
        return out


class FakeSource:
    """Yields `frames` blank frames then reports end of stream."""

    def __init__(self, frames: int = 3, opened: bool = True, fps: float = 0.0):
        self._left = frames
        self._opened = opened
        self._fps = fps
        self.released = False

    def isOpened(self) -> bool:
        return self._opened

    def read(self):
        if self._left <= 0:
            return False, None
        self._left -= 1
        return True, np.zeros((120, 160, 3), dtype=np.uint8)

    def get(self, prop: int) -> float:
        return self._fps

    def release(self) -> None:
        self.released = True
