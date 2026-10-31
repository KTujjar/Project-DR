# RESQ

Disaster-relief coordination: a coordinator dashboard fed by camera people-counting and community texts.

| Folder | What it is | Port |
|---|---|---|
| `dashboard/` | Coordinator dashboard (React + Vite) | 5173 |
| `relief-vision/` | Camera computer vision (`reliefvision`): people counts per pass, crowd metrics, heat maps, live video | 8001 |
| `relay-text-feature/` | Community text service and inbox | 8000 |

The TurtleBot3 robot software lives on the `rescue-bot` branch. Its Mission Control app runs on the Mac connected to the robot (port 8872).

## Start everything together

With the apps already set up, run from this folder:

```bash
./start.sh
```

This starts the text service on **8000**, computer vision with the laptop and phone cameras on **8001**, the dashboard at **http://localhost:5173**, and Tailscale Serve for the phone camera. Open the HTTPS address printed by Tailscale with `/phone` appended on your phone.

**Ctrl+C stops all four services and removes the launcher's Tailscale Serve mapping.** Closing the terminal or terminating the launcher also triggers cleanup. If any service exits, the launcher stops the others. Serve runs in foreground mode so its mapping does not persist after its process exits. Tailscale itself stays connected.

If you previously enabled persistent Serve with `tailscale serve --bg 8001`, turn that mapping off once with `tailscale serve --https=443 off` before using the launcher. Tailscale must already be signed in with HTTPS enabled.

The launcher uses `relay-text-feature/.venv/bin/python`, `relief-vision/.venv/bin/reliefvision`, and the dashboard's installed Vite. It does not reinstall dependencies or change `.env` files. For a different existing Python or vision environment, set `TEXT_PYTHON` or `VISION_BIN` to its executable path.

To include the robot camera, start Mission Control in its separate checkout, then run:

```bash
./start.sh /path/to/rescue-bot-folder
```

This uses the same `config.robot.yaml` as the robot launcher, showing **cam_shannon, cam_laptop, and cam_phone**. You do not need to run both launchers. `start-with-robot.sh` now forwards to `start.sh`, including the text service and Tailscale shutdown handling.

For subsequent runs with just `./start.sh`, set the folder in your terminal (or your shell profile):

```bash
export RESCUE_BOT_DIR="/path/to/rescue-bot-folder"
./start.sh
```

If `TURTBOT_MODEL_TOKEN_FILE` is already set, `./start.sh` also enables the three-camera config using that token path. Without either robot setting, it runs the laptop and phone cameras and prints instructions for enabling the robot.

## Camera chatbot

Click a camera tile: under the video, **Ask about this camera** answers questions such as "What's happening now?", "What happened in the last 10 minutes?" or "Does anyone need help?". It uses Claude Haiku 5.5 with the current camera image, the last 30 minutes of crowd metrics and passes, and a **scene log**: every ~30 seconds (sooner when something changes) the AI writes a short note about what the camera shows, so you can ask about earlier moments. The notes are listed under **Recent observations**.

It uses the same key as the text service: put `ANTHROPIC_API_KEY=...` in `relay-text-feature/.env` (git-ignored, never commit it) and run `./start.sh`, which hands the key to the vision service. Without a key, the chat says how to turn it on and no scene notes are made.

**Privacy and cost:** camera frames are sent to Anthropic's API for each question and each scene note (about 2 per minute per online camera; well under a cent per camera-hour with Haiku). Nothing is stored on disk. The AI is told never to identify people. To turn it off, set `chat: {enabled: false}` (or `scene_log: {enabled: false}`) in the camera config; see `relief-vision/README.md`.

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
   Set up the app dependencies first, as for `./start.sh`. The first vision run downloads a small person-detection model (about 5 MB).
4. Open **http://localhost:5173**. The dashboard shows only the three real cameras. Click a tile for live video, crowd metrics, and **Start pass** / **End pass** for counting people along a line:

   | Tile | Camera | Counts shelter |
   |---|---|---|
   | `cam_shannon` | TurtleBot3 camera | Lebanon Middle School (`shelter_3`) |
   | `cam_laptop` | This Mac's built-in camera | Hanover High School (`shelter_1`) |
   | `cam_phone` | iPhone, through the `/phone` page (see below) | Leverone Field House (`shelter_2`) |

The order doesn't matter: if the robot isn't started yet, its tile stays offline and switches on by itself once it is. The robot's people boxes also appear on Mission Control's own video. Nothing in this repo can move the robot.

**Headcounts:** a shelter with a real camera takes its headcount from that camera. Norwich Town Hall, which has no camera, keeps a simulated headcount. To change which shelter a camera counts, edit `site_id` in `relief-vision/config.robot.yaml`. More detail is in `relief-vision/README.md` (sections "TurtleBot3 camera" and "Dashboard API").

**Phone camera:** with [Tailscale](https://tailscale.com) on the Mac and the iPhone, run `tailscale serve --bg 8001` on the Mac, then open `https://<mac-name>.<tailnet>.ts.net/phone` in Safari and tap **Start camera**. Safari only allows camera access over https. Turn it off afterwards with `tailscale serve --https=443 off`.

## Run without the robot

The same dashboard with the laptop and phone cameras (`cam_shannon` is left out):

```bash
cd relay-text-feature && python -m uvicorn backend.main:app --port 8000   # community texts
cd relief-vision && reliefvision --config config.dashboard.yaml            # laptop + phone cameras
cd dashboard && npm run dev       # with VITE_CV_API_URL=http://localhost:8001 in dashboard/.env.local
```
