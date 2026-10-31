"""Synthetic check of the metrics layer (no models, no footage needed).

Scene (640x480, fixed camera, 45 s at 8 fps):
  * 8 adults walking right along one lane
  * 5 adults standing still in a cluster (a queue) at the bottom-left
  * 2 children standing among them (65% of adult height)
Expected: ~15 people, 2 children, dominant flow 'right', stationary share ~ 7/15,
a bottleneck hotspot bottom-left, and some free space once walkable area is learned.
"""
import numpy as np
import supervision as sv

from reliefvision.config import load_config
from reliefvision.metrics import SceneAnalyzer

W, H, FPS, SECS = 640, 480, 8, 45


def adult_h(y2):                      # perspective: lower in frame = taller
    return 60 + 0.4 * (y2 - 150)


def box(cx, y2, scale=1.0):
    h = adult_h(y2) * scale
    return [cx - 0.2 * h, y2 - h, cx + 0.2 * h, y2]


def main():
    cfg = load_config()
    an = SceneAnalyzer(cfg)
    rng = np.random.default_rng(0)
    last = None
    for f in range(FPS * SECS):
        ts = f / FPS
        boxes, ids = [], []
        for k in range(8):            # walkers: loop across the frame at ~1 body-height/s
            y2 = 250 + 25 * k
            speed = adult_h(y2) * 1.0
            travelled = 40 + k * 70 + speed * ts
            cx = travelled % (W - 80) + 40
            wraps = int(travelled // (W - 80))      # leaving + re-entering = a new track ID, like a real tracker
            boxes.append(box(cx, y2)); ids.append(100 + k + 100 * wraps)
        for k in range(5):            # standing adults (tiny sway)
            boxes.append(box(80 + 45 * k + rng.normal(0, 0.4), 440 + rng.normal(0, 0.4))); ids.append(200 + k)
        for k in range(2):            # children
            boxes.append(box(120 + 50 * k + rng.normal(0, 0.4), 438, scale=0.62)); ids.append(300 + k)
        xyxy = np.array(boxes, float)
        d = sv.Detections(xyxy=xyxy, confidence=np.ones(len(xyxy)), class_id=np.zeros(len(xyxy), int),
                          tracker_id=np.array(ids))
        last = an.update(d, (H, W, 3), ts, "fixed", {"wheelchair": 1, "walker": 0, "crutches": 0, "cane": 0, "stroller": 0})
    ev = last["event"]
    for k in ("people", "people_is_lower_bound", "density", "crowd_fraction", "children_est",
              "avg_speed_bh_s", "stationary_fraction", "stagnation_index", "dominant_flow",
              "flow_coherence", "counterflow", "free_space_fraction"):
        print(f"{k:22s} {ev[k]}")
    print("hotspots              ", ev["hotspots"])
    for i in ev["insights"]:
        print(f"  [{i['level']}] {i['message']}")

    assert ev["people"] == 15, ev["people"]
    assert ev["children_est"] == 2, ev["children_est"]
    assert ev["dominant_flow"] == "right", ev["dominant_flow"]
    assert 0.35 <= ev["stationary_fraction"] <= 0.65, ev["stationary_fraction"]
    assert ev["free_space_fraction"] is not None
    assert any(h["region"].startswith("bottom") for h in ev["hotspots"]), ev["hotspots"]
    print("\nSELFTEST PASSED")


if __name__ == "__main__":
    main()
