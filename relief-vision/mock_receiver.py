"""Tiny stand-in for the coordination platform so teammates can see/consume events.

    pip install fastapi uvicorn
    uvicorn mock_receiver:app --port 8000
    reliefvision --source video.mp4 --webhook http://localhost:8000/events

GET /latest        newest event per camera
GET /events?limit= recent events
GET /schema        JSON schema of the Event contract
"""
from collections import deque

from fastapi import FastAPI, Request

from reliefvision.schema import Event

app = FastAPI(title="reliefvision mock receiver")
recent = deque(maxlen=500)
latest = {}


@app.post("/events")
async def ingest(request: Request):
    ev = Event.model_validate(await request.json())   # rejects anything off-schema
    d = ev.model_dump()
    recent.append(d)
    latest[f"{ev.site_id}/{ev.camera_id}"] = d
    return {"ok": True}


@app.get("/latest")
def get_latest():
    return latest


@app.get("/events")
def get_events(limit: int = 50):
    return list(recent)[-limit:]


@app.get("/schema")
def schema():
    return Event.model_json_schema()
