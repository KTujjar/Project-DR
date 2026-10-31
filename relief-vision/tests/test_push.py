import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from reliefvision.dashboard import DashboardState
from reliefvision.server import create_app
from reliefvision.sources import PushSource


def jpeg(w=160, h=120) -> bytes:
    ok, buf = cv2.imencode(".jpg", np.full((h, w, 3), 128, dtype=np.uint8))
    assert ok
    return buf.tobytes()


def first_frame(src: PushSource):
    """Reads one already-pushed frame through the source's own frames() loop, as the camera worker does."""
    return next(src.frames())[0]


def test_push_source_yields_pushed_frames():
    src = PushSource(process_fps=10)
    assert src.push_jpeg(jpeg(64, 48))
    assert first_frame(src).shape == (48, 64, 3)
    assert src.motion_hint() is None


def test_push_source_rejects_non_images():
    src = PushSource(process_fps=10)
    assert not src.push_jpeg(b"not a jpeg")


@pytest.fixture
def client():
    src = PushSource(process_fps=10)
    state = DashboardState([("cam_s1", "shelter_1"), ("cam_s3", "shelter_3")])
    return TestClient(create_app(state, {}, push_sources={"cam_s1": src})), src


def test_websocket_push_delivers_frames(client):
    c, src = client
    with c.websocket_connect("/api/cameras/cam_s1/push") as ws:
        ws.send_bytes(jpeg(200, 100))
        ws.send_bytes(b"garbage is ignored")
    assert first_frame(src).shape == (100, 200, 3)


def test_websocket_rejects_non_push_camera(client):
    c, _ = client
    with pytest.raises(WebSocketDisconnect) as exc:
        with c.websocket_connect("/api/cameras/cam_s3/push") as ws:
            ws.receive_bytes()
    assert exc.value.code == 1008


def test_phone_page_and_push_camera_list(client):
    c, _ = client
    page = c.get("/phone")
    assert page.status_code == 200 and "getUserMedia" in page.text
    assert c.get("/api/push-cameras").json() == ["cam_s1"]
