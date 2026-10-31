"""Entry point: `uv run cv-service`."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from .api import create_app
from .camera_worker import CameraWorker, authorize_webcams, open_capture
from .config import load_settings
from .detector import YoloPersonTracker
from .push_source import PushSource
from .state import Store

log = logging.getLogger("cv_service")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv(Path.cwd() / ".env")
    settings = load_settings()

    authorize_webcams(settings.cameras)
    store = Store(settings.cameras, history_s=settings.history_s)
    # Frames for "push" cameras arrive from the /phone page instead of being opened locally.
    push_sources = {cam.camera_id: PushSource() for cam in settings.cameras if cam.is_push}
    workers = [
        CameraWorker(
            cam,
            store,
            # One tracker per camera: track IDs are per video stream.
            YoloPersonTracker(settings.model, settings.device),
            conf=settings.conf,
            infer_every_s=settings.infer_every_s,
            min_track_hits=settings.min_track_hits,
            pass_gap_s=settings.pass_gap_s,
            open_source=(lambda _cfg, src=push_sources[cam.camera_id]: src) if cam.is_push else open_capture,
        )
        for cam in settings.cameras
    ]
    log.info("YOLO %s tracking %d camera(s)", settings.model, len(workers))
    if push_sources:
        log.info("Phone camera page: %s/phone (use the https tailscale serve address on iPhone)", settings.public_url)

    app = create_app(store, settings, {w.cfg.camera_id: w for w in workers}, push_sources)

    @asynccontextmanager
    async def lifespan(_app):
        for w in workers:
            w.start()
        yield
        for w in workers:
            w.stop()

    app.router.lifespan_context = lifespan
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
