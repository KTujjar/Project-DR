"""Person detection + tracking. The YOLO tracker is the only code that touches model weights."""

import threading
from dataclasses import dataclass
from typing import Protocol

import numpy as np

PERSON_CLASS = 0  # COCO "person"

# Model calls from different camera threads share one GPU; run them one at a time.
_GPU_LOCK = threading.Lock()


@dataclass(frozen=True)
class Detection:
    box: tuple[int, int, int, int]  # x1, y1, x2, y2 in pixels
    score: float
    track_id: int | None = None  # stable across frames while the person stays in view


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


class YoloPersonTracker:
    """Ultralytics YOLO + ByteTrack restricted to people.

    Tracker state lives on the model, so each camera needs its own instance.
    """

    def __init__(self, model: str = "yolov8n.pt", device: str = "mps", min_score: float = 0.1):
        from ultralytics import YOLO

        self._model = YOLO(model)
        self._device = pick_device(device)
        self._min_score = min_score

    @property
    def device(self) -> str:
        return self._device

    def detect(self, frame: np.ndarray) -> list[Detection]:
        with _GPU_LOCK:
            result = self._model.track(
                frame,
                persist=True,
                tracker="bytetrack.yaml",
                classes=[PERSON_CLASS],
                conf=self._min_score,
                device=self._device,
                verbose=False,
            )[0]
        boxes = result.boxes
        ids = boxes.id.int().tolist() if boxes.id is not None else [None] * len(boxes)
        return [
            Detection(box=tuple(int(v) for v in xyxy), score=float(score), track_id=tid)
            for xyxy, score, tid in zip(boxes.xyxy.tolist(), boxes.conf.tolist(), ids)
        ]
