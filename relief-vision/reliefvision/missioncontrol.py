"""TurtleBot3 camera through rescue-bot's Mission Control (teammate model API v1.0).

The robot's camera is not a ROS topic: the Pi encodes JPEGs and Mission Control serves them
behind a private SSH tunnel (default http://127.0.0.1:8872). This module only uses its
documented, observation-only endpoints:

    GET  /api/v1/perception/input         latest frame id/url + pose (odometry) + lidar
    GET  /api/v1/perception/frames/{id}   that exact JPEG (410 once expired)
    POST /api/v1/perception/results       person boxes shown on the robot operator's video

Every request carries `Authorization: Bearer <token>` (rescue-bot's .robot/runtime/service.token).
The token is never logged or put in a URL. Nothing here can move the robot: the API has no
movement endpoint and every result response says `movement_generated: false`.

    source: "turtlebot:http://127.0.0.1:8872"     # in config.yaml, plus token_file
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from .sources import _LiveSource

log = logging.getLogger(__name__)

SPEC_PREFIX = "turtlebot:"
TOKEN_ENV = "TURTBOT_MODEL_TOKEN_FILE"   # same variable rescue-bot's example client reads
API_VERSION = "1.0"
MODEL_ID = "reliefvision-people"
MAX_DETECTIONS = 100
MAX_BACKOFF_S = 10.0

# Robot counts as moving above these (same thresholds as the ROS 2 odometry hint in sources.py).
MOVE_LINEAR_M_S = 0.02
MOVE_ANGULAR_RAD_S = 0.05
MOVE_DISTANCE_M = 0.02
MOVE_TURN_RAD = 0.03
MOTION_HOLD_S = 1.5


def is_turtlebot_spec(spec: Any) -> bool:
    return str(spec).startswith(SPEC_PREFIX)


def read_token(token_file: Optional[str]) -> str:
    """Token from the camera's token_file, else $TURTBOT_MODEL_TOKEN_FILE."""
    path = token_file or os.environ.get(TOKEN_ENV)
    if not path:
        raise ValueError(f"turtlebot camera needs token_file (or ${TOKEN_ENV}) pointing at Mission Control's service.token")
    token = Path(path).expanduser().read_text().strip()
    if not token:
        raise ValueError(f"token file {path} is empty")
    return token


def pose_moved(prev: Optional[Dict[str, float]], cur: Optional[Dict[str, float]]) -> bool:
    """True if the robot is moving: reported velocity, or position/heading changed since `prev`."""
    if not cur:
        return False
    if abs(cur.get("linear") or 0.0) > MOVE_LINEAR_M_S or abs(cur.get("angular") or 0.0) > MOVE_ANGULAR_RAD_S:
        return True
    if not prev:
        return False
    try:
        dist = math.hypot(cur["x"] - prev["x"], cur["y"] - prev["y"])
        turn = abs(math.atan2(math.sin(cur["yaw"] - prev["yaw"]), math.cos(cur["yaw"] - prev["yaw"])))
    except (KeyError, TypeError):
        return False
    return dist > MOVE_DISTANCE_M or turn > MOVE_TURN_RAD


