import cv2
import numpy as np
from fakes import FakeDetector, FakeSource

from cv_service.camera_worker import CameraWorker, annotate, encode_jpeg, is_due
from cv_service.config import CameraConfig
from cv_service.counting import PassCounter
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
    worker = CameraWorker(cfg, store, detector, conf=0.4, infer_every_s=0.125, min_track_hits=3, pass_gap_s=5,
                          clock=clock, open_source=open_source or (lambda c: FakeSource()))
    return store, worker


def frame():
    return np.zeros((120, 160, 3), dtype=np.uint8)


def run_frames(worker, clock, n, step=0.125):
    for _ in range(n):
        worker.process_frame(frame())
        clock.t += step


def test_person_who_leaves_frame_stays_counted():
    clock = Clock()
    # Person 1 and 2 seen, then they leave and person 3 appears.
    store, worker = make_worker(FakeDetector([1, 2], [1, 2], [1, 2], [3], [3], [3]), clock)
    run_frames(worker, clock, 6)
    assert worker.pass_status()["running_count"] == 3
    clock.t += 1
    worker.process_frame(frame())  # next heartbeat publishes the running count
    assert store.people_counts()[0].people_count == 3


def test_managed_pass_publishes_total_on_end_and_holds_it_during_recount():
    clock = Clock()
    store, worker = make_worker(FakeDetector([1, 2, 3], [1, 2, 3], [1, 2, 3], [4], [4], [4]), clock)
    worker.start_pass()
    run_frames(worker, clock, 3)
    status = worker.end_pass()
    assert status["last_pass_count"] == 3 and not status["in_pass"]
    (latest,) = store.people_counts()
    assert latest.people_count == 3 and latest.site_id == "shelter_3"

    worker.start_pass()  # robot is back at the start of the line
    run_frames(worker, clock, 3)
    clock.t += 1
    worker.process_frame(frame())  # heartbeat mid-pass
    assert store.people_counts()[0].people_count == 3  # still the last full pass
    worker.end_pass()
    assert store.people_counts()[0].people_count == 1  # line got shorter


def test_unmanaged_camera_passes_end_after_gap():
    clock = Clock()
    store, worker = make_worker(FakeDetector([1], [1], [1], []), clock)
    run_frames(worker, clock, 3)
    assert worker.pass_status()["in_pass"]
    run_frames(worker, clock, 41)  # 5.1 s with nobody in view
    status = worker.pass_status()
    assert not status["in_pass"] and status["last_pass_count"] == 1 and not status["managed"]
    assert store.people_counts()[0].people_count == 1


def test_tracks_only_when_due():
    clock = Clock()
    detector = FakeDetector([1])
    _, worker = make_worker(detector, clock)
    worker.process_frame(frame())
    clock.t += 0.0625
    worker.process_frame(frame())
    assert detector.calls == 1
    clock.t += 0.0625
    worker.process_frame(frame())
    assert detector.calls == 2


def test_publishes_frames():
    clock = Clock()
    store, worker = make_worker(FakeDetector([1]), clock)
    worker.process_frame(frame())
    seq, jpeg = store.latest_frame("cam_s3")
    assert seq == 1 and jpeg.startswith(b"\xff\xd8")


def test_video_file_without_loop_stops_at_end():
    cfg = CameraConfig("cam_v", "shelter_1", "/tmp/clip.mp4", loop=False)
    sources = []

    def open_source(c):
        sources.append(FakeSource(frames=3))
        return sources[-1]

    store, worker = make_worker(FakeDetector([1]), Clock(), cfg=cfg, open_source=open_source)
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
    counter = PassCounter()
    img = annotate(frame(), [Detection((5, 5, 50, 50), 0.9, 7), Detection((60, 5, 90, 50), 0.1)], 0.4, counter)
    assert img.shape == (120, 160, 3) and img.any()
    big = np.zeros((720, 1280, 3), dtype=np.uint8)
    decoded = cv2.imdecode(np.frombuffer(encode_jpeg(big), np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (360, 640, 3)


def test_is_due_keeps_10_fps_with_30_fps_camera():
    frames = [i / 30 for i in range(31)]  # one second of a 30 fps camera
    last, fired = float("-inf"), 0
    for t in frames:
        if is_due(last, 0.1, t):
            last, fired = t, fired + 1
    assert fired == 11  # every third frame, including t=0 and t=1
    assert not is_due(0.0, 0.1, 0.05)
