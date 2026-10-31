"""Shared data contracts (root CLAUDE.md). Field names must match the dashboard's TypeScript exactly."""

from pydantic import BaseModel, Field


# From Video Processing
class PeopleCount(BaseModel):
    site_id: str
    camera_id: str
    timestamp: str
    people_count: int = Field(ge=0)
    confidence: float = Field(ge=0, le=1)


# From Video Capture
class CameraFeed(BaseModel):
    camera_id: str
    site_id: str
    stream_url: str | None = None
    snapshot_url: str | None = None
    online: bool
    last_frame_at: str
