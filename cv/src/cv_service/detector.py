"""Person detection. The YOLO detector is the only code that touches model weights."""

import threading
from dataclasses import dataclass
from typing import Protocol

import numpy as np

PERSON_CLASS = 0  # COCO "person"


@dataclass(frozen=True)
class Detection:
    box: tuple[int, int, int, int]  # x1, y1, x2, y2 in pixels
    score: float


class Detector(Protocol):
    def detect(self, frame: np.ndarray) -> list[Detection]: ...


def pick_device(requested: str) -> str:
    """Falls back to CPU when the Apple GPU (mps) or CUDA isn't available."""
    import torch

    if requested == "mps" and not torch.backends.mps.is_available():
        return "cpu"
    if requested.startswith("cuda") and not torch.cuda.is_available():
        return "cpu"
    return requested


class YoloPersonDetector:
    """Ultralytics YOLO restricted to people. Shared by all camera workers, so calls are serialized."""

    def __init__(self, model: str = "yolov8n.pt", device: str = "mps", min_score: float = 0.1):
        from ultralytics import YOLO

        self._model = YOLO(model)
        self._device = pick_device(device)
        # Keep weak detections too: counting.count_confidence uses near-misses.
        self._min_score = min_score
        self._lock = threading.Lock()

    @property
    def device(self) -> str:
        return self._device

    def detect(self, frame: np.ndarray) -> list[Detection]:
        with self._lock:
            result = self._model.predict(
                frame, classes=[PERSON_CLASS], conf=self._min_score, device=self._device, verbose=False
            )[0]
        boxes = result.boxes
        return [
            Detection(box=tuple(int(v) for v in xyxy), score=float(score))
            for xyxy, score in zip(boxes.xyxy.tolist(), boxes.conf.tolist())
        ]
