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
