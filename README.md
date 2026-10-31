# Project-DR

Disaster-relief coordination: a coordinator dashboard fed by camera people-counting and community texts.

| Folder | What it is | Port |
|---|---|---|
| `dashboard/` | Coordinator dashboard (React + Vite) | 5173 |
| `relief-vision/` | Camera computer vision (`reliefvision`): people counts per pass, crowd metrics, heat maps, live video | 8001 |
| `relay-text-feature/` | Community text service and inbox | 8000 |

The TurtleBot3 robot software lives on the `rescue-bot` branch. Its Mission Control app runs on the Mac connected to the robot (port 8872).

## Show the TurtleBot camera on the dashboard

Do this on **the Mac connected to the robot** (by Ethernet).

1. **Keep two separate folders.** Leave the robot's `rescue-bot` folder as it is, and clone `main` somewhere else:
   ```bash
   git clone -b main https://github.com/KTujjar/Project-DR.git Project-DR-main
   ```
   Don't switch the rescue-bot folder to `main`: its robot software would disappear from it.
2. **Start the robot** as usual, in the rescue-bot folder: `./scripts/start.sh`.
3. **Start the dashboard with the robot camera**, in the `main` clone:
   ```bash
   ./start-with-robot.sh /path/to/rescue-bot-folder
   ```
   The first run installs dependencies and downloads a small person-detection model (about 5 MB).
4. Open **http://localhost:5173** and click the **`cam_robot`** tile for live video, heat map, crowd metrics, and **Start pass** / **End pass** for counting people along a line.

The order doesn't matter: if the robot isn't started yet, the tile stays offline and switches on by itself once it is. The robot's people boxes also appear on Mission Control's own video. Nothing in this repo can move the robot.

To count a different site, change `site_id` in `relief-vision/config.robot.yaml`. More detail is in `relief-vision/README.md` (section "TurtleBot3 camera").

## Run without the robot

```bash
cd relay-text-feature && python -m uvicorn backend.main:app --port 8000           # community texts
cd relief-vision && reliefvision --config config.yaml --serve --serve-video --heat   # cameras
cd dashboard && npm run dev       # with VITE_CV_API_URL=http://localhost:8001 in dashboard/.env.local
```
