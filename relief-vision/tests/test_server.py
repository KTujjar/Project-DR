import pytest
from conftest import Clock, dets, frame
from fastapi.testclient import TestClient

from reliefvision.dashboard import DashboardBridge, DashboardState, iso_from_epoch
from reliefvision.server import create_app

CAMS = [("cam_s3", "shelter_3"), ("cam_s4", "shelter_4")]


def make_client(video):
    clock = Clock(1_793_400_000.0)
    state = DashboardState(CAMS, public_url="http://cv:8001", video=video, clock=clock)
    bridge = DashboardBridge("cam_s3", "shelter_3", state, min_track_hits=1, clock=clock)
    bridge.on_frame(frame(), dets((1, 0.9), (2, 0.7)), 0.0)
    clock.t += 1
    bridge.on_frame(frame(), dets((1, 0.9), (2, 0.7)), 1.0)
    return TestClient(create_app(state, {"cam_s3": bridge})), clock


@pytest.fixture
def client():
    return make_client(video=True)[0]


def test_health(client):
    assert client.get("/health").json() == {"ok": True, "cameras_online": 1}


def test_cameras_with_video(client):
    cams = {c["camera_id"]: c for c in client.get("/api/cameras").json()}
    assert cams["cam_s3"] == {
        "camera_id": "cam_s3", "site_id": "shelter_3",
        "stream_url": "http://cv:8001/api/cameras/cam_s3/stream.mjpg",
        "snapshot_url": "http://cv:8001/api/cameras/cam_s3/snapshot.jpg?t=1793400001000",
        "online": True, "last_frame_at": "2026-10-30T22:40:01.000Z",
    }
    assert "snapshot_url" not in cams["cam_s4"] and cams["cam_s4"]["online"] is False


def test_people_counts_latest_and_since(client):
    assert client.get("/api/people-counts").json() == [
        {"site_id": "shelter_3", "camera_id": "cam_s3", "timestamp": "2026-10-30T22:40:01.000Z",
         "people_count": 2, "confidence": 0.8}
    ]
    since = client.get("/api/people-counts", params={"since": iso_from_epoch(1_793_400_000.5)}).json()
    assert [c["timestamp"] for c in since] == ["2026-10-30T22:40:01.000Z"]
    assert client.get("/api/people-counts", params={"since": "yesterday"}).status_code == 422


def test_pass_endpoints(client):
    started = client.post("/api/cameras/cam_s3/pass/start").json()
    assert started["in_pass"] and started["managed"] and started["running_count"] == 0
    ended = client.post("/api/cameras/cam_s3/pass/end").json()
    assert not ended["in_pass"] and ended["last_pass_count"] == 0 and ended["passes_completed"] == 1
    assert client.get("/api/cameras/cam_s3/pass").json() == ended
    assert client.get("/api/people-counts").json()[0]["people_count"] == 0
    assert client.post("/api/cameras/cam_s4/pass/start").status_code == 404


def test_snapshot_with_video(client):
    res = client.get("/api/cameras/cam_s3/snapshot.jpg")
    assert res.status_code == 200 and res.content.startswith(b"\xff\xd8")
    assert client.get("/api/cameras/cam_s4/snapshot.jpg").status_code == 404
    assert client.get("/api/cameras/nope/stream.mjpg").status_code == 404


def test_no_frames_leave_without_video():
    client, _ = make_client(video=False)
    cam = client.get("/api/cameras").json()[0]
    assert "stream_url" not in cam and "snapshot_url" not in cam and cam["online"]
    assert client.get("/api/cameras/cam_s3/snapshot.jpg").status_code == 404
    assert client.get("/api/cameras/cam_s3/stream.mjpg").status_code == 404
    assert client.get("/api/people-counts").json()[0]["people_count"] == 2


def test_cors_allows_vite_dev_server(client):
    res = client.get("/api/cameras", headers={"Origin": "http://localhost:5173"})
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"


