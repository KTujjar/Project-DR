"""Detectors, kept behind tiny interfaces so the model can be swapped (e.g. RF-DETR for licensing).

NOTE: Ultralytics YOLO is AGPL-3.0. Fine for a hackathon; if this becomes part of a hosted
platform, swap PersonDetector for an Apache-2.0 model (RF-DETR, YOLOX) or get a license.
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Dict, List, Optional, Protocol, Tuple

import numpy as np
import supervision as sv


class PersonDetector(Protocol):
    def detect(self, frame: np.ndarray) -> sv.Detections: ...


class YoloPersonDetector:
    def __init__(self, weights: str = "yolo11n.pt", conf: float = 0.35, imgsz: int = 640,
                 device: Optional[str] = None):
        from ultralytics import YOLO

        self.model = YOLO(weights)
        self.conf, self.imgsz, self.device = conf, imgsz, device
        self._lock = threading.Lock()  # one model shared by several camera threads

    def detect(self, frame: np.ndarray) -> sv.Detections:
        with self._lock:
            res = self.model.predict(
                frame, classes=[0], conf=self.conf, imgsz=self.imgsz,
                device=self.device, verbose=False,
            )[0]
        return sv.Detections.from_ultralytics(res)


# label -> text prompt for the open-vocabulary model
AID_PROMPTS: Dict[str, str] = {
    "wheelchair": "wheelchair",
    "walker": "walker",
    "crutches": "crutches",
    "cane": "walking cane",
    "stroller": "baby stroller",
}


class AidDetector:
    """Wheelchairs, walkers, crutches, canes, strollers via YOLO-World (open vocabulary).

    Runs only every `interval_s` seconds and reports a median over recent runs, because this
    is the noisiest part of the pipeline. Counts are 'currently visible', not unique people.
    """

    def __init__(self, weights: str = "yolov8s-worldv2.pt", conf: float = 0.25, imgsz: int = 640,
                 interval_s: float = 1.5, device: Optional[str] = None, model=None,
                 lock: Optional[threading.Lock] = None):
        self.labels = list(AID_PROMPTS)
        self.conf, self.imgsz, self.device, self.interval_s = conf, imgsz, device, interval_s
        if model is None:
            from ultralytics import YOLOWorld

            model = YOLOWorld(weights)
            model.set_classes([AID_PROMPTS[k] for k in self.labels])
        self.model = model
        self._lock = lock or threading.Lock()
        self._last_ts: Optional[float] = None
        self._hist: Dict[str, deque] = {k: deque(maxlen=5) for k in self.labels}
        self._last_dets: List[Tuple[str, np.ndarray, float]] = []

    def update(self, frame: np.ndarray, ts: float):
        """Returns (counts_by_label, detections[(label, xyxy, conf)]); detections are the latest run."""
        if self._last_ts is None or ts - self._last_ts >= self.interval_s or ts < self._last_ts:
            self._last_ts = ts
            with self._lock:
                res = self.model.predict(frame, conf=self.conf, imgsz=self.imgsz,
                                         device=self.device, verbose=False)[0]
            dets = []
            for box, c, k in zip(res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy(),
                                 res.boxes.cls.cpu().numpy().astype(int)):
                dets.append((self.labels[k], box, float(c)))
            self._last_dets = dets
            for lab in self.labels:
                self._hist[lab].append(sum(1 for d in dets if d[0] == lab))
        counts = {lab: int(round(float(np.median(self._hist[lab])))) if self._hist[lab] else 0
                  for lab in self.labels}
        return counts, self._last_dets
