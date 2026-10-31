import threading

from cv_service.config import CameraConfig
from cv_service.schemas import PeopleCount
from cv_service.state import Store
from cv_service.timeutil import iso_from_epoch

CAMS = [CameraConfig("cam_a", "shelter_1", 0), CameraConfig("cam_b", "shelter_2", 1)]


class Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def pc(cam: str, site: str, at: float, n: int) -> PeopleCount:
    return PeopleCount(site_id=site, camera_id=cam, timestamp=iso_from_epoch(at), people_count=n, confidence=0.9)


def test_latest_count_per_camera_and_since():
    clock = Clock()
    store = Store(CAMS, clock=clock)
    store.record_count(pc("cam_a", "shelter_1", 1000, 1))
    store.record_count(pc("cam_b", "shelter_2", 1001, 5))
    store.record_count(pc("cam_a", "shelter_1", 1002, 3))
    latest = {c.camera_id: c.people_count for c in store.people_counts()}
    assert latest == {"cam_a": 3, "cam_b": 5}
    assert [c.people_count for c in store.people_counts(since=1000.5)] == [5, 3]


def test_history_is_pruned():
    clock = Clock(1000)
    store = Store(CAMS, history_s=10, clock=clock)
    store.record_count(pc("cam_a", "shelter_1", 1000, 1))
    clock.t = 1020
    store.record_count(pc("cam_a", "shelter_1", 1020, 2))
    assert [c.people_count for c in store.people_counts(since=0)] == [2]


def test_camera_feeds_online_offline_and_urls():
    clock = Clock(1000)
    store = Store(CAMS, clock=clock)
    store.record_frame("cam_a", b"jpg", at=995.5)
    feeds = {f.camera_id: f for f in store.cameras("http://cv:8001", offline_after_s=10)}

    a, b = feeds["cam_a"], feeds["cam_b"]
    assert a.online and a.site_id == "shelter_1"
    assert a.last_frame_at == iso_from_epoch(995.5)
    assert a.snapshot_url == "http://cv:8001/api/cameras/cam_a/snapshot.jpg?t=995500"
    assert a.stream_url == "http://cv:8001/api/cameras/cam_a/stream.mjpg"
    # Never produced a frame: offline, no snapshot, reports service start time.
    assert not b.online and b.snapshot_url is None
    assert b.last_frame_at == iso_from_epoch(1000)

    clock.t = 1006
    assert not {f.camera_id: f for f in store.cameras("http://cv:8001", 10)}["cam_a"].online
    assert store.online_count(10) == 0


def test_wait_for_frame_wakes_on_new_frame():
    store = Store(CAMS)
    seq, _ = store.latest_frame("cam_a")
    got = {}

    def reader():
        got["frame"] = store.wait_for_frame("cam_a", seq, timeout=2)

    t = threading.Thread(target=reader)
    t.start()
    store.record_frame("cam_a", b"new")
    t.join(timeout=2)
    assert got["frame"] == (seq + 1, b"new")


def test_wait_for_frame_times_out():
    store = Store(CAMS)
    assert store.wait_for_frame("cam_a", 0, timeout=0.01) == (0, None)
