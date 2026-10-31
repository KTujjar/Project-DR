# reliefvision

Video module for disaster-relief coordination. Turns camera video (file, webcam, phone/RTSP, TurtleBot via ROS 2) into **aggregate** crowd statistics and sends them as small JSON events to your platform.

**Privacy by design:** no face recognition, no identities, no stored frames. Only counts and grid statistics leave the module (track IDs are used internally to measure movement and are never emitted).

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .            # installs ultralytics, supervision, trackers, opencv, pydantic...
python selftest.py          # metrics check on synthetic data, no models/footage needed

reliefvision --source crowd.mp4                  # file
reliefvision --source 0                          # laptop webcam
reliefvision --source rtsp://PHONE_IP:8554/live  # phone camera app
reliefvision --source a.mp4 --source b.mp4       # several cameras (cam1, cam2, ...)
reliefvision --source "ros2:/camera/image_raw/compressed?odom=/odom"   # TurtleBot (see below)
```

Useful flags: `--webhook URL`, `--no-display`, `--save-video DIR`, `--no-aids`, `--device cuda:0`, `--config config.yaml`.
First run downloads `yolo11n.pt` (~5 MB).

## What it measures

| Your priority | Event fields | How |
|---|---|---|
| Number of people | `people`, `people_is_lower_bound`, `density`, `crowd_fraction` | YOLO11 person detection + ByteTrack, median-smoothed. Heavy box overlap => "at least N" and density bumped up one level |
| Children (rough) | `children_est` | People much shorter than adults at the same image depth (robust fit of height vs. row, assumes most people are adults). Needs ~30 samples before it reports |
| Needs more help | `mobility_aids` {wheelchair, walker, crutches, cane, stroller} | YOLO-World open-vocabulary detector every 1.5 s, median over recent runs |
| How people move | `avg_speed_bh_s`, `stationary_fraction`, `dominant_flow`, `flow_coherence`, `counterflow` | Speed in **body-heights/second** (no calibration; walking ~ 1) |
| Where it's crowded | `crowd_grid`, `stagnation_grid`, `hotspots`, `stagnation_index` | 6x8 grid of ground positions; hotspot = crowded AND barely moving |
| Where there's room | `free_cells`, `free_space_fraction` | Cells people have been seen using that are empty now (learned over `free_space_learn_s`) |
| Plain-language notes | `insights[]` | Rule-based, e.g. "Most open space is in the bottom-right: direct new arrivals there" |

Everything is camera-relative ("bottom-left of the view"). Add a `pose` label per camera in the config to tell the platform which physical area it is.

## Fixed vs. mobile cameras (TurtleBot, handheld)

`camera_mode` is detected automatically (optical flow on the background, plus robot odometry if `?odom=/odom` is given). While the camera moves, only snapshot stats are produced (count, density, children, aids); flow, stagnation and free-space are `null` and spatial memory resets. Park the robot (or use a tripod phone) and the full metrics return after ~3 s. Force it with `mode: fixed|mobile` in the config.

## Event schema

`reliefvision/schema.py` (`Event`, `SCHEMA_VERSION = "0.1"`) is the contract with your platform. `mock_receiver.py` validates incoming events and serves them back:

```bash
pip install -e ".[server]"
uvicorn mock_receiver:app --port 8000     # GET /latest, /events, /schema
reliefvision --source crowd.mp4 --webhook http://localhost:8000/events
```

If the network drops, events queue in a local SQLite outbox (`outbox.sqlite`, max 5000) and are delivered oldest-first when it returns. A JSONL copy is always written to `events.jsonl`.

## Tuning (per camera!)

- **Density thresholds** (`metrics.density_thresholds`) are fractions of the frame covered by people, so they depend on camera distance. A close-up of 4 people reads "high". Adjust once per camera setup.
- **`grid.cell_capacity`**: how many people make one grid cell "full".
- **Small / far people**: use `person.weights: yolo11s.pt` and `imgsz: 960` (slower).
- **`process_fps`**: 5-10 is plenty; lower it to fit more cameras on one machine.

## Known limits (say these in your pitch)

- **Children** is a size heuristic: it can miss kids who are seated, cropped by the frame edge, or hidden, and can flag short adults. Reported only as a rough aggregate. **Elderly people cannot be identified reliably from video**, so mobility aids are the proxy; they are never attributed to individuals.
- **Mobility aids** (open-vocabulary) are the noisiest signal. Wheelchairs are usually found; canes and crutches often are not. Counts are "currently visible".
- **Dense crowds**: detection undercounts when bodies overlap; the output says "at least N" rather than pretending. A low camera angle makes this worse (a small mast on the robot helps).
- **Flow/free-space** need a steady camera and a few seconds to a minute of observation.

## What was verified (and not)

Verified in a sandbox: metrics on synthetic scenes (`selftest.py`: counts, children, flow direction, stationary share, hotspot, free space), full pipeline on a real image (detection + tracking + events + overlay), schema validation, webhook delivery and the offline outbox. **Not verified:** the wheelchair/walker detector end to end (its CLIP weights couldn't be downloaded in the sandbox; the counting logic was tested with a fake model, and it disables itself gracefully if it can't load), the ROS 2 adapter (no ROS here), and behaviour on real crowd video. Run it on your own footage before trusting any number.

## Licensing / supply chain

- Ultralytics YOLO is **AGPL-3.0**: fine for a hackathon; for a hosted platform, swap `YoloPersonDetector` (one class in `detector.py`) for RF-DETR/YOLOX or buy a license.
- `supervision` (MIT) and `trackers` (Apache-2.0, ByteTrack) are from Roboflow. Pin versions (`pip freeze > requirements.lock`) once you have a working install.

## Layout

```
reliefvision/  sources.py (file/webcam/RTSP/ROS2) · detector.py · camera_motion.py · metrics.py
               overlay.py · events.py · pipeline.py · schema.py · config.py · cli.py
selftest.py · mock_receiver.py · config.yaml
```
