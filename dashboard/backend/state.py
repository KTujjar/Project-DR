"""Thread-safe sensor histories with explicit provenance and approximate alignment."""
from collections import deque
from copy import deepcopy
import threading
import time


class SensorStore:
    def __init__(self, mode):
        self.mode = mode
        self.lock = threading.RLock()
        self.samples = {}
        self.metadata = {"robot": "turtle19", "model": "Burger", "camera_note": "Camera acquisition has not been verified", "errors": []}
        self.occupancy_map = None
        self.image = None
        self.image_mime = "image/jpeg"

    def update(self, name, data, stamp=None):
        with self.lock:
            history = self.samples.setdefault(name, deque(maxlen=60))
            now = time.monotonic()
            history.append({"data": data, "stamp": stamp, "received": now, "wall_time": time.time()})

    def set_image(self, image, mime="image/jpeg"):
        with self.lock:
            self.image, self.image_mime = image, mime

    def update_camera(self, data, image, mime, stamp):
        with self.lock:
            self.image, self.image_mime = image, mime
            self.update("camera", data, stamp)

    def describe(self, name):
        history = self.samples.get(name)
        if not history:
            return {"status": "missing", "hz": None, "age_s": None, "data": None}
        latest = history[-1]
        age = time.monotonic() - latest["received"]
        span = history[-1]["received"] - history[0]["received"]
        return {"status": "live" if age < 2 else "stale", "hz": (len(history) - 1) / span if span else None,
                "age_s": age, "stamp": latest["stamp"], "data": deepcopy(latest["data"])}

    def message(self):
        with self.lock:
            return {"mode": self.mode, "time": time.time(), "sensors": {name: self.describe(name) for name in ("scan", "odom", "imu", "battery", "camera", "joints")},
                    "metadata": deepcopy(self.metadata)}

    def aligned_snapshot(self, tolerance=0.25):
        with self.lock:
            required = ("camera", "scan", "odom")
            missing = [name for name in required if not self.samples.get(name)]
            reference = next((self.samples[name][-1] for name in required if self.samples.get(name)), None)
            chosen = {}
            for name, history in self.samples.items():
                if reference and reference["stamp"] is not None:
                    valid = [sample for sample in history if sample["stamp"] is not None]
                    sample = min(valid, key=lambda value: abs(value["stamp"] - reference["stamp"])) if valid else history[-1]
                else:
                    sample = history[-1]
                chosen[name] = deepcopy(sample)
            stamps = [chosen[name]["stamp"] for name in required if name in chosen and chosen[name]["stamp"] is not None]
            spread = max(stamps) - min(stamps) if len(stamps) >= 2 else None
            stale = [name for name in required if name in chosen and time.monotonic() - chosen[name]["received"] > 2]
            aligned = not missing and not stale and len(stamps) == len(required) and spread <= tolerance
            return {"mode": self.mode, "sensors": chosen, "synchronized": aligned,
                    "synchronization": {"method": "Nearest recorded header timestamps; approximate, not hardware-triggered",
                                        "spread_ms": spread * 1000 if spread is not None else None,
                                        "tolerance_ms": tolerance * 1000, "missing": missing, "stale": stale},
                    "image_bytes": self.image, "image_mime": self.image_mime}
