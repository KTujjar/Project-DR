# reliefvision

Video module for disaster-relief coordination. Turns camera video (file, webcam, phone/RTSP stream, TurtleBot via ROS 2) into **aggregate** crowd statistics and heat maps, and sends the statistics to your platform as small JSON events.

**Privacy by design:** no face recognition, no identities, no stored frames. Only counts, grid statistics and anonymous positions leave the module. Track IDs are used internally to measure movement and are never emitted. The one exception is opt-in: `--serve-video` streams the annotated video to the coordinator dashboard (see [Dashboard API](#dashboard-api---serve)).

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .                                      # ultralytics, supervision, trackers, opencv, pydantic...
python selftest.py                                    # metrics check on synthetic data: should print SELFTEST PASSED

reliefvision --source clip.mov --no-aids              # video file
reliefvision --source 0 --no-aids                     # laptop webcam (macOS: allow camera access for Terminal)
reliefvision --source rtsp://PHONE_IP:8554/live       # phone camera app / IP camera
reliefvision --source a.mp4 --source b.mp4            # several cameras (cam1, cam2, ...)
reliefvision --source "ros2:/camera/image_raw/compressed?odom=/odom"   # TurtleBot (see below)
```

Press `q` in the video window to quit. The first run downloads `yolo11n.pt` (about 5 MB).

### Command-line options

| Option | What it does |
|---|---|
| `--source X` | Video file, webcam index, RTSP/HTTP URL or `ros2:` topic. Repeat for several cameras |
| `--no-aids` | Skip the wheelchair/walker detector (needs an extra model download; see Known limits) |
| `--save-video DIR` | Save the annotated video as `DIR/cam1.mp4` (contains footage of people: keep it private) |
| `--no-display` | Don't open a window (headless / server) |
| `--heat [recent\|cumulative]` | Live heat layer (see Heat maps). Default style is `recent` |
| `--heat-half-life N` | Seconds for `recent` heat to fade by half (default 10) |
| `--follow-camera` | Keep the heat pinned to the scene while the camera moves |
| `--grid` | Shade crowded grid squares on the video (off by default) |
| `--mode auto\|fixed\|mobile` | Force the camera mode (default: detected automatically) |
| `--webhook URL` | POST events to your platform (buffered offline) |
| `--events FILE` | Event log path (default `events.jsonl`, **appended to on every run**) |
| `--max-frames N` | Stop after N processed frames |
| `--device cpu\|cuda:0\|mps` | Where to run the models |
| `--config config.yaml` | Use a config file (anything omitted falls back to defaults) |
| `--serve [PORT]` | Serve the coordinator-dashboard API (default port 8001); see Dashboard API |
| `--serve-video` | With `--serve`: also stream the annotated video, including any `--heat` / `--grid` layer (contains footage of people) |
| `--public-url URL` | With `--serve`: base URL browsers use for video links (default `http://localhost:8001`) |
| `--cors-origin URL` | With `--serve`: browser origin allowed to call the API (repeatable; default the Vite dev server) |

With no heat or grid options, the video shows just green person boxes, a stats panel, and a warning strip at the bottom. Cyan boxes marked "child?" are possible children; orange boxes are mobility aids.

## What it measures

| Topic | Event fields | How |
|---|---|---|
| Number of people | `people`, `people_is_lower_bound`, `density`, `crowd_fraction` | YOLO11 person detection + ByteTrack, median-smoothed. Heavy box overlap gives "at least N" and bumps density up one level |
| Children (rough) | `children_est` | People much shorter than adults at the same image depth (robust fit of height vs. position; assumes most people are adults). Needs about 30 samples before it reports |
| Who may need more help | `mobility_aids` {wheelchair, walker, crutches, cane, stroller} | YOLO-World open-vocabulary detector every 1.5 s, median over recent runs. Counts are "currently visible" |
| How people move | `avg_speed_bh_s`, `stationary_fraction`, `dominant_flow`, `flow_coherence`, `counterflow` | Speed in **body-heights per second** (no calibration needed; walking is about 1) |
| Where it's crowded | `crowd_grid`, `stagnation_grid`, `hotspots`, `stagnation_index` | 6x8 grid of ground positions. A hotspot is a cell that is crowded AND barely moving |
| Where there's room | `free_cells`, `free_space_fraction` | Cells people have been seen using that are empty now (learned over `free_space_learn_s`, default 20 s) |
| Plain-language notes | `insights[]` | Rule-based, e.g. "Most open space is in the bottom-right of the view: a good place to direct new arrivals" |

Everything is camera-relative ("bottom-left of the view"). Add a `pose` label per camera in the config to tell the platform which physical area it covers.

### Reading the events

Each line of `events.jsonl` is one event, written every 2 seconds of video.

```bash
tail -n 1 events.jsonl | python3 -m json.tool        # the latest event, formatted

python3 -c "
import json
for l in open('events.jsonl'):
    e = json.loads(l)
    print(e['video_ts'], '| people', e['people'], e['density'], '| children', e['children_est'],
          '| flow', e['dominant_flow'], '| still', e['stationary_fraction'],
          '| hotspots', [h['region'] for h in e['hotspots']], '| free space', e['free_space_fraction'])
    for i in e['insights']: print('    -', i['message'])
"
```

Some fields are `null` at the start: speed and flow need about 1 s of tracking, children need about 30 height samples, free space needs 20 s of steady video. Delete `events.jsonl` (or use `--events run1.jsonl`) before a fresh test, because new runs append.

## Fixed vs. mobile cameras (TurtleBot, handheld)

`camera_mode` is detected automatically (background optical flow, plus robot odometry if `?odom=/odom` is given). While the camera moves, only snapshot statistics are produced (count, density, children, aids); flow, stagnation and free space are `null` and spatial memory resets. Park the robot (or use a tripod phone) and the full metrics return after about 3 s. Force a mode with `--mode fixed|mobile` or `mode:` in the config. A "stop and scan" robot routine (drive, park for 20-30 s, repeat) works well with this.

## TurtleBot3 camera (rescue-bot Mission Control)

The Project-DR TurtleBot3 Burger (`rescue-bot` branch) doesn't publish its camera as a ROS topic: the Pi encodes JPEGs and its **Mission Control** app serves them behind a private SSH tunnel at `http://127.0.0.1:8872`. reliefvision reads them through Mission Control's teammate model API v1.0 (see `models/README.md` on `rescue-bot`), so the robot works like any other camera: events, heat, dashboard tile, crowd metrics and pass counting.

**Quickest way:** on the Mac connected to the robot, run `./start-with-robot.sh /path/to/rescue-bot-folder` from a separate `main` checkout. It uses `config.robot.yaml` and starts reliefvision and the dashboard together; see the repository root `README.md`. The manual setup is below.

```yaml
cameras:
  - id: cam_robot
    site_id: shelter_3                                   # which dashboard site the robot is counting
    source: "turtlebot:http://127.0.0.1:8872"
    token_file: /path/to/rescue-bot/.robot/runtime/service.token
    mode: auto
    # poll_fps: 5               # how often to ask for a new frame (default 5; lower it if the Pi is busy)
    # report_detections: true   # show reliefvision's person boxes on the robot operator's video
```

1. On the Mac connected to the robot, start the mission from the `rescue-bot` checkout: `./scripts/start.sh`.
2. Run reliefvision **on that same Mac**: `reliefvision --config config.yaml --serve --serve-video --heat --follow-camera`. To run it on another machine, open your own authorized SSH tunnel to the Pi and copy the token securely; use that tunnel's URL in `source`.
3. In the dashboard, click the robot's camera tile. Use **Start pass** / **End pass** in its metrics panel as the robot drives along a line of people.

- **Robot motion** comes from the robot's odometry, so `camera_mode` switches to `mobile` while it drives. Use `--follow-camera` to keep heat while it moves.
- **People boxes** go back to Mission Control as `model_id: reliefvision-people` observations. They show on the robot's own video and never control the robot: the API has no movement endpoint.
- **Errors never stop the camera.** A missing tunnel, a rejected token (401), no camera frame yet (503) or mock mode just retry; the dashboard shows the camera offline until frames arrive. reliefvision can start before the robot: it waits for the token file that `./scripts/start.sh` creates, and re-reads it after a 401.
- **Keep the rescue-bot folder separate** from your `main` checkout. Switching it to `main` would remove the robot software from that folder.
- **The token** is read from `token_file` (or `$TURTBOT_MODEL_TOKEN_FILE`) and only sent in the `Authorization` header. Never commit it, print it or put it in a URL.
- **Without the robot:** `python tests/fake_mission_control.py --token-file <file> --source 0` serves your webcam through the same API on port 8872.

## Heat maps (where people spent time)

Heat maps use each person's **foot point**, because the floor is the surface being mapped. Colours run blue (less time) to red (more time).

### Live heat layer (while the main command runs)

```bash
reliefvision --source clip.mov --no-aids --heat                       # 'recent': follows where people are now, fades after ~10 s
reliefvision --source clip.mov --no-aids --heat cumulative            # only builds up
reliefvision --source 0 --no-aids --heat --heat-half-life 20          # webcam / phone stream also works
reliefvision --source clip.mov --no-aids --follow-camera --save-video out/    # heat that follows a moving camera
```

The heat is drawn under the boxes and stats, in the live window and in `--save-video` output. The colour scale adapts as it goes, so "red" means the hottest spot so far, not a fixed amount of time.

**Fixed camera (default).** The heat only draws while the camera is steady, and clears whenever the camera moves, because heat is stored in image pixels and moving the camera would smear it.

**Moving camera (`--follow-camera`).** Each frame the background motion is estimated (a homography from tracked background points, ignoring people), new foot positions are placed on a scene-fixed canvas 3x3 screens large, and the canvas is warped back into the current view. The heat stays pinned to the floor while the camera pans or tilts.
- Checked on a simulated pan: after 20 s the estimated camera shift was within about 0.5% of the true value, and the heat stayed on the right spot.
- Limits: exact for pure rotation or a flat floor, approximate when the camera physically walks around (things at different depths shift differently); drifts slowly over long runs; heat more than about one screen from the starting view is dropped; needs a textured background to track. **Not yet tested on real handheld footage.**

**On the coordinator dashboard.** The dashboard's camera tiles play the same annotated video, so add the heat options to a `--serve-video` run: `reliefvision --config config.yaml --serve --serve-video --heat` (add `--follow-camera` for a robot or phone that moves along a line). Without `--serve-video` no frames, and so no heat layer, reach the dashboard; the per-camera metrics panel still shows the crowd grid.

### Offline heat maps and top-down floor map

Same idea as [kerberos-io/heatmap](https://github.com/kerberos-io/heatmap): detect people, convert positions with a homography onto a flat top-down plane, accumulate over a recording, and draw it on an image of the space. Needs a **fixed camera** and a video file.

```bash
# 1) camera-view heat map, no setup
python -m reliefvision.heatmap --source clip.mov --out heatmap/

# 2) one-time floor calibration: click 4 corners of a rectangle on the floor in this order:
#    far-left, far-right, near-right, near-left. Give its real size in metres.
python -m reliefvision.heatmap --source clip.mov --calibrate calib.json --plane-size 6x4
#    optional: --floorplan plan.png   an image of that same rectangle, used as the map background
#    headless: --points "120,300;700,300;780,600;40,600"   instead of clicking

# 3) camera view + top-down floor map
python -m reliefvision.heatmap --source clip.mov --calib calib.json --out heatmap/
```

Add `--video` to steps 1 or 3 for an animated version: `heatmap_video.mp4` (your video with the colour drawn on every frame) and, when calibrated, `heatmap_topdown_video.mp4`. `--video-mode cumulative` (default) builds up over the whole clip; `--video-mode recent --half-life 10` shows only roughly the last 10 seconds, fading. The colour scale is fixed for the whole video, so colours don't flicker. (Run `pip install -e .` again if you also want the short `reliefvision-heatmap` command.)

Outputs in `--out`:
- `heatmap_camera.png`: heat over a clean background with people removed
- `heatmap_topdown.png`: floor map with a 1 m grid, or your floor plan (calibrated runs)
- `heatmap_grid.json`: dwell seconds per cell (camera and top-down), for your platform to draw
- `heatmap_points.csv`: time and position, **no IDs**

Top-down accuracy depends on how carefully the four corners are clicked and on the floor being flat. Redo the calibration if the camera moves.

## Event schema and platform integration

`reliefvision/schema.py` (`Event`, `SCHEMA_VERSION = "0.1"`) is the contract with your platform. Adding fields is fine; renaming or removing one should bump the version. `mock_receiver.py` validates incoming events and serves them back:

```bash
pip install -e ".[server]"
uvicorn mock_receiver:app --port 8000          # GET /latest, /events, /schema
reliefvision --source clip.mov --webhook http://localhost:8000/events
```

If the network drops, events queue in a local SQLite outbox (`outbox.sqlite`, max 5000) and are delivered oldest-first when it returns. A JSONL copy is always written to `events.jsonl`.

## Dashboard API (`--serve`)

`--serve` adds a small HTTP API for the Project-DR coordinator dashboard, next to the normal events (which keep working as before). Without `--serve`, nothing extra runs.

```bash
pip install -e ".[server]"
reliefvision --config config.yaml --serve                          # counts, camera status and metrics on :8001
reliefvision --config config.yaml --serve --serve-video --heat     # ... plus live annotated video with the heat layer
```

Give each camera the dashboard's ids: `id: cam_s3` and `site_id: shelter_3` (per-camera `site_id` overrides the top-level one). Point the dashboard at it with `VITE_CV_API_URL=http://localhost:8001`. Clicking a camera tile in the dashboard opens its video next to its full metrics (the latest `Event` from `/api/cameras/{id}/stats`).

**Counting people in a line.** The dashboard count is the number of unique people seen in one *pass*: a TurtleBot (or someone with a phone) moves along the line, every tracked person is counted once even after they leave the frame, and when the pass ends its total replaces the previous one (so it can go down). Passes are controlled by the robot or operator:

```bash
curl -X POST http://<laptop>:8001/api/cameras/cam_s3/pass/start   # at one end of the line
curl -X POST http://<laptop>:8001/api/cameras/cam_s3/pass/end     # at the other end
```

A pass also ends after `pass.gap_s` (5 s) with nobody in view, and a camera that never calls `start` begins passes on its own when people appear. A person must be tracked in `pass.min_track_hits` (3) frames to count. If the tracker loses someone (for example behind another person) it can give them a new ID and count them twice; raise `min_track_hits` and keep the camera steady and side-on to reduce this.

| Method | Path | Returns |
|---|---|---|
| GET | `/health` | `{ok, cameras_online}` |
| GET | `/api/cameras` | `CameraFeed[]` (video links only with `--serve-video`) |
| GET | `/api/people-counts?since=<ISO 8601>` | `PeopleCount[]` (latest per camera without `since`) |
| POST | `/api/cameras/{id}/pass/start`, `/pass/end` | start / finish a pass; returns pass status |
| GET | `/api/cameras/{id}/pass` | `{in_pass, running_count, last_pass_count, ...}` |
| GET | `/api/cameras/{id}/stats` | that camera's latest `Event` (all the metrics above; `null` until the first one) |
| GET | `/phone` | iPhone camera page (see below) |
| GET | `/api/cameras/{id}/snapshot.jpg`, `/stream.mjpg` | annotated video, **only with `--serve-video`** |

`PeopleCount` and `CameraFeed` (`reliefvision/dashboard.py`) are the dashboard's shared contracts; `tests/test_contract.py` pins their fields.

**iPhone camera without an app (`source: push`).** When the phone can't accept incoming connections (campus Wi-Fi, iOS Local Network rules), it sends video to the laptop instead. Add a camera with `source: push`, run with `--serve`, and open `https://<laptop>.<tailnet>.ts.net/phone` in Safari on the phone. Safari only allows the camera over https; with [Tailscale](https://tailscale.com) on both devices, enable HTTPS certificates in the admin console and run `tailscale serve --bg 8001` on the laptop. The page streams about 10 frames/s and has Start pass / End pass buttons.

**Privacy.** Without `--serve-video`, only counts, camera status and the aggregate `Event` metrics leave the module, as with events. With it, annotated frames (boxes, overlay, heat) are streamed to whoever can reach the port; frames are still never stored.

## Tuning (per camera!)

- **Density thresholds** (`metrics.density_thresholds`) are fractions of the frame covered by people, so they depend on camera distance. A close-up of 4 people reads "high". Adjust once per camera setup.
- **`grid.cell_capacity`**: how many people make one grid cell "full" (default 3).
- **`metrics.stationary_speed_bh_s`**: raise it (try 0.3) if standing people read as moving.
- **Small / far people**: use `person.weights: yolo11s.pt` and `imgsz: 960` (slower).
- **`process_fps`**: 5-10 is plenty; lower it to fit more cameras on one machine or a slower laptop.

## Known limits (say these in your pitch)

- **Children** is a size heuristic: it can miss kids who are seated, cropped by the frame edge or hidden, and can flag short adults. It is reported only as a rough aggregate. **Elderly people cannot be identified reliably from video**, so mobility aids are the proxy; they are never attributed to individuals.
- **Mobility aids** (open-vocabulary) are the noisiest signal. Wheelchairs are usually found; canes and crutches often are not. The detector needs an extra model download (CLIP text encoder) on first use. On networks that intercept secure connections (some school, work or hackathon Wi-Fi) the download fails with a certificate error and the detector disables itself; use another network or `--no-aids`. Do not disable certificate checking.
- **Dense crowds**: detection undercounts when bodies overlap; the output says "at least N" rather than pretending. A low camera angle makes this worse (a small mast on the robot helps).
- **Flow, stagnation and free space** need a steady camera and a few seconds to a minute of observation.
- **Counts are estimates.** Compare against a manual count on your own footage and show both.

## What was verified (and not)

**Verified in a sandbox:**
- Metrics on synthetic scenes (`selftest.py`: counts, children, flow direction, stationary share, hotspot, free space).
- The full pipeline (detection, tracking, events, overlay) on a real image, and on test videos built from it.
- Schema validation, webhook delivery, and the offline outbox.
- Heat maps: camera view, top-down map (headless calibration), animated videos (cumulative and recent), and the live heat layer.
- Camera-following heat: motion-estimate accuracy and heat pinning on a simulated pan, checked against known ground truth.

**Verified on a Mac by the team:** installation, the selftest, and running the tool on a phone video.

**Not verified:**
- The wheelchair/walker detector end to end (its model download is blocked in the sandbox; the counting logic was tested with a fake model).
- The ROS 2 adapter (no ROS available).
- The click-to-calibrate window (tested only through `--points`).
- Camera-following heat on real handheld footage, and H.264 video output on macOS.
- Accuracy on real crowd video. Run it on your own footage before trusting any number.

## Licensing / supply chain

- Ultralytics YOLO is **AGPL-3.0**: fine for a hackathon; for a hosted platform, swap `YoloPersonDetector` (one class in `detector.py`) for RF-DETR or YOLOX, or buy a license.
- `supervision` (MIT) and `trackers` (Apache-2.0, ByteTrack) are from Roboflow. Pin versions (`pip freeze > requirements.lock`) once you have a working install.

## What not to commit

Model weights (`*.pt`), `.venv/`, `events*.jsonl`, `outbox.sqlite`, `out/`, `heatmap/`, `calib*.json`, and any test videos (`*.mov`, `*.mp4`): they contain or derive from footage of real people. Suggested `.gitignore`:

```
.venv/
__pycache__/
*.egg-info/
*.pt
events*.jsonl
outbox.sqlite
out/
heatmap/
calib*.json
*.mov
*.mp4
```

## Layout

```
reliefvision/   sources.py (file/webcam/RTSP/ROS 2) · detector.py · camera_motion.py · metrics.py
                overlay.py · events.py · pipeline.py · schema.py · config.py · cli.py · heatmap.py
                dashboard API (--serve): passcount.py · dashboard.py · server.py · static/phone.html
                TurtleBot camera: missioncontrol.py · observers.py (tests/fake_mission_control.py for demos)
selftest.py · mock_receiver.py · config.yaml · pyproject.toml · requirements.txt
tests/ (pytest: pip install -e ".[server,dev]")
```
