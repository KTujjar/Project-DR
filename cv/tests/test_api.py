import pytest
from fakes import FakeDetector
from fastapi.testclient import TestClient

from cv_service.api import create_app
from cv_service.camera_worker import CameraWorker
from cv_service.config import CameraConfig, Settings
from cv_service.state import Store
from cv_service.timeutil import iso_from_epoch
import numpy as np

CAMS = [CameraConfig("cam_s3", "shelter_3", 0), CameraConfig("cam_s4", "shelter_4", 1)]


class Clock:
    def __init__(self, t: float):
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def env():
    clock = Clock(1_793_400_000.0)
    settings = Settings(cameras=CAMS, public_url="http://cv:8001")
    store = Store(CAMS, clock=clock)
    worker = CameraWorker(CAMS[0], store, FakeDetector([0.9, 0.8], [0.9, 0.8, 0.7]), clock=clock)
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    worker.process_frame(frame)
    clock.t += 1
    worker.process_frame(frame)
    return TestClient(create_app(store, settings)), clock


def test_health(env):
    client, _ = env
    assert client.get("/health").json() == {"ok": True, "cameras_online": 1}


def test_cameras(env):
    client, _ = env
    cams = {c["camera_id"]: c for c in client.get("/api/cameras").json()}
    assert cams["cam_s3"] == {
        "camera_id": "cam_s3",
        "site_id": "shelter_3",
        "stream_url": "http://cv:8001/api/cameras/cam_s3/stream.mjpg",
        "snapshot_url": "http://cv:8001/api/cameras/cam_s3/snapshot.jpg?t=1793400001000",
        "online": True,
        "last_frame_at": "2026-10-30T22:40:01.000Z",
    }
    # Offline camera: no snapshot_url key at all (not null).
    assert "snapshot_url" not in cams["cam_s4"] and cams["cam_s4"]["online"] is False


def test_people_counts_latest_and_since(env):
    client, _ = env
    latest = client.get("/api/people-counts").json()
    assert latest == [
        {"site_id": "shelter_3", "camera_id": "cam_s3", "timestamp": "2026-10-30T22:40:01.000Z",
         "people_count": 2, "confidence": 0.8}
    ]  # smoothed: median_low of [2, 3]
    since = client.get("/api/people-counts", params={"since": iso_from_epoch(1_793_400_000.5)}).json()
    assert [c["timestamp"] for c in since] == ["2026-10-30T22:40:01.000Z"]
    assert len(client.get("/api/people-counts", params={"since": "1970-01-01T00:00:00.000Z"}).json()) == 2
    assert client.get("/api/people-counts", params={"since": "yesterday"}).status_code == 422


def test_snapshot(env):
    client, _ = env
    res = client.get("/api/cameras/cam_s3/snapshot.jpg?t=123")
    assert res.status_code == 200 and res.headers["content-type"] == "image/jpeg"
    assert res.content.startswith(b"\xff\xd8")
    assert client.get("/api/cameras/cam_s4/snapshot.jpg").status_code == 404
    assert client.get("/api/cameras/nope/snapshot.jpg").status_code == 404


def test_cors_allows_vite_dev_server(env):
    client, _ = env
    res = client.get("/api/cameras", headers={"Origin": "http://localhost:5173"})
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_stream_unknown_camera(env):
    client, _ = env
    assert client.get("/api/cameras/nope/stream.mjpg").status_code == 404
