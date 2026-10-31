"""Config loading: YAML on top of built-in defaults."""
from __future__ import annotations

import copy
from typing import Any, Dict, Optional

import yaml

DEFAULTS: Dict[str, Any] = {
    "site_id": "demo-site",
    "process_fps": 8,          # frames/sec actually analysed (5-10 is plenty for counting)
    "emit_interval_s": 2.0,    # how often an Event is produced per camera
    "device": None,            # None = let ultralytics choose; or "cpu", "cuda:0", "mps"
    "person": {"weights": "yolo11n.pt", "conf": 0.35, "imgsz": 640},
    # Open-vocabulary detector for wheelchairs / walkers / crutches / canes / strollers.
    # If it can't load (e.g. no network for its text encoder) it is disabled automatically.
    "aids": {
        "enabled": True,
        "weights": "yolov8s-worldv2.pt",
        "conf": 0.25,
        "imgsz": 640,
        "interval_s": 1.5,
    },
    "camera_motion": {"thresh_px_s": 4.0, "hold_s": 3.0},
    "grid": {"rows": 6, "cols": 8, "cell_capacity": 3},
    "overlay": {
        "grid": False,            # True = shade crowded grid cells on the video (or use --grid)
        "heat": None,             # None | "recent" | "cumulative": live heat layer (or use --heat)
        "heat_half_life_s": 10.0,  # how fast 'recent' heat fades
        "heat_follow": False,      # True = keep heat pinned to the scene while the camera moves (--follow-camera)
    },
    "metrics": {
        "count_window_s": 3.0,
        "speed_window_s": 3.0,
        "min_track_s": 1.0,
        "stationary_speed_bh_s": 0.2,   # body-heights per second; walking is ~0.8-1.5
        "walking_speed_bh_s": 0.8,
        "density_thresholds": [0.06, 0.18, 0.35],  # crowd_fraction cut-offs: low|medium|high|packed
        "overlap_thresh": 0.35,
        "overlap_frac_lower_bound": 0.3,
        "child_height_ratio": 0.72,
        "min_height_samples": 30,
        "free_space_learn_s": 20.0,
        "walkable_min_hits": 5,
        "free_cell_threshold": 0.15,
    },
    "events": {"jsonl": "events.jsonl", "webhook": None, "outbox_db": "outbox.sqlite"},
    # Dashboard API (reliefvision --serve). Off by default: nothing is served unless asked.
    "server": {
        "enabled": False,
        "host": "0.0.0.0",
        "port": 8001,
        "public_url": "http://localhost:8001",   # base URL browsers use for snapshot/stream links
        "cors_origins": ["http://localhost:5173", "http://127.0.0.1:5173"],
        "video": False,            # True (--serve-video) = annotated frames leave the module
    },
    # Unique-people-per-pass counting for the dashboard (robot / phone sweeping a line).
    "pass": {"min_track_hits": 3, "gap_s": 5.0},
    # Cameras may also set `site_id` (dashboard location; defaults to the top-level site_id)
    # and `source: push` (frames sent by the /phone page, needs --serve).
    "cameras": [{"id": "cam1", "source": 0, "mode": "auto"}],
}


def _merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    if not path:
        return copy.deepcopy(DEFAULTS)
    with open(path, "r") as f:
        user = yaml.safe_load(f) or {}
    return _merge(DEFAULTS, user)