class _Api:
    """Tiny authenticated JSON/bytes client (stdlib only, like rescue-bot's example client)."""

    def __init__(self, base_url: str, token: str, timeout: float = 3.0):
        self.base = base_url.rstrip("/")
        self._headers = {"Authorization": "Bearer " + token}
        self.timeout = timeout

    def get(self, path: str) -> Tuple[bytes, str]:
        req = urllib.request.Request(self.base + path, headers=self._headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return r.read(), r.headers.get("Content-Type", "")

    def post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        req = urllib.request.Request(self.base + path, data=json.dumps(payload).encode(), method="POST",
                                     headers={**self._headers, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read() or b"{}")


class MissionControlSource(_LiveSource):
    """Camera frames from the TurtleBot via Mission Control. Never gives up: retries with backoff."""

    def __init__(self, spec: str, process_fps: float, token_file: Optional[str] = None,
                 poll_fps: float = 5.0, token: Optional[str] = None, autostart: bool = True):
        super().__init__(process_fps)
        self.base_url = spec[len(SPEC_PREFIX):] if is_turtlebot_spec(spec) else spec
        self.api = _Api(self.base_url, token if token is not None else read_token(token_file))
        self.poll_period = 1.0 / max(poll_fps, 0.1)
        self._frame_lock = threading.Lock()
        # Identity of each decoded image, keyed by id(image), so we know exactly which robot frame
        # the pipeline analysed (newer frames may arrive while it works).
        self._infos: Dict[int, Dict[str, Any]] = {}
        self._yielded: Optional[Dict[str, Any]] = None
        self._last_id: Optional[str] = None
        self._prev_pose: Optional[Dict[str, float]] = None
        self._last_move = 0.0
        self._warned: set = set()
        if autostart:  # tests drive poll_once() directly
            threading.Thread(target=self._poll_loop, daemon=True, name="turtlebot-camera").start()

    # --- what the camera worker and reporter read ---
    def motion_hint(self) -> Optional[bool]:
        return (time.time() - self._last_move) < MOTION_HOLD_S

    def frames(self):
        for fr, ts in super().frames():
            with self._frame_lock:
                self._yielded = self._infos.get(id(fr))
            yield fr, ts

    def frame_info(self) -> Optional[Dict[str, Any]]:
        """{id, timestamp, width, height} of the robot frame most recently handed to the pipeline."""
        with self._frame_lock:
            return dict(self._yielded) if self._yielded else None

    # --- polling ---
    def _warn_once(self, key: str, msg: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.warning("turtlebot camera: %s", msg)

    def _poll_loop(self) -> None:
        backoff = 1.0
        while not self._stop:
            try:
                self.poll_once()
                backoff = 1.0
                self._warned.discard("unreachable")
                time.sleep(self.poll_period)
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    self._warn_once("401", "Mission Control rejected the token (401); check token_file")
                    time.sleep(5.0)
                elif e.code == 410:
                    time.sleep(self.poll_period)       # frame expired between input and fetch: re-poll
                else:                                   # 503 = no fresh camera frame yet
                    self._warn_once(f"http{e.code}", f"Mission Control returned {e.code}; retrying")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF_S)
            except (OSError, ValueError) as e:          # tunnel down, timeout, bad JSON
                self._warn_once("unreachable", f"Mission Control unreachable at {self.base_url} ({type(e).__name__}); retrying")
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_S)

    def poll_once(self) -> bool:
        """One input poll; fetches and offers the frame if it's new. Returns True if a frame was set."""
        body, _ = self.api.get("/api/v1/perception/input")
        sample = json.loads(body)
        pose = (sample.get("pose") or {}).get("data")
        if pose_moved(self._prev_pose, pose):
            self._last_move = time.time()
        if pose:
            self._prev_pose = pose

        frame = sample.get("frame") or {}
        if frame.get("mime") != "image/jpeg":
            self._warn_once("mock", "Mission Control is in mock mode (no camera JPEGs); waiting for hardware frames")
            return False
        if frame.get("id") == self._last_id:
            return False
        data, _ = self.api.get(frame["url"])
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return False
        self._last_id = frame["id"]
        with self._frame_lock:
            self._infos[id(img)] = {"id": frame["id"], "timestamp": frame.get("timestamp"),
                                    "width": img.shape[1], "height": img.shape[0]}
            while len(self._infos) > 8:          # only the newest few frames can still be in flight
                self._infos.pop(next(iter(self._infos)))
        self._set(img)
        return True


def normalized_boxes(dets, width: int, height: int, conf_floor: float = 0.0) -> List[Dict[str, Any]]:
    """Detections -> Mission Control v1 boxes: normalized [left, top, width, height], clipped inside the image."""
    out: List[Dict[str, Any]] = []
    if not len(dets) or width <= 0 or height <= 0:
        return out
    confs = dets.confidence if dets.confidence is not None else np.ones(len(dets))
    for (x1, y1, x2, y2), c in zip(np.asarray(dets.xyxy, dtype=float), confs):
        l, t = min(max(x1 / width, 0.0), 1.0), min(max(y1 / height, 0.0), 1.0)
        r, b = min(max(x2 / width, 0.0), 1.0), min(max(y2 / height, 0.0), 1.0)
        if r - l <= 0 or b - t <= 0 or not math.isfinite(float(c)) or c < conf_floor:
            continue
        out.append({"label": "person", "confidence": round(min(max(float(c), 0.0), 1.0), 3),
                    "bbox": [round(l, 4), round(t, 4), round(r - l, 4), round(b - t, 4)]})
        if len(out) >= MAX_DETECTIONS:
            break
    return out


class MissionControlReporter:
    """Observer: posts reliefvision's person boxes for each robot frame back to Mission Control.

    Posting happens on one background thread holding only the newest job, so the camera pipeline
    never waits on the network. Stale/expired results (409/410) are expected and ignored.
    """

    def __init__(self, source: MissionControlSource):
        self.source = source
        self._job: Optional[Dict[str, Any]] = None
        self._cond = threading.Condition()
        self._last_frame_id: Optional[str] = None
        self.posted = 0
        threading.Thread(target=self._post_loop, daemon=True, name="turtlebot-results").start()

    def on_frame(self, frame: np.ndarray, dets, ts: float) -> None:
        info = self.source.frame_info()
        if not info or info["id"] == self._last_frame_id:
            return                       # no robot frame yet, or already reported this one
        self._last_frame_id = info["id"]
        # Boxes are in the analysed frame's pixels; normalise by its size (same as the delivered JPEG).
        h, w = frame.shape[:2]
        payload = {"api_version": API_VERSION, "model_id": MODEL_ID, "mock": False, "frame_id": info["id"],
                   "timestamp": info["timestamp"], "detections": normalized_boxes(dets, w, h)}
        with self._cond:
            self._job = payload          # drop any older, not-yet-sent job
            self._cond.notify()

    def _post_loop(self) -> None:
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._job is not None)
                job, self._job = self._job, None
            try:
                self.source.api.post_json("/api/v1/perception/results", job)
                self.posted += 1
            except urllib.error.HTTPError as e:
                if e.code not in (409, 410):     # too old / expired frame: normal, just skip
                    log.warning("turtlebot results rejected (%s)", e.code)
            except (OSError, ValueError):
                pass                              # source logs connectivity problems
