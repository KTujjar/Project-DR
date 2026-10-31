# Project-DR CV service

Counts people in camera feeds with YOLOv8 and serves the results to the coordinator dashboard as `PeopleCount` and `CameraFeed` records (contracts in the root `CLAUDE.md`).

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
| GET | `/api/cameras/{id}/snapshot.jpg` | Latest frame with detection boxes |
| GET | `/api/cameras/{id}/stream.mjpg` | Live MJPEG stream (open it in a browser) |

How counting works:
- `people_count` is the number of person detections at or above `CV_CONF` (0.4), taken as the median of the last 5 detections to smooth out flicker.
- `confidence` is the mean score of the counted people. With nobody in frame, it is 1 minus the strongest near-miss.
- Detection runs once per second per camera (`CV_INFER_EVERY_S`).
- A camera with no frame for 10 s is reported offline.

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
| `CV_INFER_EVERY_S` | `1` | Seconds between detections per camera |
| `CV_OFFLINE_AFTER_S` | `10` | Seconds without a frame before a camera reports offline |
