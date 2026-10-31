"""Clearly simulated development data. This module never imports or connects to ROS."""
import math
import threading
import time


class MockBridge:
    def __init__(self, store, control):
        self.store, self.control = store, control
        self.finished = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.store.metadata.update({"robot": "Development simulator", "camera_note": "Illustrated placeholder; not a camera stream", "driver_status": "No hardware connections in mock mode"})

    def start(self):
        self.thread.start()

    def run(self):
        started = time.monotonic()
        while not self.finished.is_set():
            t = time.monotonic() - started
            now = time.time()
            ranges = []
            for index in range(360):
                angle = index * math.tau / 360
                boundary = min(3.5 / max(abs(math.cos(angle)), 0.01), 2.7 / max(abs(math.sin(angle)), 0.01))
                obstacle = 1.4 + 0.05 * math.sin(t) if 0.5 < angle < 0.8 else boundary
                if 3.1 < angle < 3.45:
                    obstacle = 2.0
                ranges.append(min(obstacle + 0.008 * math.sin(index * 7 + t), 3.5))
            self.store.update("scan", {"ranges": ranges, "angle_min": 0, "angle_increment": math.tau / 360,
                "range_min": 0.12, "range_max": 3.5, "frame_id": "simulated_base_scan", "valid_count": 360}, now)
            self.store.update("odom", {"x": 0.0, "y": 0.0, "yaw": 0.0, "linear": 0.0, "angular": 0.0}, now)
            self.store.update("imu", {"gyro": [0, 0, 0], "acceleration": [0, 0, 9.81]}, now)
            self.store.update("battery", {"voltage": 12.1, "percentage": 88.0}, now)
            self.store.update("camera", {"status": "placeholder", "width": 640, "height": 480, "format": "Illustration", "verified": False,"frame_id": "simulated-"+str(round(t*10)), "calibration":{"intrinsics":None}}, now)
            self.store.update("joints", {"names": ["wheel_left_joint", "wheel_right_joint"], "positions": [0, 0], "velocities": [0, 0]}, now)
            self.control.tick()
            self.finished.wait(0.1)

    def close(self):
        self.finished.set()
        self.thread.join(timeout=2)
