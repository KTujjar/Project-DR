"""Shared test helpers: tracked detections without models, cameras or footage."""
import numpy as np
import supervision as sv


def dets(*people):
    """sv.Detections for tracked people; each entry is a track id (score 0.9) or (track_id, score)."""
    if not people:
        return sv.Detections.empty()
    ids, scores = zip(*[(p if isinstance(p, tuple) else (p, 0.9)) for p in people])
    n = len(people)
    xyxy = np.array([[10 + 30 * i, 10, 30 + 30 * i, 80] for i in range(n)], dtype=float)
    return sv.Detections(xyxy=xyxy, confidence=np.array(scores, dtype=float),
                         class_id=np.zeros(n, dtype=int), tracker_id=np.array(ids))


def frame(w=160, h=120):
    return np.zeros((h, w, 3), dtype=np.uint8)


class Clock:
    def __init__(self, t: float = 1_793_400_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t
