"""HTTP API the dashboard (or the team backend) polls."""

from typing import Iterator, Mapping, Protocol

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .config import Settings
from .state import Store
from .timeutil import parse_iso

BOUNDARY = "frame"


class PassControl(Protocol):
    """Start/end a pass along the line (implemented by CameraWorker)."""

    def start_pass(self) -> dict: ...
    def end_pass(self) -> dict: ...
    def pass_status(self) -> dict: ...


def create_app(store: Store, settings: Settings, passes: Mapping[str, PassControl] | None = None) -> FastAPI:
    passes = passes or {}
    app = FastAPI(title="Project-DR CV service")
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET", "POST"])

    def require_pass_control(camera_id: str) -> PassControl:
        if camera_id not in passes:
            raise HTTPException(404, f"unknown camera {camera_id}")
        return passes[camera_id]

    def require_camera(camera_id: str) -> None:
        if not store.has_camera(camera_id):
            raise HTTPException(404, f"unknown camera {camera_id}")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "cameras_online": store.online_count(settings.offline_after_s)}

    @app.get("/api/cameras")
    def cameras() -> JSONResponse:
        feeds = store.cameras(settings.public_url, settings.offline_after_s)
        # Optional fields are omitted rather than null, matching the TypeScript `?:` contract.
        return JSONResponse([f.model_dump(exclude_none=True) for f in feeds])

    @app.get("/api/people-counts")
    def people_counts(since: str | None = Query(None, description="ISO 8601; omit for the latest count per camera")) -> JSONResponse:
        try:
            since_s = parse_iso(since) if since else None
        except ValueError:
            raise HTTPException(422, "since must be an ISO 8601 timestamp")
        return JSONResponse([c.model_dump() for c in store.people_counts(since_s)])

    # The robot (or phone operator) calls start at one end of the line and end at the other.
    @app.post("/api/cameras/{camera_id}/pass/start")
    def start_pass(camera_id: str) -> dict:
        return require_pass_control(camera_id).start_pass()

    @app.post("/api/cameras/{camera_id}/pass/end")
    def end_pass(camera_id: str) -> dict:
        return require_pass_control(camera_id).end_pass()

    @app.get("/api/cameras/{camera_id}/pass")
    def pass_status(camera_id: str) -> dict:
        return require_pass_control(camera_id).pass_status()

    @app.get("/api/cameras/{camera_id}/snapshot.jpg")
    def snapshot(camera_id: str) -> Response:
        require_camera(camera_id)
        _, jpeg = store.latest_frame(camera_id)
        if jpeg is None:
            raise HTTPException(404, "no frame yet")
        return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/api/cameras/{camera_id}/stream.mjpg")
    def stream(camera_id: str) -> StreamingResponse:
        require_camera(camera_id)

        def frames() -> Iterator[bytes]:
            seq = 0
            while True:
                seq, jpeg = store.wait_for_frame(camera_id, seq, timeout=5)
                if jpeg is None:
                    continue
                yield b"--" + BOUNDARY.encode() + b"\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"

        return StreamingResponse(frames(), media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}")

    return app
