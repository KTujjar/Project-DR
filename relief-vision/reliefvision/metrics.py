"""Scene analytics: turns tracked person boxes into aggregate organizer-facing statistics.

Everything here is aggregate. Track IDs are used internally (to measure movement) and never
leave this module except as a set of IDs for the on-screen overlay.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any, Dict, List, Optional, Set

import numpy as np

DENSITY_LEVELS = ["low", "medium", "high", "packed"]


def region_name(r: int, c: int, rows: int, cols: int) -> str:
    v = ["top", "middle", "bottom"][min(2, int(r * 3 / rows))]
    h = ["left", "center", "right"][min(2, int(c * 3 / cols))]
    if v == "middle" and h == "center":
        return "center"
    if v == "middle":
        return h
    if h == "center":
        return v
    return f"{v}-{h}"


class SceneAnalyzer:
    def __init__(self, cfg: Dict[str, Any]):
        self.m = cfg["metrics"]
        self.rows, self.cols = cfg["grid"]["rows"], cfg["grid"]["cols"]
        self.cap = float(cfg["grid"]["cell_capacity"])
        self.tracks: Dict[int, Dict[str, Any]] = {}
        self.count_hist: deque = deque()
        self.samples: deque = deque(maxlen=800)   # (ts, ground_y, box_height) of standing adults
        self._reset_spatial(0.0)
        self.last_mode: Optional[str] = None

    def _reset_spatial(self, ts: float) -> None:
        self.walk_hits = np.zeros((self.rows, self.cols))
        self.grid_ema = np.zeros((self.rows, self.cols))
        self.stag_ema = np.zeros((self.rows, self.cols))
        self.fixed_since = ts

    # ------------------------------------------------------------------ child estimate
    def _fit_expected_height(self, H: int) -> Optional[np.ndarray]:
        """Robust fit of 'how tall is an adult at this image row' from the people we see.

        Assumes most people are adults. Anything much shorter than the fit is a child candidate.
        """
        if len(self.samples) < self.m["min_height_samples"]:
            return None
        s = np.array(self.samples)
        y, h = s[:, 1], s[:, 2]
        keep = np.ones(len(s), bool)
        coef = np.array([0.0, float(np.median(h))])
        for _ in range(3):
            if keep.sum() < 15:
                break
            if y[keep].max() - y[keep].min() < 0.12 * H:
                coef = np.array([0.0, float(np.median(h[keep]))])
            else:
                coef = np.polyfit(y[keep], h[keep], 1)
                if coef[0] <= 0:  # perspective says lower in frame = bigger; otherwise distrust slope
                    coef = np.array([0.0, float(np.median(h[keep]))])
            ratio = h / np.maximum(np.polyval(coef, y), 1.0)
            keep = (ratio > 0.75) & (ratio < 1.4)
        return coef

    # ------------------------------------------------------------------ main update
    def update(self, dets, shape, ts: float, mode: str,
               aid_counts: Optional[Dict[str, int]]) -> Dict[str, Any]:
        m = self.m
        H, W = shape[:2]
        xyxy = np.asarray(dets.xyxy, dtype=float).reshape(-1, 4) if len(dets) else np.zeros((0, 4))
        n = len(xyxy)
        ids = (np.asarray(dets.tracker_id).astype(int)
               if len(dets) and dets.tracker_id is not None else -(np.arange(n) + 1))
        x1, y1, x2, y2 = (xyxy[:, i] for i in range(4))
        w, h, cx = x2 - x1, y2 - y1, (x1 + x2) / 2

        if mode != self.last_mode:           # view changed => spatial memory is invalid
            self.tracks.clear()
            self._reset_spatial(ts)
            self.last_mode = mode

        # --- smoothed headcount
        self.count_hist.append((ts, n))
        while self.count_hist and ts - self.count_hist[0][0] > m["count_window_s"]:
            self.count_hist.popleft()
        people = int(round(float(np.median([c for _, c in self.count_hist]))))

        # --- overlap => "at least N"
        overlap_frac = 0.0
        if n >= 2:
            ix = np.clip(np.minimum(x2[:, None], x2[None]) - np.maximum(x1[:, None], x1[None]), 0, None)
            iy = np.clip(np.minimum(y2[:, None], y2[None]) - np.maximum(y1[:, None], y1[None]), 0, None)
            inter = ix * iy
            area = w * h
            frac = inter / np.maximum(np.minimum(area[:, None], area[None]), 1.0)
            np.fill_diagonal(frac, 0)
            overlap_frac = float((frac.max(axis=1) > m["overlap_thresh"]).mean())
        lower_bound = overlap_frac >= m["overlap_frac_lower_bound"]

        # --- how much of the view is covered by people -> density category
        sc = 4
        mask = np.zeros((H // sc + 2, W // sc + 2), np.uint8)
        for a, b, c, d in np.clip(xyxy, 0, [W, H, W, H]):
            mask[int(b / sc): int(d / sc) + 1, int(a / sc): int(c / sc) + 1] = 1
        crowd_fraction = float(mask.mean())
        lvl = sum(crowd_fraction >= t for t in m["density_thresholds"])
        if lower_bound:
            lvl = min(3, lvl + 1)

        # --- per-track history (for speed / flow)
        for i in range(n):
            st = self.tracks.setdefault(int(ids[i]), {"hist": deque(), "ratios": deque(maxlen=20), "last": ts})
            st["hist"].append((ts, cx[i], y2[i], h[i]))
            st["last"] = ts
            while st["hist"] and ts - st["hist"][0][0] > m["speed_window_s"] + 0.5:
                st["hist"].popleft()
        for t in [t for t, s in self.tracks.items() if ts - s["last"] > 2.0]:
            del self.tracks[t]

        # --- children (size relative to adults at the same image depth)
        truncated = (x1 < 2) | (y1 < 2) | (x2 > W - 2) | (y2 > H - 2)
        eligible = (~truncated) & (h / np.maximum(w, 1) > 1.4) & (h > 0.06 * H) if n else np.zeros(0, bool)
        for i in np.nonzero(eligible)[0]:
            self.samples.append((ts, y2[i], h[i]))
        while self.samples and ts - self.samples[0][0] > 90:
            self.samples.popleft()
        coef = self._fit_expected_height(H)
        child_ids: Set[int] = set()
        children_est: Optional[int] = None
        if coef is not None:
            for i in np.nonzero(eligible)[0]:
                st = self.tracks[int(ids[i])]
                st["ratios"].append(h[i] / max(float(np.polyval(coef, y2[i])), 1.0))
                if len(st["ratios"]) >= 5 and float(np.median(st["ratios"])) < m["child_height_ratio"]:
                    child_ids.add(int(ids[i]))
            children_est = len(child_ids)

        # --- movement (steady camera only)
        speeds: Dict[int, float] = {}
        vecs: List[tuple] = []
        if mode == "fixed":
            for i in range(n):
                hist = self.tracks[int(ids[i])]["hist"]
                if len(hist) >= 2 and hist[-1][0] - hist[0][0] >= m["min_track_s"]:
                    dt = hist[-1][0] - hist[0][0]
                    hmed = float(np.median([q[3] for q in hist]))
                    vx = (hist[-1][1] - hist[0][1]) / dt / hmed
                    vy = (hist[-1][2] - hist[0][2]) / dt / hmed
                    sp = math.hypot(vx, vy)
                    speeds[int(ids[i])] = sp
                    if sp >= m["stationary_speed_bh_s"]:
                        vecs.append((vx, vy))
        avg_speed = stationary_fraction = None
        if speeds:
            arr = np.array(list(speeds.values()))
            avg_speed = round(float(arr.mean()), 2)
            stationary_fraction = round(float((arr < m["stationary_speed_bh_s"]).mean()), 2)

        flow = coherence = None
        counterflow = False
        if len(vecs) >= 3:
            v = np.array(vecs)
            mean = v.mean(axis=0)
            coherence = float(np.linalg.norm(mean) / max(np.linalg.norm(v, axis=1).mean(), 1e-6))
            if coherence < 0.4 and len(vecs) >= 4:
                flow, counterflow = "mixed", True
            elif abs(mean[0]) >= abs(mean[1]):
                flow = "right" if mean[0] > 0 else "left"
            else:
                flow = "toward camera" if mean[1] > 0 else "away from camera"
            coherence = round(coherence, 2)

        # --- where is it crowded (grid), where is it still, where is there room
        gr = np.clip((y2 / H * self.rows).astype(int), 0, self.rows - 1) if n else np.zeros(0, int)
        gc = np.clip((cx / W * self.cols).astype(int), 0, self.cols - 1) if n else np.zeros(0, int)
        counts = np.zeros((self.rows, self.cols))
        spd_sum = np.zeros_like(counts)
        spd_n = np.zeros_like(counts)
        for i in range(n):
            counts[gr[i], gc[i]] += 1
            s = speeds.get(int(ids[i]))
            if s is not None:
                spd_sum[gr[i], gc[i]] += s
                spd_n[gr[i], gc[i]] += 1
        self.grid_ema = 0.4 * counts + 0.6 * self.grid_ema
        crowd_grid = np.clip(self.grid_ema / self.cap, 0, 1.5)

        stag_grid = hotspots = free_cells = None
        free_fraction: Optional[float] = None
        stagnation_index: Optional[float] = None
        if mode == "fixed":
            with np.errstate(invalid="ignore", divide="ignore"):
                cell_speed = np.where(spd_n > 0, spd_sum / np.maximum(spd_n, 1), np.nan)
            inst = np.where(
                np.isnan(cell_speed), 0.0,
                np.clip(counts / self.cap, 0, 1) * (1 - np.clip(cell_speed / m["walking_speed_bh_s"], 0, 1)),
            )
            self.stag_ema = 0.4 * inst + 0.6 * self.stag_ema
            stag_grid = np.round(self.stag_ema, 2)
            hotspots = [
                {"region": region_name(int(r), int(c), self.rows, self.cols), "row": int(r), "col": int(c),
                 "score": float(stag_grid[r, c])}
                for r, c in sorted(zip(*np.nonzero(stag_grid >= 0.5)), key=lambda rc: -stag_grid[rc])[:3]
            ]
            if stationary_fraction is not None:
                stagnation_index = round(float(min(1.0, crowd_fraction / 0.2) * stationary_fraction), 2)

            # Free space = places people have been seen using ("walkable") that are empty right now.
            self.walk_hits += counts > 0
            walkable = self.walk_hits >= m["walkable_min_hits"]
            if ts - self.fixed_since >= m["free_space_learn_s"] and walkable.sum() >= 4:
                free = walkable & (self.grid_ema < m["free_cell_threshold"])
                free_fraction = round(float(free.sum() / walkable.sum()), 2)
                free_cells = [[int(r), int(c)] for r, c in zip(*np.nonzero(free))]

        # --- plain-language insights for organizers
        insights: List[Dict[str, str]] = []
        if mode == "mobile":
            insights.append({"level": "info", "code": "mobile_camera",
                             "message": "Camera is moving: showing snapshot counts only (flow and free-space paused)."})
        if lvl >= 2:
            who = f"at least {people}" if lower_bound else f"{people}"
            insights.append({"level": "warn", "code": "crowd_density",
                             "message": f"Crowd density is {DENSITY_LEVELS[lvl]} ({who} people in view)."})
        if hotspots:
            insights.append({"level": "warn", "code": "bottleneck",
                             "message": f"Crowded and barely moving in the {hotspots[0]['region']} of the view: "
                                        "possible bottleneck or stalled line."})
        if stationary_fraction is not None and people >= 5 and stationary_fraction >= 0.8:
            insights.append({"level": "info", "code": "mostly_stationary",
                             "message": f"{int(stationary_fraction * 100)}% of people are standing still "
                                        "(waiting, or flow is blocked)."})
        if counterflow:
            insights.append({"level": "warn", "code": "counterflow",
                             "message": "People are moving in conflicting directions: consider marking one-way lanes."})
        if free_cells and free_fraction is not None and free_fraction >= 0.2:
            tally: Dict[str, int] = {}
            for r, c in free_cells:
                k = region_name(r, c, self.rows, self.cols)
                tally[k] = tally.get(k, 0) + 1
            best = max(tally, key=tally.get)
            insights.append({"level": "info", "code": "open_space",
                             "message": f"Most open space is in the {best} of the view: "
                                        "a good place to direct new arrivals."})
        if aid_counts:
            shown = {k: v for k, v in aid_counts.items() if v > 0 and k != "stroller"}
            if shown:
                txt = ", ".join(f"{v} {k}" for k, v in shown.items())
                insights.append({"level": "info", "code": "mobility_aids",
                                 "message": f"Mobility aids visible: {txt}. Consider an accessible lane or priority help."})
        if children_est:
            insights.append({"level": "info", "code": "children",
                             "message": f"About {children_est} children in view (rough, size-based estimate)."})

        return {
            "event": dict(
                camera_mode=mode, people=people, people_is_lower_bound=lower_bound,
                density=DENSITY_LEVELS[lvl], crowd_fraction=round(crowd_fraction, 3),
                children_est=children_est, mobility_aids=aid_counts,
                avg_speed_bh_s=avg_speed, stationary_fraction=stationary_fraction,
                stagnation_index=stagnation_index, dominant_flow=flow, flow_coherence=coherence,
                counterflow=counterflow, free_space_fraction=free_fraction,
                grid_rows=self.rows, grid_cols=self.cols,
                crowd_grid=np.round(crowd_grid, 2).tolist(),
                stagnation_grid=stag_grid.tolist() if stag_grid is not None else None,
                free_cells=free_cells, hotspots=hotspots or [], insights=insights,
            ),
            "child_ids": child_ids,
        }
