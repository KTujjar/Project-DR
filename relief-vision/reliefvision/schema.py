"""Versioned event schema. This is the contract with the coordination platform.

Only aggregate numbers leave this module: no frames, no faces, no identities, no track IDs.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel

SCHEMA_VERSION = "0.1"


class Insight(BaseModel):
    level: Literal["info", "warn"]
    code: str
    message: str


class Hotspot(BaseModel):
    region: str          # camera-relative, e.g. "bottom-left"
    row: int
    col: int
    score: float         # 0..1, crowded AND barely moving


class Event(BaseModel):
    schema_version: str = SCHEMA_VERSION
    site_id: str
    camera_id: str
    ts: float                                   # wall-clock epoch seconds
    video_ts: Optional[float] = None            # position in source video (files) or same as ts
    pose: Optional[str] = None                  # optional label for robot waypoint / location

    camera_mode: Literal["fixed", "mobile"]     # mobile => flow/free-space metrics are None

    # --- how many people ---
    people: int
    people_is_lower_bound: bool = False         # True when heavy overlap means "at least N"
    density: Literal["low", "medium", "high", "packed"]
    crowd_fraction: float                       # share of the frame covered by people (0..1)

    # --- who may need more help (aggregate, rough) ---
    children_est: Optional[int] = None          # size-based estimate; None until calibrated
    mobility_aids: Optional[Dict[str, int]] = None   # wheelchair/walker/crutches/cane/stroller

    # --- movement (fixed camera only) ---
    avg_speed_bh_s: Optional[float] = None      # body-heights per second (walking ~1)
    stationary_fraction: Optional[float] = None
    stagnation_index: Optional[float] = None    # 0..1 crowded AND still
    dominant_flow: Optional[str] = None         # left/right/toward camera/away from camera/mixed
    flow_coherence: Optional[float] = None      # 1 = everyone same direction
    counterflow: bool = False

    # --- where it's crowded / where there's room ---
    free_space_fraction: Optional[float] = None  # of the area people have been seen using
    grid_rows: int
    grid_cols: int
    crowd_grid: List[List[float]]               # per-cell crowding, 0..1.5 (1 = cell at capacity)
    stagnation_grid: Optional[List[List[float]]] = None
    free_cells: Optional[List[List[int]]] = None   # [[row, col], ...] walkable but empty now
    hotspots: List[Hotspot] = []

    insights: List[Insight] = []                # plain-language notes for organizers
