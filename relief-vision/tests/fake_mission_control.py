"""A stand-in for rescue-bot's Mission Control perception API v1.0 (tests and local demos).

Implements the same contract as rescue-bot dashboard/backend/features.py: bearer token,
GET /api/v1/perception/input, GET /api/v1/perception/frames/{id} (410 when expired),
POST /api/v1/perception/results (410 unknown frame). No robot, no movement.

    python tests/fake_mission_control.py --port 8872 --token-file /tmp/token --source 0
serves webcam 0 as if it were the robot camera (for trying the dashboard without the robot).
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

import cv2
import numpy as np


class FakeMissionControl:
    def __init__(self, token: str = "test-token", port: int = 0):
        self.token = token
        self.mode = "hardware"
        self.frames: "OrderedDict[str, bytes]" = OrderedDict()
        self.current: Optional[Dict[str, Any]] = None
        self.pose: Dict[str, Any] = {"status": "live", "stamp": time.time(),
                                     "data": {"x": 0.0, "y": 0.0, "yaw": 0.0, "linear": 0.0, "angular": 0.0}}
        self.results: List[Dict[str, Any]] = []
        self.input_error: Optional[int] = None     # force e.g. 503 on the next input polls
        self.frame_requests = 0
        self.lock = threading.Lock()
        self._seq = 0
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # quiet
                pass

            def _send(self, code: int, body: bytes = b"", ctype: str = "application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authorized(self) -> bool:
                if self.headers.get("Authorization") != "Bearer " + fake.token:
                    self._send(401, b'{"detail":"Service token required"}')
                    return False
                return True

            def do_GET(self):
                if not self._authorized():
                    return
                with fake.lock:
                    if self.path == "/api/v1/perception/input":
                        if fake.input_error:
                            return self._send(fake.input_error, b"{}")
                        if fake.mode == "mock":
                            body = {"api_version": "1.0", "mode": "mock",
                                    "frame": {"id": "mock", "timestamp": time.time(), "width": 640, "height": 480,
                                              "mime": "image/svg+xml", "url": "/api/v1/perception/frames/mock"},
                                    "lidar": None, "pose": fake.pose}
                            return self._send(200, json.dumps(body).encode())
                        if not fake.current:
                            return self._send(503, b'{"detail":"No fresh camera frame"}')
                        body = {"api_version": "1.0", "mode": "hardware", "frame": dict(fake.current),
                                "lidar": {"status": "live"}, "pose": fake.pose}
                        return self._send(200, json.dumps(body).encode())
                    if self.path.startswith("/api/v1/perception/frames/"):
                        fake.frame_requests += 1
                        jpeg = fake.frames.get(self.path.rsplit("/", 1)[1])
                        if jpeg is None:
                            return self._send(410, b'{"detail":"Frame expired"}')
                        return self._send(200, jpeg, "image/jpeg")
                self._send(404, b"{}")

            def do_POST(self):
                if not self._authorized():
                    return
                if self.path != "/api/v1/perception/results":
                    return self._send(404, b"{}")
                result = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                with fake.lock:
                    if result.get("frame_id") not in fake.frames:
                        return self._send(410, b'{"detail":"Unknown/expired frame identity"}')
                    fake.results.append(result)
                self._send(200, json.dumps({"accepted": True, "model_id": result["model_id"],
                                            "movement_generated": False}).encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def push_frame(self, image: np.ndarray, keep: int = 90) -> str:
        """Publishes a new camera frame (like the Pi relay ingest); returns its id."""
        ok, buf = cv2.imencode(".jpg", image)
        assert ok
        with self.lock:
            self._seq += 1
            fid = f"session-{self._seq}"
            self.frames[fid] = buf.tobytes()
            while len(self.frames) > keep:
                self.frames.popitem(last=False)
            self.current = {"id": fid, "timestamp": time.time(), "width": image.shape[1], "height": image.shape[0],
                            "mime": "image/jpeg", "url": "/api/v1/perception/frames/" + fid}
            return fid

    def set_pose(self, **data) -> None:
        with self.lock:
            self.pose = {"status": "live", "stamp": time.time(), "data": {**self.pose["data"], **data}}

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Fake TurtleBot Mission Control serving a webcam/video as the robot camera")
    ap.add_argument("--port", type=int, default=8872)
    ap.add_argument("--token-file", required=True, help="file holding the bearer token reliefvision should send")
    ap.add_argument("--source", default="0", help="webcam index or video file to serve as robot frames")
    ap.add_argument("--fps", type=float, default=8.0)
    a = ap.parse_args()
    fake = FakeMissionControl(open(a.token_file).read().strip(), a.port)
    cap = cv2.VideoCapture(int(a.source) if a.source.isdigit() else a.source)
    print(f"fake Mission Control on {fake.url}; Ctrl-C to stop", flush=True)
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            fake.push_frame(cv2.resize(frame, (640, 480)))
            time.sleep(1 / a.fps)
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        fake.close()


if __name__ == "__main__":
    main()
