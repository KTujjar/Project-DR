import threading

from conftest import Clock, dets, frame

from reliefvision.dashboard import DashboardBridge, DashboardState, PeopleCount, iso_from_epoch, is_due, parse_iso

CAMS = [("cam_s3", "shelter_3"), ("cam_s4", "shelter_4")]


def test_iso_matches_js_to_iso_string():
    assert iso_from_epoch(1793400541.123) == "2026-10-30T22:49:01.123Z"
    assert iso_from_epoch(0) == "1970-01-01T00:00:00.000Z"
    assert abs(parse_iso("2026-10-30T22:49:01.123Z") - 1793400541.123) < 1e-6


def test_is_due_keeps_10_fps_with_30_fps_camera():
    last, fired = float("-inf"), 0
    for t in [i / 30 for i in range(31)]:
        if is_due(last, 0.1, t):
            last, fired = t, fired + 1
    assert fired == 11


def pc(cam, at, n):
    return PeopleCount(site_id="s", camera_id=cam, timestamp=iso_from_epoch(at), people_count=n, confidence=0.9)


def test_state_latest_counts_since_and_pruning():
    clock = Clock(1000)
    state = DashboardState(CAMS, history_s=10, clock=clock)
    state.record_count(pc("cam_s3", 1000, 1))
    state.record_count(pc("cam_s4", 1001, 5))
    state.record_count(pc("cam_s3", 1002, 3))
    assert {c.camera_id: c.people_count for c in state.people_counts()} == {"cam_s3": 3, "cam_s4": 5}
    assert [c.people_count for c in state.people_counts(since=1000.5)] == [5, 3]
    clock.t = 1020
    state.record_count(pc("cam_s3", 1020, 2))
    assert [c.people_count for c in state.people_counts(since=0)] == [2]


def test_cameras_without_video_have_no_urls():
    clock = Clock(1000)
    state = DashboardState(CAMS, public_url="http://cv:8001/", video=False, clock=clock)
    state.record_frame("cam_s3", None, at=995.5)
    feeds = {f.camera_id: f for f in state.cameras()}
    assert feeds["cam_s3"].online and feeds["cam_s3"].stream_url is None and feeds["cam_s3"].snapshot_url is None
    assert feeds["cam_s3"].last_frame_at == iso_from_epoch(995.5)
    assert not feeds["cam_s4"].online and feeds["cam_s4"].last_frame_at == iso_from_epoch(1000)
    clock.t = 1006
    assert state.online_count() == 0


def test_cameras_with_video_have_stream_and_snapshot_urls():
    state = DashboardState(CAMS, public_url="http://cv:8001", video=True, clock=Clock(1000))
    state.record_frame("cam_s3", b"jpg", at=999)
    feed = state.cameras()[0]
    assert feed.stream_url == "http://cv:8001/api/cameras/cam_s3/stream.mjpg"
    assert feed.snapshot_url == "http://cv:8001/api/cameras/cam_s3/snapshot.jpg?t=999000"


def test_wait_for_frame_wakes_on_new_frame():
    state = DashboardState(CAMS, video=True)
    got = {}
    t = threading.Thread(target=lambda: got.update(f=state.wait_for_frame("cam_s3", 0, timeout=2)))
    t.start()
    state.record_frame("cam_s3", b"new")
    t.join(2)
    assert got["f"] == (1, b"new")


def make_bridge(video=False):
    clock = Clock()
    state = DashboardState(CAMS, video=video, clock=clock)
    return state, DashboardBridge("cam_s3", "shelter_3", state, conf=0.35, min_track_hits=3, pass_gap_s=5,
                                  clock=clock), clock


def run(bridge, clock, frames, ts0=0.0, step=0.125):
    ts = ts0
    for d in frames:
        bridge.on_frame(frame(), d, ts)
        ts += step
        clock.t += step
    return ts


def test_bridge_counts_people_who_left_and_heartbeats():
    state, bridge, clock = make_bridge()
    run(bridge, clock, [dets(1, 2)] * 3 + [dets(3)] * 3)
    assert bridge.pass_status()["running_count"] == 3
    clock.t += 1
    bridge.on_frame(frame(), dets(3), 2.0)
    (latest,) = state.people_counts()
    assert latest.people_count == 3 and latest.site_id == "shelter_3"


def test_bridge_managed_pass_publishes_total_on_end():
    state, bridge, clock = make_bridge()
    bridge.start_pass()
    ts = run(bridge, clock, [dets(1, 2, 3)] * 3)
    assert bridge.end_pass()["last_pass_count"] == 3
    assert state.people_counts()[0].people_count == 3
    bridge.start_pass()
    run(bridge, clock, [dets(4)] * 3, ts0=ts)
    assert state.people_counts()[0].people_count == 3  # held during the recount
    bridge.end_pass()
    assert state.people_counts()[0].people_count == 1


def test_bridge_pass_gap_uses_pipeline_time():
    state, bridge, clock = make_bridge()
    run(bridge, clock, [dets(1)] * 3)
    # Video file: pipeline time jumps 6 s while barely any wall time passes.
    bridge.on_frame(frame(), dets(), 6.5)
    status = bridge.pass_status()
    assert not status["in_pass"] and status["last_pass_count"] == 1


def test_bridge_ignores_untracked_detections():
    _, bridge, clock = make_bridge()
    d = dets(1)
    d.tracker_id = None
    run(bridge, clock, [d] * 5)
    assert bridge.pass_status()["running_count"] == 0


def test_bridge_stores_frames_only_with_video():
    state, bridge, clock = make_bridge(video=False)
    run(bridge, clock, [dets(1)])
    assert state.latest_frame("cam_s3") == (0, None) and state.online_count() == 1
    state, bridge, clock = make_bridge(video=True)
    run(bridge, clock, [dets(1)])
    seq, jpeg = state.latest_frame("cam_s3")
    assert seq == 1 and jpeg.startswith(b"\xff\xd8")


def test_bridge_ignores_unconfirmed_tracks():
    # ByteTrack reports -1 for people it hasn't confirmed yet; many newcomers' first frames
    # must not add up to a phantom "person -1".
    _, bridge, clock = make_bridge()
    run(bridge, clock, [dets(-1, -1)] * 5 + [dets(7)] * 3)
    assert bridge.pass_status()["running_count"] == 1
