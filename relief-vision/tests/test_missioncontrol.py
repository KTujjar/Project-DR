import logging
import time
import urllib.error

import numpy as np
import pytest
import supervision as sv
from conftest import dets
from fake_mission_control import FakeMissionControl

from reliefvision.missioncontrol import (MissionControlReporter, MissionControlSource, is_turtlebot_spec,
                                         normalized_boxes, pose_moved, read_token)
from reliefvision.observers import ObserverGroup

TOKEN = "s3cret-test-token"


def image(w=640, h=480, value=100):
    return np.full((h, w, 3), value, dtype=np.uint8)


@pytest.fixture
def fake():
    f = FakeMissionControl(TOKEN)
    yield f
    f.close()


def source(fake, token=TOKEN):
    return MissionControlSource("turtlebot:" + fake.url, process_fps=10, token=token, autostart=False)


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


# --------------------------------------------------------------------- helpers
def test_spec_and_token(tmp_path, monkeypatch):
    assert is_turtlebot_spec("turtlebot:http://127.0.0.1:8872") and not is_turtlebot_spec(0)
    f = tmp_path / "service.token"
    f.write_text(TOKEN + "\n")
    assert read_token(str(f)) == TOKEN
    monkeypatch.setenv("TURTBOT_MODEL_TOKEN_FILE", str(f))
    assert read_token(None) == TOKEN
    monkeypatch.delenv("TURTBOT_MODEL_TOKEN_FILE")
    with pytest.raises(ValueError):
        read_token(None)


@pytest.mark.parametrize("prev,cur,moving", [
    (None, None, False),
    (None, {"x": 0, "y": 0, "yaw": 0, "linear": 0.05, "angular": 0}, True),     # driving forward
    (None, {"x": 0, "y": 0, "yaw": 0, "linear": 0, "angular": 0.2}, True),      # turning in place
    ({"x": 0, "y": 0, "yaw": 0}, {"x": 0.005, "y": 0, "yaw": 0.01, "linear": 0, "angular": 0}, False),  # jitter
    ({"x": 0, "y": 0, "yaw": 0}, {"x": 0.05, "y": 0, "yaw": 0, "linear": 0, "angular": 0}, True),  # moved 5 cm
    ({"x": 0, "y": 0, "yaw": 3.13}, {"x": 0, "y": 0, "yaw": -3.13, "linear": 0, "angular": 0}, False),  # wraps ±pi
])
def test_pose_moved(prev, cur, moving):
    assert pose_moved(prev, cur) is moving


def test_normalized_boxes_clip_and_skip():
    d = sv.Detections(xyxy=np.array([[64, 48, 192, 240], [-10, -10, 32, 24], [600, 400, 700, 500], [5, 5, 5, 9]], float),
                      confidence=np.array([0.9, 0.8, 0.7, 0.6]), class_id=np.zeros(4, int))
    boxes = normalized_boxes(d, 640, 480)
    assert boxes[0] == {"label": "person", "confidence": 0.9, "bbox": [0.1, 0.1, 0.2, 0.4]}
    assert boxes[1]["bbox"][:2] == [0.0, 0.0]                      # clipped to the image
    assert all(0 <= v <= 1 for b in boxes for v in b["bbox"])
    assert boxes[2]["bbox"][0] + boxes[2]["bbox"][2] <= 1.0
    assert len(boxes) == 3                                          # zero-width box dropped
    assert normalized_boxes(sv.Detections.empty(), 640, 480) == []


def test_observer_group_fans_out_and_isolates_failures():
    calls = []

    class Ok:
        def on_frame(self, *a):
            calls.append("ok")

    class Broken:
        def on_frame(self, *a):
            raise RuntimeError("boom")

    ObserverGroup(Broken(), None, Ok()).on_frame(None, None, 0.0)
    assert calls == ["ok"]


# --------------------------------------------------------------------- source
def test_frames_flow_and_duplicates_are_not_refetched(fake):
    src = source(fake)
    assert src.base_url == fake.url
    fake.push_frame(image(320, 240))
    assert src.poll_once() is True
    assert src.poll_once() is False             # same frame id: no second download
    assert fake.frame_requests == 1
    frame, _ = next(src.frames())
    assert frame.shape == (240, 320, 3)
    assert src.frame_info()["id"] == "session-1"


def test_frame_info_matches_the_frame_actually_analysed(fake):
    src = source(fake)
    fake.push_frame(image())
    src.poll_once()
    frames = src.frames()
    next(frames)                                # pipeline takes session-1 ...
    fake.push_frame(image())
    src.poll_once()                             # ... while session-2 arrives
    assert src.frame_info()["id"] == "session-1"
    next(frames)
    assert src.frame_info()["id"] == "session-2"


def test_errors_raise_from_poll_once(fake):
    with pytest.raises(urllib.error.HTTPError) as e:
        source(fake).poll_once()                # no frame yet
    assert e.value.code == 503
    with pytest.raises(urllib.error.HTTPError) as e:
        source(fake, token="wrong").poll_once()
    assert e.value.code == 401


def test_mock_mode_svg_is_skipped(fake):
    fake.mode = "mock"
    src = source(fake)
    assert src.poll_once() is False and fake.frame_requests == 0


