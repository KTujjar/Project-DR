"""Pure counting logic: person detection scores in, people_count and confidence out."""

from collections import deque
from statistics import median_low
from typing import Sequence


def count_people(scores: Sequence[float], conf: float) -> int:
    """Person detections at or above the confidence threshold."""
    return sum(1 for s in scores if s >= conf)


def count_confidence(scores: Sequence[float], conf: float) -> float:
    """How sure we are of the count, 0..1.

    Mean score of the counted people. With nobody counted, it is 1 minus the strongest
    near-miss, so an empty frame with no borderline detections reads as confident.
    """
    counted = [s for s in scores if s >= conf]
    if counted:
        return round(sum(counted) / len(counted), 3)
    near_miss = max(scores, default=0.0)
    return round(1.0 - near_miss, 3)


class Smoother:
    """Median of the last `window` counts, to stop single-frame flicker."""

    def __init__(self, window: int = 5):
        if window < 1:
            raise ValueError("window must be >= 1")
        self._values: deque[int] = deque(maxlen=window)

    def push(self, value: int) -> int:
        self._values.append(value)
        return median_low(self._values)
