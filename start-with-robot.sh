#!/usr/bin/env bash
# Shows the TurtleBot3 camera, this Mac's webcam and the iPhone /phone camera on the dashboard.
#
# Run on the Mac connected to the robot, from a checkout of `main` that is SEPARATE from the
# rescue-bot folder (don't switch the rescue-bot folder to main: its robot software would vanish).
#
#   1. In the rescue-bot folder:   ./scripts/start.sh          (robot Mission Control on :8872)
#   2. In this main checkout:      ./start-with-robot.sh /path/to/rescue-bot-folder
#   3. Open http://localhost:5173 and click the cam_robot tile.
#
# Starts reliefvision (robot camera -> people counts, heat, metrics on :8001) and the dashboard
# (:5173). Ctrl-C stops both. Nothing here can move the robot.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
ROBOT_DIR="${1:-${RESCUE_BOT_DIR:-}}"

if [[ -z "$ROBOT_DIR" ]]; then
  echo "Usage: ./start-with-robot.sh /path/to/rescue-bot-folder" >&2
  echo "       (the folder where you run the robot's ./scripts/start.sh)" >&2
  exit 1
fi
ROBOT_DIR="$(cd "$ROBOT_DIR" && pwd)"
if [[ "$ROBOT_DIR" == "$ROOT" ]]; then
  echo "This is the main checkout, not the rescue-bot folder. Use a separate clone for main." >&2
  exit 1
fi
if [[ ! -f "$ROBOT_DIR/scripts/start.sh" ]]; then
  echo "No scripts/start.sh in $ROBOT_DIR: is that the rescue-bot folder?" >&2
  exit 1
fi

# reliefvision reads the robot's API token from here (never printed or copied).
export TURTBOT_MODEL_TOKEN_FILE="$ROBOT_DIR/.robot/runtime/service.token"
if [[ ! -f "$TURTBOT_MODEL_TOKEN_FILE" ]]; then
  echo "Note: $TURTBOT_MODEL_TOKEN_FILE doesn't exist yet. Start the robot (./scripts/start.sh"
  echo "      in the rescue-bot folder); reliefvision will wait for it."
fi
code="$(curl -s -o /dev/null -m 3 -w '%{http_code}' http://127.0.0.1:8872/api/v1/perception/input || true)"
if [[ "$code" == "000" ]]; then
  echo "Note: robot Mission Control isn't answering on :8872 yet. The robot tile stays offline until it does."
fi

# One-time setup.
cd "$ROOT/relief-vision"
if [[ ! -x .venv/bin/reliefvision ]]; then
  echo "Setting up reliefvision (first run only)..."
  python3 -m venv .venv
  .venv/bin/pip install -q -e ".[server]"
fi
cd "$ROOT/dashboard"
[[ -d node_modules ]] || { echo "Installing dashboard dependencies (first run only)..."; npm install --no-audit --no-fund; }
grep -qs '^VITE_CV_API_URL=' .env.local || echo 'VITE_CV_API_URL=http://localhost:8001' >> .env.local

# Run both; stop both on exit.
cd "$ROOT/relief-vision"
.venv/bin/reliefvision --config config.robot.yaml --no-display &
RV_PID=$!
trap 'kill $RV_PID 2>/dev/null || true' EXIT INT TERM

cd "$ROOT/dashboard"
echo "Dashboard: http://localhost:5173  (camera tiles: cam_robot, cam_laptop, cam_phone)"
npm run dev -- --port 5173
