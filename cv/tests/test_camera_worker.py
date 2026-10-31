import cv2
import numpy as np
from fakes import FakeDetector, FakeSource

from cv_service.camera_worker import CameraWorker, annotate, encode_jpeg
from cv_service.config import CameraConfig
from cv_service.detector import Detection
from cv_service.state import Store

CAM = CameraConfig("cam_s3", "shelter_3", 0)


class Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def make_worker(detector, clock, cfg=CAM, open_source=None):
    store = Store([cfg], clock=clock)
    worker = CameraWorker(cfg, store, detector, conf=0.4, infer_every_s=1.0, clock=clock,
                          open_source=open_source or (lambda c: FakeSource()))
    return store, worker


def frame():
    return np.zeros((120, 160, 3), dtype=np.uint8)


def test_publishes_count_and_frame():
    clock = Clock()
    store, worker = make_worker(FakeDetector([0.9, 0.8, 0.2]), clock)
    worker.process_frame(frame())
    (count,) = store.people_counts()
    assert count.people_count == 2
    assert count.confidence == 0.85
    assert count.site_id == "shelter_3"
    assert count.timestamp == "1970-01-01T00:16:40.000Z"
    seq, jpeg = store.latest_frame("cam_s3")
    assert seq == 1 and jpeg.startswith(b"\xff\xd8")


def test_detects_only_every_infer_interval():
    clock = Clock()
    detector = FakeDetector([0.9])
    store, worker = make_worker(detector, clock)
    worker.process_frame(frame())
    clock.t += 0.5
    worker.process_frame(frame())
    assert detector.calls == 1
    clock.t += 0.5
    worker.process_frame(frame())
    assert detector.calls == 2
    assert len(store.people_counts(since=0)) == 2


def test_count_is_smoothed():
    clock = Clock()
    store, worker = make_worker(FakeDetector([0.9], [0.9], [0.9, 0.9, 0.9, 0.9, 0.9]), clock)
    for _ in range(3):
        worker.process_frame(frame())
        clock.t += 1
    assert store.people_counts()[0].people_count == 1  # one-off spike of 5 ignored


def test_video_file_without_loop_stops_at_end():
    cfg = CameraConfig("cam_v", "shelter_1", "/tmp/clip.mp4", loop=False)
    sources = []

    def open_source(c):
        sources.append(FakeSource(frames=3))
        return sources[-1]

    store, worker = make_worker(FakeDetector([0.9]), Clock(), cfg=cfg, open_source=open_source)
    worker.run()  # returns on its own
    assert len(sources) == 1 and sources[0].released
    assert store.latest_frame("cam_v")[1] is not None


def test_unopenable_source_retries_until_stopped():
    attempts = []

    def open_source(c):
        attempts.append(1)
        if len(attempts) >= 2:
            worker.stop()
        return FakeSource(opened=False)

    store, worker = make_worker(FakeDetector(), Clock(), open_source=open_source)
    worker._stop_event.wait = lambda timeout=None: None  # skip backoff sleeps
    worker.run()
    assert len(attempts) == 2


def test_annotate_and_encode():
    img = annotate(frame(), [Detection((5, 5, 50, 50), 0.9), Detection((60, 5, 90, 50), 0.1)], conf=0.4, people=1)
    assert img.shape == (120, 160, 3) and img.any()
    big = np.zeros((720, 1280, 3), dtype=np.uint8)
    decoded = cv2.imdecode(np.frombuffer(encode_jpeg(big), np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (360, 640, 3)
