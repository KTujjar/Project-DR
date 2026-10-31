"""Decide whether the camera is fixed or moving (robot driving, someone walking with a phone).

Fixed-camera metrics (flow, stagnation, free space) are only meaningful when the view is steady,
so the pipeline switches automatically: parked robot / tripod phone => "fixed", moving => "mobile".
"""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np


class CameraMotionEstimator:
    def __init__(self, thresh_px_s: float = 4.0, hold_s: float = 3.0, scale_w: int = 320):
        self.thresh, self.hold_s, self.scale_w = thresh_px_s, hold_s, scale_w
        self._prev: Optional[np.ndarray] = None
        self._prev_ts: Optional[float] = None
        self._ema = 0.0
        self._mode = "fixed"
        self._calm_since: Optional[float] = None

    def update(self, frame: np.ndarray, person_boxes: np.ndarray, ts: float,
               hint: Optional[bool] = None) -> str:
        h, w = frame.shape[:2]
        scale = self.scale_w / float(w)
        small = cv2.cvtColor(cv2.resize(frame, (self.scale_w, int(h * scale))), cv2.COLOR_BGR2GRAY)

        speed = None
        if self._prev is not None and self._prev.shape == small.shape and ts > self._prev_ts:
            mask = np.full(small.shape, 255, np.uint8)
            for x1, y1, x2, y2 in np.asarray(person_boxes).reshape(-1, 4) * scale:  # ignore people
                mask[max(int(y1), 0): int(y2) + 1, max(int(x1), 0): int(x2) + 1] = 0
            pts = cv2.goodFeaturesToTrack(self._prev, 150, 0.01, 8, mask=mask)
            if pts is not None and len(pts) >= 10:
                nxt, st, _ = cv2.calcOpticalFlowPyrLK(self._prev, small, pts, None)
                ok = st.reshape(-1) == 1
                if ok.sum() >= 8:
                    d = np.linalg.norm((nxt - pts).reshape(-1, 2)[ok], axis=1)
                    speed = float(np.median(d)) / (ts - self._prev_ts)
        self._prev, self._prev_ts = small, ts

        if speed is not None:
            self._ema = 0.6 * self._ema + 0.4 * speed
        moving = self._ema > self.thresh or bool(hint)

        if moving:
            self._mode, self._calm_since = "mobile", None
        elif self._mode == "mobile":
            if self._calm_since is None:
                self._calm_since = ts
            if ts - self._calm_since >= self.hold_s and self._ema < self.thresh * 0.6:
                self._mode = "fixed"
        return self._mode
