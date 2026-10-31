"""One thread per camera: read frames, detect people every few seconds, publish counts and JPEGs."""

import logging
import threading
import time
from typing import Callable, Protocol

import cv2
import numpy as np

from .config import CameraConfig
from .counting import Smoother, count_confidence, count_people
from .detector import Detection, Detector
from .schemas import PeopleCount
from .state import Store
from .timeutil import iso_from_epoch

log = logging.getLogger(__name__)

MAX_BACKOFF_S = 10.0
JPEG_EVERY_S = 0.2  # publish at most ~5 frames per second
JPEG_MAX_WIDTH = 640


class FrameSource(Protocol):
    def isOpened(self) -> bool: ...
    def read(self) -> tuple[bool, np.ndarray | None]: ...
    def get(self, prop: int) -> float: ...
    def release(self) -> None: ...


def open_capture(cfg: CameraConfig) -> FrameSource:
    return cv2.VideoCapture(cfg.source)


def authorize_webcams(cameras: list[CameraConfig]) -> None:
    """Opens each webcam once on the main thread.

    macOS only shows the camera permission prompt from the main thread; worker threads would fail.
    """
    for cfg in cameras:
        if isinstance(cfg.source, int):
            cap = cv2.VideoCapture(cfg.source)
            if not cap.isOpened():
                log.warning("%s: webcam %d not available (check camera permission)", cfg.camera_id, cfg.source)
            cap.release()


def annotate(frame: np.ndarray, detections: list[Detection], conf: float, people: int) -> np.ndarray:
    out = frame.copy()
    for d in detections:
        if d.score < conf:
            continue
        x1, y1, x2, y2 = d.box
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 200, 0), 2)
        cv2.putText(out, f"{d.score:.2f}", (x1, max(y1 - 6, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 0), 1)
    cv2.putText(out, f"people: {people}", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return out


def encode_jpeg(frame: np.ndarray) -> bytes:
    h, w = frame.shape[:2]
    if w > JPEG_MAX_WIDTH:
        frame = cv2.resize(frame, (JPEG_MAX_WIDTH, int(h * JPEG_MAX_WIDTH / w)))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()


class CameraWorker(threading.Thread):
    def __init__(
        self,
        cfg: CameraConfig,
        store: Store,
        detector: Detector,
        conf: float = 0.4,
        infer_every_s: float = 1.0,
        open_source: Callable[[CameraConfig], FrameSource] = open_capture,
        clock: Callable[[], float] = time.time,
    ):
        super().__init__(name=f"camera-{cfg.camera_id}", daemon=True)
        self.cfg = cfg
        self._store = store
        self._detector = detector
        self._conf = conf
        self._infer_every_s = infer_every_s
        self._open_source = open_source
        self._clock = clock
        self._stop_event = threading.Event()
        self._smoother = Smoother()
        self._detections: list[Detection] = []
        self._people = 0
        self._last_infer = float("-inf")
        self._last_jpeg = float("-inf")

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        backoff = 1.0
        while not self._stop_event.is_set():
            src = self._open_source(self.cfg)
            if not src.isOpened():
                src.release()
                log.warning("%s: cannot open %r, retrying in %.0fs", self.cfg.camera_id, self.cfg.source, backoff)
                self._stop_event.wait(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_S)
                continue
            log.info("%s: opened %r", self.cfg.camera_id, self.cfg.source)
            backoff = 1.0
            try:
                self._read_until_done(src)
            finally:
                src.release()
            if self.cfg.is_file and not self.cfg.loop:
                log.info("%s: video ended", self.cfg.camera_id)
                return

    def _read_until_done(self, src: FrameSource) -> None:
        # Files read as fast as the CPU allows, so pace them to their own frame rate.
        fps = src.get(cv2.CAP_PROP_FPS) if self.cfg.is_file else 0
        frame_gap = 1.0 / fps if fps and fps > 0 else 0.0
        while not self._stop_event.is_set():
            ok, frame = src.read()
            if not ok or frame is None:
                if not self.cfg.is_file:
                    log.warning("%s: lost feed, reconnecting", self.cfg.camera_id)
                return
            self.process_frame(frame)
            if frame_gap:
                self._stop_event.wait(frame_gap)

    def process_frame(self, frame: np.ndarray) -> None:
        """Runs detection when due and publishes the annotated frame and count."""
        now = self._clock()
        if now - self._last_infer >= self._infer_every_s:
            self._last_infer = now
            self._detections = self._detector.detect(frame)
            scores = [d.score for d in self._detections]
            self._people = self._smoother.push(count_people(scores, self._conf))
            self._store.record_count(
                PeopleCount(
                    site_id=self.cfg.site_id,
                    camera_id=self.cfg.camera_id,
                    timestamp=iso_from_epoch(now),
                    people_count=self._people,
                    confidence=count_confidence(scores, self._conf),
                )
            )
        if now - self._last_jpeg >= JPEG_EVERY_S:
            self._last_jpeg = now
            self._store.record_frame(
                self.cfg.camera_id, encode_jpeg(annotate(frame, self._detections, self._conf, self._people)), at=now
            )
