"""Frame sources: video file, webcam, RTSP/phone stream, or a ROS 2 image topic.

Every source exposes:
    frames()        -> generator of (bgr_frame, timestamp_seconds)
    motion_hint()   -> True if the platform knows the camera is moving (robot odometry), else None
    close()

Source spec strings (used in config.yaml / --source):
    0, 1                         webcam index
    path/to/video.mp4            file (timestamps are simulated from the file's FPS)
    rtsp://... / http://...      network stream (phone camera apps, IP cams)
    ros2:/camera/image_raw/compressed
    ros2:/camera/image_raw/compressed?odom=/odom     (odom lets a parked robot count as 'fixed')
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Iterator, Optional, Tuple, Union

import cv2
import numpy as np

Frame = Tuple[np.ndarray, float]


class _LiveSource:
    """Keeps only the newest frame so slow processing never builds up latency."""

    is_live = True

    def __init__(self, process_fps: float):
        self.period = 1.0 / max(process_fps, 0.1)
        self._lock = threading.Lock()
        self._latest: Optional[np.ndarray] = None
        self._alive = True
        self._stop = False

    def _set(self, frame: np.ndarray) -> None:
        with self._lock:
            self._latest = frame

    def frames(self) -> Iterator[Frame]:
        next_t = time.time()
        while self._alive and not self._stop:
            now = time.time()
            if now < next_t:
                time.sleep(min(next_t - now, 0.05))
                continue
            with self._lock:
                fr, self._latest = self._latest, None
            if fr is None:
                time.sleep(0.01)
                continue
            next_t = now + self.period
            yield fr, now

    def motion_hint(self) -> Optional[bool]:
        return None

    def close(self) -> None:
        self._stop = True


class OpenCVSource(_LiveSource):
    def __init__(self, spec: Union[int, str], process_fps: float):
        super().__init__(process_fps)
        self.spec = spec
        self.cap = cv2.VideoCapture(spec)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open video source: {spec!r}")
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.src_fps = fps if fps and fps == fps and fps > 1 else 30.0
        self.is_live = isinstance(spec, int) or str(spec).startswith(
            ("rtsp://", "http://", "https://", "rtmp://")
        )
        self.process_fps = process_fps
        if self.is_live:
            threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        while not self._stop:
            ok, fr = self.cap.read()
            if not ok:
                self._alive = False
                break
            self._set(fr)

    def frames(self) -> Iterator[Frame]:
        if self.is_live:
            yield from super().frames()
            return
        # File: use simulated time so speed/wait metrics don't depend on how fast we process.
        step = max(1, int(round(self.src_fps / self.process_fps)))
        idx = 0
        while not self._stop:
            if not self.cap.grab():
                break
            if idx % step == 0:
                ok, fr = self.cap.retrieve()
                if not ok:
                    break
                yield fr, idx / self.src_fps
            idx += 1

    def close(self) -> None:
        super().close()
        self.cap.release()


class Ros2Source(_LiveSource):
    """ROS 2 image topic (compressed or raw). Needs a sourced ROS 2 environment (rclpy)."""

    def __init__(self, topic: str, process_fps: float, odom_topic: Optional[str] = None):
        super().__init__(process_fps)
        import rclpy  # imported lazily so the core runs without ROS installed
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import CompressedImage, Image

        if not rclpy.ok():
            rclpy.init(args=None)
        self._node = rclpy.create_node(f"reliefvision_{uuid.uuid4().hex[:6]}")
        self._last_move = 0.0
        self._has_odom = odom_topic is not None

        if topic.endswith("compressed"):
            self._node.create_subscription(
                CompressedImage, topic, self._on_compressed, qos_profile_sensor_data
            )
        else:
            self._node.create_subscription(Image, topic, self._on_raw, qos_profile_sensor_data)

        if odom_topic:
            from nav_msgs.msg import Odometry

            self._node.create_subscription(Odometry, odom_topic, self._on_odom, 10)

        self._exec = SingleThreadedExecutor()
        self._exec.add_node(self._node)
        threading.Thread(target=self._exec.spin, daemon=True).start()

    def _on_compressed(self, msg) -> None:
        fr = cv2.imdecode(np.frombuffer(msg.data, np.uint8), cv2.IMREAD_COLOR)
        if fr is not None:
            self._set(fr)

    def _on_raw(self, msg) -> None:
        ch = {"mono8": 1, "rgb8": 3, "bgr8": 3}.get(msg.encoding)
        if ch is None:
            return
        arr = np.frombuffer(msg.data, np.uint8).reshape(msg.height, msg.step)[:, : msg.width * ch]
        arr = arr.reshape(msg.height, msg.width, ch) if ch == 3 else arr
        if msg.encoding == "rgb8":
            arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        elif msg.encoding == "mono8":
            arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
        self._set(arr.copy())

    def _on_odom(self, msg) -> None:
        lin, ang = msg.twist.twist.linear, msg.twist.twist.angular
        if abs(lin.x) + abs(lin.y) > 0.02 or abs(ang.z) > 0.05:
            self._last_move = time.time()

    def motion_hint(self) -> Optional[bool]:
        if not self._has_odom:
            return None
        return (time.time() - self._last_move) < 1.5

    def close(self) -> None:
        super().close()
        try:
            self._exec.shutdown()
            self._node.destroy_node()
        except Exception:
            pass


def open_source(spec: Union[int, str], process_fps: float):
    s = str(spec)
    if s.startswith("ros2:"):
        topic, _, query = s[5:].partition("?odom=")
        return Ros2Source(topic, process_fps, odom_topic=query or None)
    if s.isdigit():
        return OpenCVSource(int(s), process_fps)
    return OpenCVSource(s, process_fps)
