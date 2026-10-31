import threading

import cv2
import numpy as np
import pytest
from fakes import FakeDetector
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from cv_service.api import create_app
from cv_service.camera_worker import CameraWorker
from cv_service.config import CameraConfig, Settings, parse_cameras
from cv_service.push_source import PushSource
from cv_service.state import Store

PHONE = CameraConfig("cam_s1", "shelter_1", "push")
WEBCAM = CameraConfig("cam_s3", "shelter_3", 0)


def jpeg(w=160, h=120) -> bytes:
    ok, buf = cv2.imencode(".jpg", np.full((h, w, 3), 128, dtype=np.uint8))
    assert ok
    return buf.tobytes()


def test_push_is_neither_file_nor_url():
    (cam,) = parse_cameras({"cameras": [{"camera_id": "p", "site_id": "s", "source": "push"}]})
    assert cam.is_push and not cam.is_file
    assert not WEBCAM.is_push


def test_push_source_returns_new_frames_once():
    src = PushSource()
    assert src.push_jpeg(jpeg(64, 48))
    ok, frame = src.read()
    assert ok and frame.shape == (48, 64, 3)


def test_push_source_reports_no_frame_without_disconnecting(monkeypatch):
    monkeypatch.setattr("cv_service.push_source.NO_FRAME_WAIT_S", 0.01)
    src = PushSource()
    assert src.read() == (True, None)
    src.push_jpeg(jpeg())
    src.read()
    assert src.read() == (True, None)  # the same frame isn't returned twice


def test_push_source_rejects_non_images():
    src = PushSource()
    assert not src.push_jpeg(b"not a jpeg")
    assert src.isOpened()


def test_worker_waits_on_push_source_until_stopped(monkeypatch):
    monkeypatch.setattr("cv_service.push_source.NO_FRAME_WAIT_S", 0.01)
    src = PushSource()
    store = Store([PHONE])
    worker = CameraWorker(PHONE, store, FakeDetector([1]), open_source=lambda c: src)
    worker.start()
    src.push_jpeg(jpeg())
    for _ in range(200):
        if store.latest_frame("cam_s1")[1]:
            break
        threading.Event().wait(0.01)
    worker.stop()
    worker.join(2)
    assert store.latest_frame("cam_s1")[1] is not None
    assert not worker.is_alive()


@pytest.fixture
def client():
    cams = [PHONE, WEBCAM]
    src = PushSource()
    app = create_app(Store(cams), Settings(cameras=cams), push_sources={"cam_s1": src})
    return TestClient(app), src


def test_websocket_push_delivers_frames(client):
    c, src = client
    with c.websocket_connect("/api/cameras/cam_s1/push") as ws:
        ws.send_bytes(jpeg(200, 100))
        ws.send_bytes(b"garbage is ignored")
        ws.send_bytes(jpeg(200, 100))
    ok, frame = src.read()
    assert ok and frame.shape == (100, 200, 3)


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
