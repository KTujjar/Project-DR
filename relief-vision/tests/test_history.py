import time

from conftest import Clock, dets, frame

from reliefvision.dashboard import DashboardBridge, DashboardState
from reliefvision.history import CameraHistory, RecordingSink
from reliefvision.schema import Event


def ev(ts, people=3, camera="cam_laptop", **kw):
    base = dict(site_id="shelter_1", camera_id=camera, ts=ts, camera_mode="fixed", people=people,
                density="low", crowd_fraction=0.1, grid_rows=1, grid_cols=1, crowd_grid=[[0.1]])
    base.update(kw)
    return Event(**base)


def test_window_prunes_events_passes_and_notes():
    clock = Clock(10_000)
    h = CameraHistory(window_s=1800, clock=clock)
    h.record_event(ev(10_000))
    h.record_pass("cam_laptop", 4)
    h.add_note("cam_laptop", "two people waiting")
    clock.t += 1801
    h.record_event(ev(clock.t, people=5))
    assert [e.people for e in h.events("cam_laptop")] == [5]
    assert h.passes("cam_laptop") == [] and h.notes("cam_laptop") == []
    assert h.latest_event("cam_laptop").people == 5


def test_recording_sink_records_and_forwards():
    class Sink:
        def __init__(self):
            self.got, self.closed = [], False

        def emit(self, e):
            self.got.append(e)

        def close(self):
            self.closed = True

    inner, h = Sink(), CameraHistory()
    sink = RecordingSink(inner, h)
    sink.emit(ev(time.time()))
    sink.close()
    assert len(inner.got) == 1 and h.latest_event("cam_laptop") is not None and inner.closed


def test_bridge_feeds_history_frames_and_passes():
    clock = Clock()
    h = CameraHistory(clock=clock)
    state = DashboardState([("cam_laptop", "shelter_1")], clock=clock)   # video off: frames still go to history
    b = DashboardBridge("cam_laptop", "shelter_1", state, min_track_hits=1, clock=clock, history=h)
    b.start_pass()
    for i in range(3):
        b.on_frame(frame(), dets(1, 2), i * 0.5)
        clock.t += 0.5
    jpeg, ts = h.latest_frame("cam_laptop")
    assert jpeg.startswith(b"\xff\xd8") and ts is not None
    assert state.latest_frame("cam_laptop") == (0, None)                # still not served without --serve-video
    b.end_pass()
    (p,) = h.passes("cam_laptop")
    assert p.total == 2
