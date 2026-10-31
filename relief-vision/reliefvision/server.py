"""HTTP API for the coordinator dashboard (enabled with `reliefvision --serve`).

    GET  /health                            {ok, cameras_online}
    GET  /api/cameras                       CameraFeed[]
    GET  /api/people-counts?since=<iso>     PeopleCount[] (latest per camera without `since`)
    POST /api/cameras/{id}/pass/start|end   start / finish a pass along the line
    GET  /api/cameras/{id}/pass             pass status
    GET  /api/cameras/{id}/stats            latest crowd-metrics Event (null until the first one)
    GET  /phone                             iPhone camera page (Safari, needs https)
    WS   /api/cameras/{id}/push             the phone page sends JPEG frames here
    GET  /api/cameras/{id}/snapshot.jpg     only with --serve-video
    GET  /api/cameras/{id}/stream.mjpg      only with --serve-video
"""
from __future__ import annotations

import threading
from importlib.resources import files
from typing import Callable, Iterator, Mapping, Optional, Sequence

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from .dashboard import DashboardBridge, DashboardState, parse_iso
from .schema import Event
from .sources import PushSource

BOUNDARY = "frame"


def create_app(state: DashboardState, bridges: Mapping[str, DashboardBridge],
               push_sources: Optional[Mapping[str, PushSource]] = None,
               cors_origins: Sequence[str] = ("http://localhost:5173", "http://127.0.0.1:5173"),
               crowd_events: Optional[Mapping[str, Callable[[], Optional[Event]]]] = None) -> FastAPI:
    """`crowd_events` maps camera id -> a getter for that camera's latest Event (CameraWorker.last_event)."""
    push_sources = push_sources or {}
    crowd_events = crowd_events or {}
    phone_page = files("reliefvision").joinpath("static/phone.html").read_text()
    app = FastAPI(title="reliefvision dashboard API")
    app.add_middleware(CORSMiddleware, allow_origins=list(cors_origins), allow_methods=["GET", "POST"])

    def bridge(camera_id: str) -> DashboardBridge:
        if camera_id not in bridges:
            raise HTTPException(404, f"unknown camera {camera_id}")
        return bridges[camera_id]

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "cameras_online": state.online_count()}

    @app.get("/api/cameras")
    def cameras() -> JSONResponse:
        # Optional fields are omitted rather than null, matching the TypeScript `?:` contract.
        return JSONResponse([f.model_dump(exclude_none=True) for f in state.cameras()])

    @app.get("/api/people-counts")
    def people_counts(since: Optional[str] = Query(None, description="ISO 8601; omit for the latest per camera")) -> JSONResponse:
        try:
            since_s = parse_iso(since) if since else None
        except ValueError:
            raise HTTPException(422, "since must be an ISO 8601 timestamp")
        return JSONResponse([c.model_dump() for c in state.people_counts(since_s)])

    # The robot (or phone operator) calls start at one end of the line and end at the other.
    @app.post("/api/cameras/{camera_id}/pass/start")
    def start_pass(camera_id: str) -> dict:
        return bridge(camera_id).start_pass()

    @app.post("/api/cameras/{camera_id}/pass/end")
    def end_pass(camera_id: str) -> dict:
        return bridge(camera_id).end_pass()

    @app.get("/api/cameras/{camera_id}/pass")
    def pass_status(camera_id: str) -> dict:
        return bridge(camera_id).pass_status()

    # Full crowd metrics for one camera: its latest Event (aggregate only, like the events output).
    @app.get("/api/cameras/{camera_id}/stats")
    def stats(camera_id: str) -> JSONResponse:
        if camera_id not in crowd_events:
            raise HTTPException(404, f"no crowd stats for camera {camera_id}")
        ev = crowd_events[camera_id]()
        return JSONResponse(None if ev is None else ev.model_dump(mode="json"))

    # --- phone camera: the page captures frames and sends them here (phone -> laptop) ---
    @app.get("/phone", response_class=HTMLResponse)
    def phone() -> str:
        return phone_page

    @app.get("/api/push-cameras")
    def push_cameras() -> list:
        return list(push_sources)

    @app.websocket("/api/cameras/{camera_id}/push")
    async def push(ws: WebSocket, camera_id: str) -> None:
        source = push_sources.get(camera_id)
        if source is None:
            await ws.close(code=1008, reason=f"{camera_id} is not a push camera")
            return
        await ws.accept()
        try:
            while True:
                source.push_jpeg(await ws.receive_bytes())
        except WebSocketDisconnect:
            pass

    # --- video leaves the module only when explicitly enabled (--serve-video) ---
    if state.video:
        def require_camera(camera_id: str) -> None:
            if not state.has_camera(camera_id):
                raise HTTPException(404, f"unknown camera {camera_id}")

        @app.get("/api/cameras/{camera_id}/snapshot.jpg")
        def snapshot(camera_id: str) -> Response:
            require_camera(camera_id)
            _, jpeg = state.latest_frame(camera_id)
            if jpeg is None:
                raise HTTPException(404, "no frame yet")
            return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

        @app.get("/api/cameras/{camera_id}/stream.mjpg")
        def stream(camera_id: str) -> StreamingResponse:
            require_camera(camera_id)

            def frames() -> Iterator[bytes]:
                seq = 0
                while True:
                    seq, jpeg = state.wait_for_frame(camera_id, seq, timeout=5)
                    if jpeg is None:
                        continue
                    yield b"--" + BOUNDARY.encode() + b"\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"

            return StreamingResponse(frames(), media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}")

    return app


def run_in_thread(app: FastAPI, host: str, port: int) -> threading.Thread:
    """Starts uvicorn in a daemon thread so the CLI's camera loop keeps the main thread."""
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True, name="dashboard-api")
    thread.start()
    return thread
