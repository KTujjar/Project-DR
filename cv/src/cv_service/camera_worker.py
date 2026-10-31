"""One thread per camera: read frames, track people, count them per pass, publish counts and JPEGs."""

import logging
import threading
import time
from typing import Callable, Protocol

import cv2
import numpy as np

from .config import CameraConfig
from .counting import PassCounter
from .detector import Detection, Detector
from .schemas import PeopleCount
from .state import Store
from .timeutil import iso_from_epoch

log = logging.getLogger(__name__)

MAX_BACKOFF_S = 10.0
JPEG_EVERY_S = 0.1  # publish at most 10 frames per second
JPEG_MAX_WIDTH = 640
PUBLISH_EVERY_S = 1.0  # heartbeat so the dashboard sees fresh timestamps


def is_due(last: float, interval: float, now: float) -> bool:
    """True once `interval` has passed, allowing 10% early.

    Camera frames arrive at fixed gaps (33 ms at 30 fps), so three of them span 99.9 ms.
    Without the slack a 0.1 s interval would wait for a fourth frame and run at 7.5 fps.
    """
    return now - last >= interval * 0.9


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


def annotate(frame: np.ndarray, detections: list[Detection], conf: float, counter: PassCounter) -> np.ndarray:
    out = frame.copy()
    for d in detections:
        if d.score < conf:
            continue
        x1, y1, x2, y2 = d.box
        label = f"#{d.track_id} {d.score:.2f}" if d.track_id is not None else f"{d.score:.2f}"
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 200, 0), 2)
        cv2.putText(out, label, (x1, max(y1 - 6, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 0), 1)
    status = f"pass: {counter.running()}" if counter.in_pass else "no pass"
    last = "-" if counter.last_total is None else counter.last_total
    cv2.putText(out, f"{status} | last pass: {last}", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
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
        infer_every_s: float = 0.1,
        min_track_hits: int = 3,
        pass_gap_s: float = 5.0,
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
        # Guards the counter: the API thread starts/ends passes while this thread observes.
        self._lock = threading.Lock()
        self._counter = PassCounter(conf=conf, min_hits=min_track_hits, gap_s=pass_gap_s)
        self._detections: list[Detection] = []
        self._last_infer = float("-inf")
        self._last_jpeg = float("-inf")
        self._last_publish = float("-inf")

    def stop(self) -> None:
        self._stop_event.set()

    # --- pass control (called from the API) ---

    def start_pass(self) -> dict:
        with self._lock:
            self._counter.start(self._clock())
            return self._status()

    def end_pass(self) -> dict:
        with self._lock:
            self._counter.end()
            self._publish(self._clock())
            return self._status()

    def pass_status(self) -> dict:
        with self._lock:
            return self._status()

    def _status(self) -> dict:
        c = self._counter
        return {
            "camera_id": self.cfg.camera_id,
            "in_pass": c.in_pass,
            "managed": c.managed,
            "running_count": c.running(),
            "last_pass_count": c.last_total,
            "passes_completed": c.passes_completed,
        }

    def _publish(self, now: float) -> None:
        people, confidence = self._counter.published()
        self._last_publish = now
        self._store.record_count(
            PeopleCount(
                site_id=self.cfg.site_id,
                camera_id=self.cfg.camera_id,
                timestamp=iso_from_epoch(now),
                people_count=people,
                confidence=confidence,
            )
        )

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
            if ok and frame is None:
                continue  # push source: connected, no new frame yet
            if not ok or frame is None:
                if not self.cfg.is_file:
                    log.warning("%s: lost feed, reconnecting", self.cfg.camera_id)
                return
            self.process_frame(frame)
            if frame_gap:
                self._stop_event.wait(frame_gap)

    def process_frame(self, frame: np.ndarray) -> None:
        """Tracks people when due, publishes the count (immediately when a pass ends) and the annotated frame."""
        now = self._clock()
        with self._lock:
            if is_due(self._last_infer, self._infer_every_s, now):
                self._last_infer = now
                self._detections = self._detector.detect(frame)
                passes_before = self._counter.passes_completed
                self._counter.observe([(d.track_id, d.score) for d in self._detections], now)
                if self._counter.passes_completed != passes_before or now - self._last_publish >= PUBLISH_EVERY_S:
                    self._publish(now)
            if is_due(self._last_jpeg, JPEG_EVERY_S, now):
                self._last_jpeg = now
                jpeg = encode_jpeg(annotate(frame, self._detections, self._conf, self._counter))
                self._store.record_frame(self.cfg.camera_id, jpeg, at=now)