def crowd_event(**over):
    from reliefvision.schema import Event

    base = dict(site_id="shelter_3", camera_id="cam_s3", ts=1_793_400_000.0, camera_mode="fixed", people=12,
                people_is_lower_bound=True, density="high", crowd_fraction=0.21, children_est=2,
                mobility_aids={"wheelchair": 1, "walker": 0, "crutches": 0, "cane": 0, "stroller": 0},
                grid_rows=2, grid_cols=2, crowd_grid=[[0.1, 1.2], [0.0, 0.4]],
                hotspots=[{"region": "top-right", "row": 0, "col": 1, "score": 0.9}],
                insights=[{"level": "warn", "code": "hotspot", "message": "Crowded top-right"}])
    base.update(over)
    return Event(**base)


def stats_client(latest):
    state = DashboardState(CAMS)  # video off: stats are aggregate, so they don't need --serve-video
    return TestClient(create_app(state, {}, crowd_events={"cam_s3": lambda: latest}))


def test_stats_returns_latest_event():
    body = stats_client(crowd_event()).get("/api/cameras/cam_s3/stats").json()
    assert body["schema_version"] == "0.1" and body["people"] == 12 and body["people_is_lower_bound"]
    assert body["mobility_aids"]["wheelchair"] == 1 and body["hotspots"][0]["region"] == "top-right"
    assert body["insights"][0]["level"] == "warn"


def test_stats_null_before_first_event_and_404_for_unknown():
    c = stats_client(None)
    res = c.get("/api/cameras/cam_s3/stats")
    assert res.status_code == 200 and res.json() is None
    assert c.get("/api/cameras/cam_s4/stats").status_code == 404


# ---------------------------------------------------------------- camera chat endpoints
def chat_client(client, with_chat=True):
    from test_chat import JPEG
    from test_history import ev

    from reliefvision.chat import CameraChat
    from reliefvision.history import CameraHistory

    clock = Clock(1_793_430_000.0)
    h = CameraHistory(clock=clock)
    h.record_event(ev(clock.t - 30, camera="cam_s3"))
    h.set_frame("cam_s3", JPEG, ts=clock.t)
    h.add_note("cam_s3", "Two people at the desk.", ts=clock.t - 10)
    chat = CameraChat(h, client, clock=clock) if with_chat else None
    return TestClient(create_app(DashboardState(CAMS), {}, chat=chat, history=h))


def test_chat_endpoint_answers():
    from test_chat import FakeClient

    c = chat_client(FakeClient("Two people at the desk, calm."))
    res = c.post("/api/cameras/cam_s3/chat", json={"messages": [{"role": "user", "content": "What's happening?"}],
                                                   "site_name": "Lebanon Middle School"})
    assert res.status_code == 200
    assert res.json() == {"reply": "Two people at the desk, calm.", "used": {"image": True, "minutes": 30, "scene_notes": 1}}


def test_chat_endpoint_errors():
    from test_chat import FakeClient

    c = chat_client(FakeClient())
    q = {"messages": [{"role": "user", "content": "hi"}]}
    assert c.post("/api/cameras/nope/chat", json=q).status_code == 404
    assert c.post("/api/cameras/cam_s3/chat", json={"messages": []}).status_code == 422
    no_key = chat_client(None).post("/api/cameras/cam_s3/chat", json=q)
    assert no_key.status_code == 503 and "API key" in no_key.json()["detail"]
    assert chat_client(None, with_chat=False).post("/api/cameras/cam_s3/chat", json=q).status_code == 503


def test_scene_log_endpoint():
    from test_chat import FakeClient

    body = chat_client(FakeClient()).get("/api/cameras/cam_s3/scene-log").json()
    assert body["enabled"] is True and body["notes"][0]["text"] == "Two people at the desk."
    assert body["notes"][0]["time"].endswith("Z")
    assert chat_client(None).get("/api/cameras/cam_s3/scene-log").json()["enabled"] is False


def test_cors_allows_json_post_from_dashboard():
    from test_chat import FakeClient

    res = chat_client(FakeClient()).options("/api/cameras/cam_s3/chat", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    assert res.status_code == 200 and "content-type" in res.headers["access-control-allow-headers"].lower()
