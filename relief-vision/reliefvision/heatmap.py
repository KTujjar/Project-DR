"""Dwell-time heat maps: where people spent time, in the camera view and on a top-down floor map.

Same idea as kerberos-io/heatmap: detect people, convert positions with a homography onto a flat
top-down plane, accumulate, and draw the result on an image of the space.

    # 1) camera-view heat map only (no setup)
    python -m reliefvision.heatmap --source clip.mov --out heatmap/

    # 2) one-time floor calibration: click 4 corners of a rectangle on the floor
    #    in this order: far-left, far-right, near-right, near-left; give its real size in metres
    python -m reliefvision.heatmap --source clip.mov --calibrate calib.json --plane-size 6x4
    #    (optional) --floorplan plan.png  = image of that same rectangle, drawn as the map background
    #    (headless)  --points "120,300;700,300;780,600;40,600"  instead of clicking

    # 3) camera view + top-down floor map + CSV/JSON
    python -m reliefvision.heatmap --source clip.mov --calib calib.json --out heatmap/

Positions use each person's FOOT point (bottom centre of the box), because the floor is the plane
the homography maps. Outputs hold positions and dwell time only: no IDs, no faces, no frames.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import deque
from typing import List, Optional, Tuple

import cv2
import numpy as np

from .config import load_config
from .detector import YoloPersonDetector
from .sources import open_source


# ------------------------------------------------------------------ calibration
def parse_size(s: str) -> Tuple[float, float]:
    w, h = s.lower().replace(" ", "").split("x")
    return float(w), float(h)


def plane_pixels(size_m: Tuple[float, float], long_side: int) -> Tuple[int, int]:
    w, h = size_m
    if w >= h:
        pw, ph = long_side, max(1, int(round(long_side * h / w)))
    else:
        pw, ph = max(1, int(round(long_side * w / h))), long_side
    return pw + pw % 2, ph + ph % 2            # even sizes: video encoders drop frames otherwise


def calibrate_gui(frame: np.ndarray) -> Optional[List[Tuple[float, float]]]:
    """Click 4 floor corners: far-left, far-right, near-right, near-left. Returns image-pixel points."""
    h0, w0 = frame.shape[:2]
    s = min(1.0, 1200 / w0, 800 / h0)
    disp = cv2.resize(frame, None, fx=s, fy=s) if s < 1 else frame.copy()
    names = ["far-left", "far-right", "near-right", "near-left"]
    pts: List[Tuple[int, int]] = []

    def on_mouse(ev, x, y, flags, param):
        if ev == cv2.EVENT_LBUTTONDOWN and len(pts) < 4:
            pts.append((x, y))

    win = "calibrate floor"
    cv2.namedWindow(win)
    cv2.setMouseCallback(win, on_mouse)
    result = None
    while True:
        img = disp.copy()
        for i, p in enumerate(pts):
            cv2.circle(img, p, 5, (0, 0, 255), -1)
            cv2.putText(img, names[i], (p[0] + 8, p[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        if len(pts) > 1:
            cv2.polylines(img, [np.array(pts, np.int32)], len(pts) == 4, (0, 255, 255), 2)
        msg = (f"Click floor corner {len(pts) + 1}/4: {names[len(pts)]}" if len(pts) < 4
               else "Enter = save   r = reset   q = cancel")
        cv2.rectangle(img, (0, 0), (img.shape[1], 30), (20, 20, 20), -1)
        cv2.putText(img, msg, (10, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.imshow(win, img)
        k = cv2.waitKey(30) & 0xFF
        if k in (ord("q"), 27):
            break
        if k == ord("r"):
            pts.clear()
        if k in (13, 10, 32) and len(pts) == 4:
            result = [(x / s, y / s) for x, y in pts]
            break
    cv2.destroyWindow(win)
    cv2.waitKey(1)
    return result


def save_calibration(path: str, image_pts, size_m, plane_px, frame_size, floorplan: Optional[str]) -> None:
    with open(path, "w") as f:
        json.dump({
            "image_points": [[float(x), float(y)] for x, y in image_pts],
            "plane_size_m": list(size_m), "plane_px": list(plane_px),
            "frame_size": list(frame_size),
            "floorplan": os.path.abspath(floorplan) if floorplan else None,
        }, f, indent=2)


def homography(calib: dict) -> np.ndarray:
    w, h = calib["plane_px"]
    dst = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    return cv2.getPerspectiveTransform(np.float32(calib["image_points"]), dst)


# ------------------------------------------------------------------ accumulate + render
class HeatAccumulator:
    def __init__(self, size_wh: Tuple[int, int]):
        self.w, self.h = size_wh
        self.heat = np.zeros((self.h, self.w), np.float32)

    def add(self, pts: np.ndarray, weight: float) -> None:
        for x, y in pts:
            xi, yi = int(x), int(y)
            if 0 <= xi < self.w and 0 <= yi < self.h:
                self.heat[yi, xi] += weight


def splat(heat: np.ndarray, pts: np.ndarray, weight: float) -> None:
    h, w = heat.shape
    for x, y in pts:
        xi, yi = int(x), int(y)
        if 0 <= xi < w and 0 <= yi < h:
            heat[yi, xi] += weight


def _blur(heat: np.ndarray) -> np.ndarray:
    return cv2.GaussianBlur(heat, (0, 0), sigmaX=max(2.0, 0.018 * max(heat.shape)))


def _ref(h: np.ndarray) -> float:
    """Heat level that maps to 'red' (99th percentile of the meaningful pixels)."""
    mx = float(h.max())
    if mx <= 0:
        return 0.0
    sig = h > 0.02 * mx
    return float(np.percentile(h[sig], 99)) if sig.any() else mx


def render(heat: np.ndarray, bg: np.ndarray, alpha: float = 0.65, ref: Optional[float] = None) -> np.ndarray:
    h = _blur(heat)
    if float(h.max()) <= 0:
        return bg.copy()
    ref = _ref(h) if ref is None else ref
    v = np.clip(h / max(ref, 1e-9), 0, 1)
    color = cv2.applyColorMap((v * 255).astype(np.uint8), cv2.COLORMAP_JET)
    a = (np.clip(v * 1.4, 0, 1) ** 0.8 * alpha)[..., None]       # low values fade out: scene stays visible
    return (bg.astype(np.float32) * (1 - a) + color.astype(np.float32) * a).astype(np.uint8)


def annotate(img: np.ndarray, title: str, person_seconds: Optional[float] = None) -> np.ndarray:
    out = img.copy()
    H, W = out.shape[:2]
    fs = max(0.45, W / 1280 * 0.6)
    th = max(1, int(round(fs * 2)))
    text = title if person_seconds is None else f"{title}  |  {person_seconds:.0f} person-seconds observed"
    (tw, tht), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, fs, th)
    cv2.rectangle(out, (6, 6), (18 + tw, 14 + tht + 6), (20, 20, 20), -1)
    cv2.putText(out, text, (12, 10 + tht), cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), th)
    return draw_legend(out)


def draw_legend(out: np.ndarray) -> np.ndarray:
    """Small 'less time -> more time' colour bar, bottom-right, on a dark backing (legible on any image)."""
    H, W = out.shape[:2]
    fs = max(0.45, W / 1280 * 0.6)
    bw, bh = max(120, int(W * 0.25)), 12
    x0, y0 = W - bw - 14, H - bh - 26
    bar = cv2.applyColorMap(np.tile(np.linspace(0, 255, bw, dtype=np.uint8), (bh, 1)), cv2.COLORMAP_JET)
    cv2.rectangle(out, (x0 - 6, y0 - 6), (x0 + bw + 6, y0 + bh + 22), (20, 20, 20), -1)
    out[y0:y0 + bh, x0:x0 + bw] = bar
    cv2.putText(out, "less time", (x0, y0 + bh + 15), cv2.FONT_HERSHEY_SIMPLEX, fs * 0.6, (255, 255, 255), 1)
    (hw, _), _ = cv2.getTextSize("more time", cv2.FONT_HERSHEY_SIMPLEX, fs * 0.6, 1)
    cv2.putText(out, "more time", (x0 + bw - hw, y0 + bh + 15), cv2.FONT_HERSHEY_SIMPLEX, fs * 0.6, (255, 255, 255), 1)
    return out


class LiveHeat:
    """Running heat layer for the live view.

    mode 'recent'     : old heat fades with the given half-life (seconds): "where are people now"
    mode 'cumulative' : heat only builds up: "where have people spent time since the start"

    follow=False (default): heat lives in image pixels, so it is only valid for a steady camera
        (the caller resets it when the view moves).
    follow=True : heat lives on a scene-fixed canvas 3x3 screens large. Each frame the camera's
        background motion (a homography) places the new foot positions on that canvas, and the canvas
        is warped back into the current view, so the heat stays pinned to the floor while the camera
        pans, tilts or walks. Exact for pure rotation or a flat floor; approximate otherwise, drifts
        slowly, and heat further than ~1 screen from the starting view is dropped.

    Works at reduced resolution (cheap). The colour scale adapts smoothly, since a live stream has no
    'final' level to normalise against.
    """

    def __init__(self, mode: str = "recent", half_life: float = 10.0, max_w: int = 480,
                 alpha: float = 0.6, follow: bool = False):
        self.mode, self.half_life, self.max_w, self.alpha, self.follow = mode, half_life, max_w, alpha, follow
        self.reset()

    def reset(self) -> None:
        self.heat: Optional[np.ndarray] = None
        self.shape: Optional[Tuple[int, int]] = None
        self.prev_ts: Optional[float] = None
        self.ref = 0.0
        self.scale = 1.0
        self.view_hw = (0, 0)
        self.Wm = np.eye(3)            # current frame pixels -> scene (first-frame) pixels

    def _canvas_matrix(self) -> np.ndarray:
        hs, ws = self.view_hw
        s = self.scale
        return np.array([[1, 0, ws], [0, 1, hs], [0, 0, 1.0]]) @ np.diag([s, s, 1.0]) @ self.Wm

    def update(self, feet: np.ndarray, ts: float, shape, motion: Optional[np.ndarray] = None) -> None:
        """motion: homography mapping this frame's pixels onto the previous frame's (None = no camera motion)."""
        H, W = shape[:2]
        if self.heat is None or self.shape != (H, W):
            self.scale = min(1.0, self.max_w / W)
            hs, ws = max(1, int(H * self.scale)), max(1, int(W * self.scale))
            self.view_hw = (hs, ws)
            self.heat = np.zeros((3 * hs, 3 * ws) if self.follow else (hs, ws), np.float32)
            self.shape, self.prev_ts, self.ref, self.Wm = (H, W), None, 0.0, np.eye(3)
        dt = 0.125 if self.prev_ts is None or ts <= self.prev_ts else min(ts - self.prev_ts, 1.0)
        self.prev_ts = ts
        if self.mode == "recent":
            self.heat *= 0.5 ** (dt / max(self.half_life, 0.1))
        if self.follow and motion is not None:
            Wn = self.Wm @ motion
            if np.isfinite(Wn).all() and abs(np.linalg.det(Wn[:2, :2])) > 1e-3:
                self.Wm = Wn / Wn[2, 2]
        if len(feet):
            f = np.asarray(feet, np.float32)
            if self.follow:
                q = cv2.perspectiveTransform(f.reshape(-1, 1, 2), self._canvas_matrix().astype(np.float32)).reshape(-1, 2)
            else:
                q = f * self.scale
            splat(self.heat, q, dt)

    def apply(self, frame: np.ndarray) -> np.ndarray:
        if self.heat is None:
            return frame
        hs, ws = self.view_hw
        if self.follow:
            try:
                A = np.diag([self.scale, self.scale, 1.0]) @ np.linalg.inv(self._canvas_matrix())
            except np.linalg.LinAlgError:
                return frame
            view = cv2.warpPerspective(self.heat, A, (ws, hs), flags=cv2.INTER_LINEAR)
        else:
            view = self.heat
        h = _blur(view)
        if float(h.max()) <= 0:
            return frame
        cur = _ref(h)
        self.ref = cur if self.ref <= 0 else max(cur, 0.98 * self.ref + 0.02 * cur)   # rises fast, falls slowly
        v = np.clip(h / max(self.ref, 1e-9), 0, 1)
        color = cv2.applyColorMap((v * 255).astype(np.uint8), cv2.COLORMAP_JET)
        a = np.clip(v * 1.4, 0, 1) ** 0.8 * self.alpha
        H, W = frame.shape[:2]
        if (W, H) != (h.shape[1], h.shape[0]):
            color = cv2.resize(color, (W, H))
            a = cv2.resize(a, (W, H))
        a = a[..., None]
        out = (frame.astype(np.float32) * (1 - a) + color.astype(np.float32) * a).astype(np.uint8)
        return draw_legend(out)


def topdown_background(calib: dict) -> np.ndarray:
    w, h = calib["plane_px"]
    fp = calib.get("floorplan")
    if fp and os.path.exists(fp):
        img = cv2.imread(fp)
        if img is not None:
            return cv2.resize(img, (w, h))
    bg = np.full((h, w, 3), 238, np.uint8)
    wm, hm = calib["plane_size_m"]
    for i in range(1, int(wm) + 1):                      # 1 m grid
        x = int(i * (w - 1) / wm)
        cv2.line(bg, (x, 0), (x, h - 1), (210, 210, 210), 1)
    for j in range(1, int(hm) + 1):
        y = int(j * (h - 1) / hm)
        cv2.line(bg, (0, y), (w - 1, y), (210, 210, 210), 1)
    cv2.rectangle(bg, (0, 0), (w - 1, h - 1), (120, 120, 120), 2)
    cv2.putText(bg, f"{wm:g} m x {hm:g} m (1 m grid)", (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (90, 90, 90), 1)
    return bg


def coarse_grid(heat: np.ndarray, rows: int, cols: int) -> List[List[float]]:
    """Sum of dwell seconds per cell (rows x cols)."""
    mean = cv2.resize(heat, (cols, rows), interpolation=cv2.INTER_AREA)
    total = mean * (heat.shape[0] * heat.shape[1] / float(rows * cols))
    return np.round(total, 2).tolist()


# ------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="reliefvision-heatmap", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True, help="video file / webcam index / rtsp url")
    ap.add_argument("--out", default="heatmap", help="output folder")
    ap.add_argument("--calibrate", metavar="FILE", help="create a floor calibration file, then exit")
    ap.add_argument("--plane-size", default=None, help="real size of the calibrated floor rectangle in metres, e.g. 6x4")
    ap.add_argument("--plane-px", type=int, default=900, help="long side of the top-down image in pixels")
    ap.add_argument("--floorplan", help="optional image of the calibrated rectangle, used as map background")
    ap.add_argument("--points", help='headless calibration: "x,y;x,y;x,y;x,y" far-left;far-right;near-right;near-left')
    ap.add_argument("--calib", metavar="FILE", help="use a saved calibration to also make the top-down map")
    ap.add_argument("--config", help="YAML config (model, device)")
    ap.add_argument("--conf", type=float, help="person detection confidence")
    ap.add_argument("--video", action="store_true",
                    help="also write an animated heat map video (video files only, not live sources)")
    ap.add_argument("--video-mode", choices=["cumulative", "recent"], default="cumulative",
                    help="cumulative = heat builds up over the whole clip; recent = only the last few seconds, fading")
    ap.add_argument("--half-life", type=float, default=10.0, help="seconds for 'recent' heat to fade by half")
    ap.add_argument("--process-fps", type=float)
    ap.add_argument("--max-frames", type=int)
    ap.add_argument("--device")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    fps = args.process_fps or cfg["process_fps"]
    src = open_source(args.source, fps)

    # ---- calibration mode
    if args.calibrate:
        if not args.plane_size:
            print("--plane-size WxH (metres) is required with --calibrate, e.g. --plane-size 6x4", file=sys.stderr)
            return 2
        frame = next(iter(src.frames()), (None, None))[0]
        src.close()
        if frame is None:
            print("Could not read a frame from the source.", file=sys.stderr)
            return 1
        if args.points:
            pts = [tuple(float(v) for v in p.split(",")) for p in args.points.split(";")]
            if len(pts) != 4:
                print("--points needs exactly 4 x,y pairs", file=sys.stderr)
                return 2
        else:
            pts = calibrate_gui(frame)
            if pts is None:
                print("Calibration cancelled.")
                return 1
        size = parse_size(args.plane_size)
        save_calibration(args.calibrate, pts, size, plane_pixels(size, args.plane_px),
                         (frame.shape[1], frame.shape[0]), args.floorplan)
        print(f"Saved calibration to {args.calibrate}. Now run with --calib {args.calibrate}")
        return 0

    calib = None
    Hm = None
    if args.calib:
        with open(args.calib) as f:
            calib = json.load(f)
        calib["plane_px"] = [int(v) + int(v) % 2 for v in calib["plane_px"]]   # even (older calib files)
        Hm = homography(calib)

    det = YoloPersonDetector(cfg["person"]["weights"], args.conf or cfg["person"]["conf"],
                             cfg["person"]["imgsz"], args.device or cfg["device"])
    cam_acc: Optional[HeatAccumulator] = None
    plane_acc = HeatAccumulator(tuple(calib["plane_px"])) if calib else None
    bg_frames: deque = deque(maxlen=25)
    rows = []
    cache_cam: list = []
    cache_plane: list = []
    cache_dt: list = []
    live = bool(getattr(src, "is_live", False))
    prev_ts = None
    n = 0
    scale = 1.0
    cam_size = (0, 0)
    for frame, ts in src.frames():
        h0, w0 = frame.shape[:2]
        if cam_acc is None:
            scale = min(1.0, 960 / w0)
            cam_size = (int(w0 * scale) // 2 * 2, int(h0 * scale) // 2 * 2)
            cam_acc = HeatAccumulator(cam_size)
            if calib and tuple(calib["frame_size"]) != (w0, h0):
                print(f"Warning: video is {w0}x{h0} but calibration was made on "
                      f"{calib['frame_size'][0]}x{calib['frame_size'][1]}; the map may be wrong.")
        dt = 1.0 / fps if prev_ts is None or ts <= prev_ts else min(ts - prev_ts, 1.0)
        prev_ts = ts
        d = det.detect(frame)
        feet = (np.c_[(d.xyxy[:, 0] + d.xyxy[:, 2]) / 2, d.xyxy[:, 3]].astype(np.float32)
                if len(d) else np.zeros((0, 2), np.float32))
        feet[:, 0] = np.clip(feet[:, 0], 0, w0 - 1)
        feet[:, 1] = np.clip(feet[:, 1], 0, h0 - 1)
        cam_acc.add(feet * scale, dt)
        plane_pts = np.zeros((0, 2), np.float32)
        if Hm is not None and len(feet):
            plane_pts = cv2.perspectiveTransform(feet.reshape(-1, 1, 2), Hm).reshape(-1, 2)
            plane_acc.add(plane_pts, dt)
        cache_cam.append(feet * scale)       # kept so the video pass needs no second detection run
        cache_plane.append(plane_pts)
        cache_dt.append(dt)
        for k in range(len(feet)):
            row = [round(float(ts), 2), round(float(feet[k, 0]), 1), round(float(feet[k, 1]), 1)]
            if Hm is not None:
                px, py = plane_pts[k]
                wm, hm = calib["plane_size_m"]
                pw, ph = calib["plane_px"]
                inside = 0 <= px < pw and 0 <= py < ph
                row += [round(float(px) * wm / pw, 2), round(float(py) * hm / ph, 2)] if inside else ["", ""]
            rows.append(row)
        if n % 10 == 0:
            bg_frames.append(cv2.resize(frame, cam_size))
        n += 1
        if n % 50 == 0:
            print(f"[heatmap] {n} frames processed...")
        if args.max_frames and n >= args.max_frames:
            break
    src.close()
    if cam_acc is None or not bg_frames:
        print("No frames were processed.", file=sys.stderr)
        return 1

    os.makedirs(args.out, exist_ok=True)
    bg = np.median(np.stack(list(bg_frames)), axis=0).astype(np.uint8)   # median removes moving people

    cam_img = render(cam_acc.heat, bg)
    if calib:
        quad = (np.array(calib["image_points"]) * scale).astype(np.int32)
        cv2.polylines(cam_img, [quad], True, (255, 255, 255), 2)
    cam_img = annotate(cam_img, "Camera view", float(cam_acc.heat.sum()))
    cv2.imwrite(os.path.join(args.out, "heatmap_camera.png"), cam_img)
    outputs = ["heatmap_camera.png"]

    grids = {"units": "person-seconds",
             "camera": {"rows": 18, "cols": 24, "grid": coarse_grid(cam_acc.heat, 18, 24)}}
    header = ["t_seconds", "img_x", "img_y"]
    if calib:
        top = render(plane_acc.heat, topdown_background(calib))
        top = annotate(top, "Top-down floor map", float(plane_acc.heat.sum()))
        cv2.imwrite(os.path.join(args.out, "heatmap_topdown.png"), top)
        outputs.append("heatmap_topdown.png")
        pw, ph = calib["plane_px"]
        rr, cc = (12, 16) if pw >= ph else (16, 12)
        grids["topdown"] = {"rows": rr, "cols": cc, "plane_size_m": calib["plane_size_m"],
                            "grid": coarse_grid(plane_acc.heat, rr, cc)}
        header += ["floor_x_m", "floor_y_m"]

    with open(os.path.join(args.out, "heatmap_grid.json"), "w") as f:
        json.dump(grids, f)
    with open(os.path.join(args.out, "heatmap_points.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(header)
        wr.writerows(rows)
    outputs += ["heatmap_grid.json", "heatmap_points.csv"]
    if args.video:
        if live:
            print("[heatmap] --video needs a video file (not a live source); skipped.")
        else:
            print("[heatmap] writing heat map video...")
            outputs += write_heat_videos(args, fps, cam_size, cache_cam, cache_plane, cache_dt,
                                         calib, scale, args.out)
    print(f"[heatmap] {n} frames, {len(rows)} positions. Wrote to {args.out}/: " + ", ".join(outputs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
