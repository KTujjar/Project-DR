"""Entry point: `uv run cv-service`."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from .api import create_app
from .camera_worker import CameraWorker, authorize_webcams
from .config import load_settings
from .detector import YoloPersonDetector
from .state import Store

log = logging.getLogger("cv_service")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv(Path.cwd() / ".env")
    settings = load_settings()

    authorize_webcams(settings.cameras)
    detector = YoloPersonDetector(settings.model, settings.device)
    log.info("YOLO %s on %s, %d camera(s)", settings.model, detector.device, len(settings.cameras))

    store = Store(settings.cameras, history_s=settings.history_s)
    workers = [
        CameraWorker(cam, store, detector, conf=settings.conf, infer_every_s=settings.infer_every_s)
        for cam in settings.cameras
    ]

    app = create_app(store, settings)

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
