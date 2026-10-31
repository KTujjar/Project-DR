"""The optional CameraWorker hooks (source=, observer=) used by --serve, run through the real pipeline."""
import numpy as np
import supervision as sv

from reliefvision.config import load_config
from reliefvision.dashboard import DashboardBridge, DashboardState
from reliefvision.pipeline import CameraWorker


class FakePersonDetector:
    """Two people standing still: stable boxes the real ByteTrack will track."""

    def detect(self, frame):
        xyxy = np.array([[100, 100, 160, 260], [300, 120, 360, 280]], dtype=float)
        return sv.Detections(xyxy=xyxy, confidence=np.array([0.9, 0.8]), class_id=np.zeros(2, dtype=int))


class FakeSource:
    def __init__(self, n):
        self.n = n

    def frames(self):
        for i in range(self.n):
            yield np.zeros((480, 640, 3), dtype=np.uint8), i / 8

    def motion_hint(self):
        return None

    def close(self):
        pass


class ListSink:
    def __init__(self):
        self.events = []

    def emit(self, ev):
        self.events.append(ev)


def run_worker(observer=None, cam=None):
    cfg = load_config()
    cfg["aids"]["enabled"] = False
    cam = cam or {"id": "cam_s3", "source": 0, "mode": "fixed"}
    sink = ListSink()
    w = CameraWorker(cam, cfg, FakePersonDetector(), None, sink, source=FakeSource(24), observer=observer)
    w.run()  # synchronously, in this thread
    assert w.error is None, w.error
    return w, sink


def test_without_hooks_behaviour_is_unchanged():
    w, sink = run_worker(cam={"id": "cam1", "source": 0, "mode": "fixed"})
    assert w.frames_processed == 24 and sink.events
    assert sink.events[-1].site_id == "demo-site" and sink.events[-1].people == 2


def test_observer_gets_tracked_frames_and_counts_people():
    state = DashboardState([("cam_s3", "shelter_3")])
    bridge = DashboardBridge("cam_s3", "shelter_3", state)
    w, sink = run_worker(observer=bridge)
    assert bridge.pass_status()["running_count"] == 2  # tracked, so counted once each
    bridge.end_pass()
    assert state.people_counts()[0].people_count == 2
    assert sink.events  # their Events are still emitted alongside


def test_per_camera_site_id_overrides_global():
    _, sink = run_worker(cam={"id": "cam_s3", "source": 0, "mode": "fixed", "site_id": "shelter_3"})
    assert sink.events[-1].site_id == "shelter_3"
