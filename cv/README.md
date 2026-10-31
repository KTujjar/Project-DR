# Project-DR CV service

Counts the people in a line using a moving camera, such as a TurtleBot3 Burger driving along the line or an iPhone carried from one end to the other. It serves the results to the coordinator dashboard as `PeopleCount` and `CameraFeed` records (contracts in the root `CLAUDE.md`).

## How counting works

The camera makes **passes** along the line. During a pass, YOLOv8 + ByteTrack gives each person a track ID, and every person seen is counted once, even after they leave the frame. When the pass ends, its total becomes the published `people_count`. It stays fixed while the next pass recounts, and is then replaced, so the count can go down when the line gets shorter. Before the first pass finishes, the running count is published so the dashboard isn't empty.

A pass starts and ends in one of two ways:

- **Explicitly (recommended):** the robot or phone operator calls `POST /api/cameras/{id}/pass/start` at one end of the line and `POST /api/cameras/{id}/pass/end` at the other. After a camera's first `start`, it only begins passes on request, so driving back to the start of the line doesn't trigger a recount.
- **Automatically (fallback):** a pass ends after `CV_PASS_GAP_S` (5 s) with nobody in view. A camera that never calls `start` also begins a pass on its own when people appear.

A person must be tracked in `CV_MIN_TRACK_HITS` (3) detections to count, which filters out tracker flicker. `confidence` is the mean best detection score of the counted people.

Known limit: if a person is hidden for a while (for example behind someone else), the tracker may give them a new ID when they reappear and count them twice. A steady camera speed and a side-on view of the line help.

## Run it

Needs [uv](https://docs.astral.sh/uv/). Python 3.12 is installed automatically.

```bash
cd cv
uv sync
cp cameras.example.yaml cameras.yaml   # map cameras to dashboard sites
cp .env.example .env                   # defaults are fine for local use
uv run cv-service                      # http://localhost:8001
```

The first run downloads the YOLO weights (`yolov8n.pt`, about 6 MB). On macOS, allow camera access for your terminal when prompted.

### Camera sources

Each entry in `cameras.yaml` maps one feed to a dashboard site:

```yaml
cameras:
  - camera_id: cam_s3      # must match the dashboard's camera ids
    site_id: shelter_3     # must match a dashboard location id
    source: 0              # webcam index, rtsp:// or http:// URL, or a video file path
    loop: true             # replay video files when they end
```

The mock dashboard uses `cam_s1` to `cam_s4` for `shelter_1` to `shelter_4`. A CV camera with the same id replaces that mock camera; the others keep mock data.

For the TurtleBot3, publish its camera as an MJPEG stream from the Pi, for example with ROS `web_video_server` (`source: http://<pi-ip>:8080/stream?topic=/camera/image_raw`). For an iPhone, use any IP-camera app and put its stream URL in `source`. The ROS node (or a shortcut on the phone) then calls the `pass/start` and `pass/end` endpoints at each end of the line:

```bash
curl -X POST http://<laptop-ip>:8001/api/cameras/cam_s3/pass/start   # at the first person in line
curl -X POST http://<laptop-ip>:8001/api/cameras/cam_s3/pass/end     # at the last person
```

## Connect the dashboard

On the `dashboard` branch, set this in `dashboard/.env.local` and restart `npm run dev`:

```bash
VITE_CV_API_URL=http://localhost:8001
```

The dashboard keeps everything else from its normal source (mock or API) and overlays live camera tiles and people counts from this service. If the service stops, its cameras turn grey ("Offline") and go stale after 60 s. They come back on their own when it restarts.

## API

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/health` | `{ ok, cameras_online }` |
| GET | `/api/cameras` | `CameraFeed[]` |
| GET | `/api/people-counts?since=<ISO 8601>` | `PeopleCount[]`: everything after `since`, or the latest per camera without it |
| POST | `/api/cameras/{id}/pass/start` | Starts a new pass (discards one in progress); returns pass status |
| POST | `/api/cameras/{id}/pass/end` | Ends the pass and publishes its total; returns pass status |
| GET | `/api/cameras/{id}/pass` | `{ camera_id, in_pass, managed, running_count, last_pass_count, passes_completed }` |
| GET | `/api/cameras/{id}/snapshot.jpg` | Latest frame with track boxes and pass status |
| GET | `/api/cameras/{id}/stream.mjpg` | Live MJPEG stream (open it in a browser) |

A count is published at least once per second, so the dashboard sees fresh timestamps, and immediately when a pass ends. A camera with no frame for 10 s is reported offline.

## Tests

```bash
uv run pytest
```

Tests use a fake detector and synthetic frames, so they need no camera or model weights. `tests/test_contract.py` checks the JSON fields against the TypeScript interfaces in the root `CLAUDE.md`.

## Settings (`.env`)

| Variable | Default | Meaning |
| --- | --- | --- |
| `CV_CONFIG` | `cameras.yaml` | Camera list |
| `CV_HOST` / `CV_PORT` | `0.0.0.0` / `8001` | Where the API listens |
| `CV_PUBLIC_URL` | `http://localhost:8001` | Base URL browsers use for snapshot and stream links |
| `CV_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Origins allowed to call the API |
| `CV_MODEL` | `yolov8n.pt` | YOLO weights |
| `CV_DEVICE` | `mps` | `mps` (Apple GPU), `cpu`, or `cuda`; falls back to CPU if unavailable |
| `CV_CONF` | `0.4` | Minimum score to count a person |
| `CV_INFER_EVERY_S` | `0.1` | Seconds between detections per camera (tracking needs several per second) |
| `CV_MIN_TRACK_HITS` | `3` | Detections a tracked person needs before being counted |
| `CV_PASS_GAP_S` | `5` | Seconds with nobody in view before a pass auto-ends |
| `CV_OFFLINE_AFTER_S` | `10` | Seconds without a frame before a camera reports offline |
