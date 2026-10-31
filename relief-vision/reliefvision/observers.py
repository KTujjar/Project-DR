"""Combine several per-frame observers behind CameraWorker's single `observer=` hook."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class ObserverGroup:
    """Calls `on_frame` on every observer, in order; one failing observer doesn't stop the others."""

    def __init__(self, *observers):
        self.observers = [o for o in observers if o is not None]

    def on_frame(self, frame, dets, ts) -> None:
        for o in self.observers:
            try:
                o.on_frame(frame, dets, ts)
            except Exception:  # an observer bug must not stop the camera pipeline
                log.exception("frame observer %r failed", o)
