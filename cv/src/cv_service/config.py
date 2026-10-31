import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

PUSH_SOURCE = "push"


@dataclass(frozen=True)
class CameraConfig:
    camera_id: str
    site_id: str
    source: int | str  # webcam index, stream URL, video file path, or "push" (phone page sends frames)
    loop: bool = True

    @property
    def is_push(self) -> bool:
        return self.source == PUSH_SOURCE

    @property
    def is_file(self) -> bool:
        return isinstance(self.source, str) and "://" not in self.source and not self.is_push


@dataclass(frozen=True)
class Settings:
    cameras: list[CameraConfig]
    host: str = "0.0.0.0"
    port: int = 8001
    public_url: str = "http://localhost:8001"
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    model: str = "yolov8n.pt"
    device: str = "mps"
    conf: float = 0.4
    infer_every_s: float = 0.1  # tracking needs several frames per second
    min_track_hits: int = 3
    pass_gap_s: float = 5.0
    offline_after_s: float = 10.0
    history_s: float = 600.0


def parse_cameras(data: object) -> list[CameraConfig]:
    if not isinstance(data, dict) or not isinstance(data.get("cameras"), list):
        raise ValueError("camera config must have a 'cameras' list")
    cameras: list[CameraConfig] = []
    for i, raw in enumerate(data["cameras"]):
        if not isinstance(raw, dict):
            raise ValueError(f"cameras[{i}] must be a mapping")
        missing = [k for k in ("camera_id", "site_id", "source") if raw.get(k) in (None, "")]
        if missing:
            raise ValueError(f"cameras[{i}] is missing {', '.join(missing)}")
        source = raw["source"]
        if isinstance(source, str) and source.isdigit():
            source = int(source)
        cameras.append(
            CameraConfig(
                camera_id=str(raw["camera_id"]),
                site_id=str(raw["site_id"]),
                source=source,
                loop=bool(raw.get("loop", True)),
            )
        )
    ids = [c.camera_id for c in cameras]
    if len(ids) != len(set(ids)):
        raise ValueError("camera_id values must be unique")
    return cameras


def load_cameras(path: str | Path) -> list[CameraConfig]:
    path = Path(path)
    cameras = parse_cameras(yaml.safe_load(path.read_text()))
    # Video file paths are relative to the config file.
    return [
        CameraConfig(c.camera_id, c.site_id, str((path.parent / c.source).resolve()), c.loop)
        if c.is_file and not Path(str(c.source)).is_absolute()
        else c
        for c in cameras
    ]


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    defaults = Settings(cameras=[])
    origins = env.get("CV_CORS_ORIGINS")
    return Settings(
        cameras=load_cameras(env.get("CV_CONFIG", "cameras.yaml")),
        host=env.get("CV_HOST", defaults.host),
        port=int(env.get("CV_PORT", defaults.port)),
        public_url=env.get("CV_PUBLIC_URL", defaults.public_url).rstrip("/"),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()) if origins else defaults.cors_origins,
        model=env.get("CV_MODEL", defaults.model),
        device=env.get("CV_DEVICE", defaults.device),
        conf=float(env.get("CV_CONF", defaults.conf)),
        infer_every_s=float(env.get("CV_INFER_EVERY_S", defaults.infer_every_s)),
        min_track_hits=int(env.get("CV_MIN_TRACK_HITS", defaults.min_track_hits)),
        pass_gap_s=float(env.get("CV_PASS_GAP_S", defaults.pass_gap_s)),
        offline_after_s=float(env.get("CV_OFFLINE_AFTER_S", defaults.offline_after_s)),
    )
