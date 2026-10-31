# CLAUDE.md: Project-DR CV service

This folder (`cv/`) is the **Video Capture + Video Processing** module described in the root `CLAUDE.md`. It reads camera feeds, counts people with YOLO, and serves `PeopleCount` and `CameraFeed` records over HTTP for the coordinator dashboard (branch `dashboard`).

Cameras are moving: a TurtleBot3 Burger (or a person with an iPhone) sweeps along a line of people. The count is the number of unique tracked people seen in one full pass. People who leave the frame stay counted, and each finished pass replaces the previous total (`counting.PassCounter`).

## Rules

- Work only inside `cv/`. The dashboard lives on the `dashboard` branch and is owned separately.
- The JSON shapes are the shared contracts in the root `CLAUDE.md` (`PeopleCount`, `CameraFeed`). Never rename or add fields; `tests/test_contract.py` enforces this.
- Timestamps are UTC ISO 8601 with milliseconds and `Z` (`timeutil.iso_now()`), same as JS `toISOString()`. The dashboard compares them as strings.
- Counting logic stays pure and unit-tested in `counting.py`. Camera/model code stays thin.
- Tests never need a camera or model weights: use the fake detector and synthetic frame sources in `tests/`.
- Commit after each step with a message like `cv: step 3 - detector and camera worker`.

## Commands

```bash
uv sync                    # install (Python 3.12)
uv run pytest              # tests
uv run cv-service          # run the service (reads .env and cameras.yaml)
```

## Endpoints

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/health` | `{ ok, cameras_online }` |
| GET | `/api/cameras` | `CameraFeed[]` |
| GET | `/api/people-counts?since=` | `PeopleCount[]` (latest per camera when `since` is omitted) |
| POST | `/api/cameras/{id}/pass/start` | Starts a pass along the line |
| POST | `/api/cameras/{id}/pass/end` | Ends the pass and publishes its total |
| GET | `/api/cameras/{id}/pass` | Pass status |
| GET | `/api/cameras/{id}/snapshot.jpg` | Latest annotated frame |
| GET | `/api/cameras/{id}/stream.mjpg` | Live MJPEG stream |
