"""Unique-people-per-pass counting for a camera that sweeps along a line of people.

A robot (TurtleBot3) or a handheld phone moves from one end of the line to the other.
Every tracked person seen during that pass is counted once, even after they leave the
frame. When the pass ends, its total becomes the published count until the next pass ends.

Track IDs are only used inside this module; only the counts leave it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence, Tuple

# (track_id, score) per detection; track_id is None until the tracker confirms a person.
Observation = Tuple[Optional[int], float]


@dataclass
class _Track:
    hits: int = 0
    best: float = 0.0


@dataclass
class PassCounter:
    conf: float = 0.4  # minimum score for a detection to count toward a track
    min_hits: int = 3  # a track must be seen this often to count (filters tracker flicker)
    gap_s: float = 5.0  # a pass ends after this long with nobody in view

    in_pass: bool = False
    # True once the robot/app has called start(); after that, passes only start on request.
    managed: bool = False
    passes_completed: int = 0
    last_total: Optional[int] = None
    last_confidence: Optional[float] = None
    _tracks: Dict[int, _Track] = field(default_factory=dict)
    _last_person_at: float = 0.0

    def start(self, now: float, managed: bool = True) -> None:
        """Begins a new pass, discarding any pass in progress."""
        self.managed = self.managed or managed
        self.in_pass = True
        self._tracks = {}
        self._last_person_at = now

    def end(self) -> Optional[int]:
        """Finishes the pass and publishes its total. No-op when no pass is running."""
        if self.in_pass:
            self.last_total = self.running()
            self.last_confidence = self._confidence()
            self.passes_completed += 1
            self.in_pass = False
        return self.last_total

    def observe(self, detections: Sequence[Observation], now: float) -> None:
        people = [(tid, s) for tid, s in detections if tid is not None and s >= self.conf]
        if people and not self.in_pass and not self.managed:
            self.start(now, managed=False)
        if not self.in_pass:
            return
        if people:
            self._last_person_at = now
            for tid, score in people:
                track = self._tracks.setdefault(tid, _Track())
                track.hits += 1
                track.best = max(track.best, score)
        elif now - self._last_person_at >= self.gap_s:
            self.end()

    def running(self) -> int:
        """Unique people counted so far in the current pass."""
        return sum(1 for t in self._tracks.values() if t.hits >= self.min_hits)

    def published(self) -> Tuple[int, float]:
        """(people_count, confidence) to report: the last finished pass, or the running count before the first one."""
        if self.last_total is not None and self.last_confidence is not None:
            return self.last_total, self.last_confidence
        return self.running(), self._confidence()

    def _confidence(self) -> float:
        """Mean best score of the counted people; 1.0 when nobody was counted."""
        best = [t.best for t in self._tracks.values() if t.hits >= self.min_hits]
        return round(sum(best) / len(best), 3) if best else 1.0
