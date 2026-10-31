"""Live overlay: crowd heat grid, boxes, mobility aids, stats panel, organizer insights."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

import cv2
import numpy as np

GREEN = (80, 200, 80)
CYAN = (255, 220, 0)
ORANGE = (0, 165, 255)


def _heat_color(v: float) -> Tuple[int, int, int]:
    v = float(np.clip(v, 0, 1))
    return (0, int(255 * (1 - v)), int(255 * min(1.0, v * 2)))  # green -> yellow -> red (BGR)


def draw(frame: np.ndarray, dets, ev: Dict[str, Any], child_ids: Set[int],
         aid_dets: Optional[List[tuple]] = None, show_grid: bool = True) -> np.ndarray:
    out = frame.copy()
    H, W = out.shape[:2]
    fs = max(0.45, W / 1280 * 0.6)
    th = max(1, int(round(fs * 2)))

    if show_grid:
        rows, cols = ev["grid_rows"], ev["grid_cols"]
        layer = out.copy()
        for r in range(rows):
            for c in range(cols):
                v = ev["crowd_grid"][r][c]
                p1, p2 = (int(c * W / cols), int(r * H / rows)), (int((c + 1) * W / cols), int((r + 1) * H / rows))
                if v > 0.05:
                    cv2.rectangle(layer, p1, p2, _heat_color(v), -1)
        out = cv2.addWeighted(layer, 0.28, out, 0.72, 0)
        for r, c in ev.get("free_cells") or []:
            p1, p2 = (int(c * W / cols) + 2, int(r * H / rows) + 2), (int((c + 1) * W / cols) - 2, int((r + 1) * H / rows) - 2)
            cv2.rectangle(out, p1, p2, (120, 255, 120), 1)

    ids = dets.tracker_id if len(dets) and dets.tracker_id is not None else [None] * len(dets)
    for box, tid in zip(dets.xyxy if len(dets) else [], ids):
        x1, y1, x2, y2 = map(int, box)
        child = tid is not None and int(tid) in child_ids
        col = CYAN if child else GREEN
        cv2.rectangle(out, (x1, y1), (x2, y2), col, 2)
        label = ("child? " if child else "") + (f"#{int(tid)}" if tid is not None else "")
        if label:
            cv2.putText(out, label, (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, fs * 0.7, col, th)

    for lab, box, conf in aid_dets or []:
        x1, y1, x2, y2 = map(int, box)
        cv2.rectangle(out, (x1, y1), (x2, y2), ORANGE, 2)
        cv2.putText(out, f"{lab} {conf:.2f}", (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, fs * 0.7, ORANGE, th)

    # stats panel
    aids = ev.get("mobility_aids")
    aid_txt = "off" if aids is None else (", ".join(f"{v} {k}" for k, v in aids.items() if v) or "none")
    fmt = lambda x, f="{}": "-" if x is None else f.format(x)
    lines = [
        f"People: {'>=' if ev['people_is_lower_bound'] else ''}{ev['people']}   Density: {ev['density'].upper()}",
        f"Children (est): {fmt(ev['children_est'])}   Aids: {aid_txt}",
        f"Camera: {ev['camera_mode']}   Flow: {fmt(ev['dominant_flow'])}",
        f"Speed: {fmt(ev['avg_speed_bh_s'])} bh/s   Still: {fmt(None if ev['stationary_fraction'] is None else int(ev['stationary_fraction'] * 100), '{}%')}",
        f"Stagnation: {fmt(ev['stagnation_index'])}   Free space: {fmt(None if ev['free_space_fraction'] is None else int(ev['free_space_fraction'] * 100), '{}%')}",
    ]
    lh = int(26 * fs / 0.6 * 0.75) + 6
    pw = int(max(cv2.getTextSize(s, cv2.FONT_HERSHEY_SIMPLEX, fs, th)[0][0] for s in lines)) + 16
    panel = out.copy()
    cv2.rectangle(panel, (6, 6), (6 + pw, 6 + lh * len(lines) + 8), (20, 20, 20), -1)
    out = cv2.addWeighted(panel, 0.65, out, 0.35, 0)
    for i, s in enumerate(lines):
        cv2.putText(out, s, (14, 6 + lh * (i + 1)), cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), th)

    # insights along the bottom
    ins = ev.get("insights", [])[:3]
    for i, it in enumerate(reversed(ins)):
        y = H - 10 - i * lh
        col = (80, 80, 255) if it["level"] == "warn" else (230, 230, 230)
        txt = it["message"]
        (tw, _), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, fs * 0.9, th)
        cv2.rectangle(out, (6, y - lh + 8), (14 + tw, y + 6), (20, 20, 20), -1)
        cv2.putText(out, txt, (10, y), cv2.FONT_HERSHEY_SIMPLEX, fs * 0.9, col, th)
    return out