def test_motion_hint_follows_pose(fake):
    src = source(fake)
    fake.push_frame(image())
    src.poll_once()
    assert src.motion_hint() is False
    fake.set_pose(linear=0.1)
    src.poll_once()
    assert src.motion_hint() is True
    src._last_move = time.time() - 2            # hold window passed, robot stopped
    fake.set_pose(linear=0.0)
    src.poll_once()
    assert src.motion_hint() is False


def test_background_loop_survives_outage_and_recovers(fake, caplog):
    src = MissionControlSource("turtlebot:" + fake.url, process_fps=10, token=TOKEN, poll_fps=20)
    try:
        fake.input_error = 503
        time.sleep(0.2)
        fake.input_error = None
        fake.push_frame(image())
        assert wait_for(lambda: src.frame_info() is None and src._last_id == "session-1", timeout=5)
        assert next(src.frames())[0].shape == (480, 640, 3)
        assert TOKEN not in caplog.text
    finally:
        src.close()


def test_unreachable_server_never_ends_source(caplog):
    caplog.set_level(logging.WARNING)
    src = MissionControlSource("turtlebot:http://127.0.0.1:9", process_fps=10, token=TOKEN, poll_fps=20)
    try:
        assert wait_for(lambda: "unreachable" in caplog.text)
        assert src._alive and TOKEN not in caplog.text
    finally:
        src.close()


# --------------------------------------------------------------------- reporter
def test_reporter_posts_normalized_people_for_the_analysed_frame(fake):
    src = source(fake)
    fid = fake.push_frame(image())
    src.poll_once()
    frame, _ = next(src.frames())
    rep = MissionControlReporter(src)
    d = dets(1, 2)                               # boxes at x 10..30 and 40..60, y 10..80
    rep.on_frame(frame, d, 0.0)
    rep.on_frame(frame, d, 0.1)                 # same frame again: not re-posted
    assert wait_for(lambda: rep.posted == 1)
    (res,) = fake.results
    assert res["model_id"] == "reliefvision-people" and res["mock"] is False and res["frame_id"] == fid
    assert res["api_version"] == "1.0" and len(res["detections"]) == 2
    assert res["detections"][0]["bbox"] == [round(10 / 640, 4), round(10 / 480, 4), round(20 / 640, 4), round(70 / 480, 4)]


def test_reporter_sends_empty_list_and_ignores_expired(fake):
    src = source(fake)
    fake.push_frame(image())
    src.poll_once()
    frame, _ = next(src.frames())
    rep = MissionControlReporter(src)
    rep.on_frame(frame, sv.Detections.empty(), 0.0)
    assert wait_for(lambda: rep.posted == 1)
    assert fake.results[-1]["detections"] == []
    fake.frames.clear()                          # frame expired on the robot side -> 410, ignored
    fake.push_frame(image())
    src.poll_once()
    frame, _ = next(src.frames())
    fake.frames.clear()
    rep.on_frame(frame, dets(1), 0.1)
    time.sleep(0.3)
    assert rep.posted == 1                       # no crash, nothing accepted


def test_reporter_waits_for_a_robot_frame(fake):
    rep = MissionControlReporter(source(fake))
    rep.on_frame(image(), dets(1), 0.0)
    time.sleep(0.2)
    assert fake.results == [] and rep.posted == 0


# --------------------------------------------------------------------- full pipeline
def test_camera_worker_with_robot_source_feeds_dashboard_and_robot(fake):
    from reliefvision.config import load_config
    from reliefvision.dashboard import DashboardBridge, DashboardState
    from reliefvision.pipeline import CameraWorker

    class TwoPeople:
        def detect(self, frame):
            xyxy = np.array([[100, 100, 160, 260], [300, 120, 360, 280]], dtype=float)
            return sv.Detections(xyxy=xyxy, confidence=np.array([0.9, 0.8]), class_id=np.zeros(2, dtype=int))

    class Sink:
        def __init__(self):
            self.events = []

        def emit(self, ev):
            self.events.append(ev)

    cfg = load_config()
    cfg["aids"]["enabled"] = False
    cam = {"id": "cam_robot", "source": "turtlebot:" + fake.url, "site_id": "shelter_3", "mode": "auto"}
    src = MissionControlSource(cam["source"], 10, token=TOKEN, poll_fps=20)
    state = DashboardState([("cam_robot", "shelter_3")])
    bridge = DashboardBridge("cam_robot", "shelter_3", state, min_track_hits=1)
    reporter = MissionControlReporter(src)
    sink = Sink()
    worker = CameraWorker(cam, cfg, TwoPeople(), None, sink, max_frames=6,
                          source=src, observer=ObserverGroup(bridge, reporter))
    worker.start()
    for _ in range(40):                       # the "robot" keeps sending frames
        fake.push_frame(image())
        time.sleep(0.05)
        if worker.done:
            break
    worker.join(5)
    assert worker.error is None, worker.error
    assert worker.frames_processed == 6
    assert sink.events and sink.events[-1].site_id == "shelter_3" and sink.events[-1].people == 2
    assert bridge.pass_status()["running_count"] == 2                 # dashboard pass counting
    assert state.online_count() == 1
    assert wait_for(lambda: len(fake.results) >= 1)                    # boxes shown to the robot operator
    assert all(len(r["detections"]) == 2 and r["model_id"] == "reliefvision-people" for r in fake.results)
