"""Local-only FastAPI/WebSocket dashboard. Real mode never falls back to mock data."""
import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .features import register

from .ai import MockAdapter, UnconfiguredAdapter
from .safety import ControlDenied, SafetyController
from .state import SensorStore

BASE = Path(__file__).resolve().parents[1]


def same_origin(origin, host):
    if not origin:
        return False
    parsed = urlsplit(origin)
    return parsed.scheme in ("http", "https") and parsed.netloc == host


def create_app(mode=None, data_directory=None):
    mode = mode or os.environ.get("TURTBOT_MODE", "mock")
    if mode not in ("mock", "hardware"):
        raise ValueError("TURTBOT_MODE must be mock or hardware")
    data_directory = Path(data_directory or os.environ.get("TURTBOT_DATA_DIR", str(BASE / "data")))
    store = SensorStore(mode)
    control = SafetyController(enabled=mode == "hardware" and os.environ.get("TURTBOT_ALLOW_MOTION") == "1")
    adapter = MockAdapter() if mode == "mock" else UnconfiguredAdapter()

    @asynccontextmanager
    async def lifespan(application):
        if mode == "mock":
            from .mock import MockBridge
            bridge = MockBridge(store, control)
            placeholder = BASE / "static" / "camera-placeholder.svg"
            if placeholder.exists():
                store.set_image(placeholder.read_bytes(), "image/svg+xml")
        else:
            from .ros_bridge import RosBridge
            bridge = RosBridge(store, control)
        application.state.bridge = bridge
        bridge.start()
        try:
            yield
        finally:
            bridge.close()

    app = FastAPI(title="TurtleBot Observatory", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.store, app.state.control = store, control
    app.state.mode = mode
    app.state.source_revision = hashlib.sha256(b"".join(p.read_bytes() for p in sorted((BASE / "backend").glob("*.py")))).hexdigest()[:16]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver", "[::1]"])
    register(app, store, control, data_directory, mode, same_origin)

    @app.middleware("http")
    async def secure_headers(request, call_next):
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin and not same_origin(origin, request.headers.get("host")):
            return JSONResponse({"detail": "Cross-origin actions are not allowed"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.get("/")
    async def index():
        return FileResponse(BASE / "static" / "index.html")

    @app.get("/api/health")
    async def health():
        return {"status": "running", "version": "mission-v1", "source_revision": app.state.source_revision, "metadata": store.message()["metadata"], "sensors": store.message()["sensors"], "mode": mode, "motion_enabled": control.enabled, "control": control.state(),
                "camera_verified": bool(store.message()["sensors"]["camera"]["data"] and store.message()["sensors"]["camera"]["data"].get("verified")),
                "ai_configured": False}

    @app.get("/api/camera")
    async def camera():
        with store.lock:
            status = store.describe("camera")
            if store.image is None or status["status"] != "live":
                raise HTTPException(503, "No fresh verified camera image is available")
            return Response(store.image, media_type=store.image_mime,
                            headers={"Cache-Control": "no-store", "X-Sensor-Provenance": mode})

    @app.post("/api/snapshots")
    async def capture():
        snapshot = store.aligned_snapshot()
        image = snapshot.pop("image_bytes")
        mime = snapshot.pop("image_mime")
        snapshot.update({"id": str(uuid4()), "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                         "camera_frame_available": image is not None, "ai": {"status": "not_requested"}})
        if mode == "hardware" and (image is None or not snapshot.get("sensors", {}).get("camera", {}).get("data", {}).get("verified")):
            snapshot["synchronized"] = False
            if "camera" not in snapshot["synchronization"]["missing"]:
                snapshot["synchronization"]["missing"].append("camera")
        data_directory.mkdir(parents=True, exist_ok=True)
        if image:
            suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/svg+xml": ".svg"}.get(mime)
            if suffix:
                filename = snapshot["id"] + suffix
                (data_directory / filename).write_bytes(image)
                snapshot["image_url"] = "/api/snapshots/" + snapshot["id"] + "/image"
                snapshot["image_file"] = filename
        (data_directory / (snapshot["id"] + ".json")).write_text(json.dumps(snapshot, allow_nan=False, indent=2))
        app.state.mission.add("snapshot", "Sensor snapshot saved", {"snapshot_id":snapshot["id"], "synchronized":snapshot["synchronized"], "mode":mode})
        return snapshot

    def load_snapshot(identifier):
        path = data_directory / (str(identifier) + ".json")
        if not path.exists():
            raise HTTPException(404, "Snapshot not found")
        return json.loads(path.read_text())

    @app.get("/api/snapshots/{identifier}/image")
    async def snapshot_image(identifier: UUID):
        snapshot = load_snapshot(identifier)
        filename = snapshot.get("image_file")
        if not filename:
            raise HTTPException(404, "This snapshot has no camera image")
        return FileResponse(data_directory / filename)

    @app.post("/api/snapshots/{identifier}/interpret")
    async def interpret(identifier: UUID):
        snapshot = load_snapshot(identifier)
        # The adapter receives immutable capture data and has no control-node reference.
        result = await adapter.interpret(snapshot)
        snapshot["ai"] = result
        (data_directory / (str(identifier) + ".json")).write_text(json.dumps(snapshot, allow_nan=False, indent=2))
        return result

    @app.websocket("/ws")
    async def websocket(websocket: WebSocket):
        if not same_origin(websocket.headers.get("origin"), websocket.headers.get("host")):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        owner = secrets.token_urlsafe(18)
        outgoing = asyncio.Queue()

        async def sender():
            while True:
                message = store.message()
                message.update({"models": app.state.model_views(), "type": "telemetry", "control": {**control.state(), "is_owner": control.owner == owner}})
                await websocket.send_json(message)
                while not outgoing.empty():
                    await websocket.send_json(outgoing.get_nowait())
                await asyncio.sleep(0.1)

        async def receiver():
            while True:
                message = await websocket.receive_json()
                try:
                    if not isinstance(message, dict):
                        raise ControlDenied("Invalid command")
                    action = message.get("action")
                    if action == "heartbeat":
                        control.heartbeat(owner)
                    elif action == "arm":
                        control.arm(owner)
                    elif action == "disarm":
                        if control.owner == owner:
                            control.disarm()
                    elif action == "stop":
                        control.disarm("Stop requested")
                    elif action == "release":
                        if control.owner == owner:
                            control.stop("Direction released")
                    elif action == "drive":
                        control.command(owner, float(message.get("linear", 0)), float(message.get("angular", 0)))
                    else:
                        raise ControlDenied("Unknown action")
                except (ControlDenied, TypeError, ValueError) as exc:
                    await outgoing.put({"type": "notice", "message": str(exc)})

        tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            with suppress(Exception):
                control.disconnect(owner)
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError, Exception):
                    await task
            with suppress(Exception):
                await websocket.close()

    app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
    return app


app = create_app()
