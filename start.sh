#!/usr/bin/env bash
# Run the local stack using the environments already installed in this checkout.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
if [[ "${1:-}" == "--help" || "$#" -gt 1 ]]; then
  echo "Usage: $0 [path/to/rescue-bot-folder]"
  echo "Starts texts (:8000), vision (:8001), dashboard (:5173), and Tailscale Serve."
  echo "Pass the rescue-bot folder (or set RESCUE_BOT_DIR) for robot + laptop + phone cameras."
  echo "Press Ctrl+C to stop everything. The robot's Mission Control is started separately."
  exit 0
fi

TEXT_PYTHON="${TEXT_PYTHON:-$ROOT/relay-text-feature/.venv/bin/python}"
VISION_BIN="${VISION_BIN:-$ROOT/relief-vision/.venv/bin/reliefvision}"
VITE_BIN="$ROOT/dashboard/node_modules/.bin/vite"
for executable in "$TEXT_PYTHON" "$VISION_BIN" "$VITE_BIN"; do
  if [[ ! -x "$executable" ]]; then
    echo "Missing executable: $executable. Complete this app's setup first (see README.md)." >&2
    exit 1
  fi
done
command -v tailscale >/dev/null || { echo "Tailscale CLI is not on PATH." >&2; exit 1; }

CONFIG=config.dashboard.yaml
ROBOT_DIR="${1:-${RESCUE_BOT_DIR:-}}"
if [[ -n "$ROBOT_DIR" ]]; then
  ROBOT_DIR="$(cd "$ROBOT_DIR" && pwd)"
  if [[ "$ROBOT_DIR" == "$ROOT" || ! -f "$ROBOT_DIR/scripts/start.sh" ]]; then
    echo "Use a separate rescue-bot checkout containing scripts/start.sh." >&2
    exit 1
  fi
  export TURTBOT_MODEL_TOKEN_FILE="$ROBOT_DIR/.robot/runtime/service.token"
  CONFIG=config.robot.yaml
elif [[ -n "${TURTBOT_MODEL_TOKEN_FILE:-}" ]]; then
  CONFIG=config.robot.yaml
fi
if [[ "$CONFIG" == config.robot.yaml ]]; then
  echo "Cameras: cam_shannon, cam_laptop, cam_phone"
  if [[ ! -f "$TURTBOT_MODEL_TOKEN_FILE" ]]; then
    echo "Note: robot token not available yet. Start Mission Control in the rescue-bot folder."
    echo "The robot camera will wait for its token and connection."
  fi
else
  echo "Cameras: cam_laptop, cam_phone"
  echo "For all three cameras: $0 /path/to/rescue-bot-folder (or set RESCUE_BOT_DIR)."
fi

# Refuse occupied ports instead of connecting the dashboard to an unrelated app.
"$TEXT_PYTHON" - <<'PY'
import socket
import sys

sockets = []
try:
    for port in (8000, 8001, 5173):
        sock = socket.socket()
        sockets.append(sock)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError as exc:
            sys.exit(f"Cannot use port {port}: {exc}. Stop the existing app before starting the stack.")
finally:
    for sock in sockets:
        sock.close()
PY

# Job control gives each service its own process group, including any children.
# This also works with the Bash 3.2 shipped by macOS (no wait -n required).
set -m
pids=()
names=()
cleanup() {
  local status=$? pid attempt running
  trap - EXIT
  trap '' INT TERM HUP
  echo
  echo "Stopping applications and Tailscale Serve..."
  for pid in "${pids[@]}"; do
    kill -TERM -- "-$pid" 2>/dev/null || true
  done
  for ((attempt=0; attempt<50; attempt++)); do
    running=false
    for pid in "${pids[@]}"; do
      if kill -0 -- "-$pid" 2>/dev/null; then running=true; fi
    done
    if [[ "$running" == false ]]; then break; fi
    sleep 0.1
  done
  for pid in "${pids[@]}"; do
    kill -KILL -- "-$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  done
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

cd "$ROOT/relay-text-feature"
"$TEXT_PYTHON" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
pids+=($!)
names+=("Text service")

# The camera chatbot (in reliefvision) uses the same Anthropic key as the text service.
# It's read from relay-text-feature/.env (never printed) unless ANTHROPIC_API_KEY is already set.
CHAT_KEY="${ANTHROPIC_API_KEY:-}"
if [[ -z "$CHAT_KEY" && -f "$ROOT/relay-text-feature/.env" ]]; then
  CHAT_KEY="$(sed -n 's/^[[:space:]]*ANTHROPIC_API_KEY[[:space:]]*=[[:space:]]*//p' "$ROOT/relay-text-feature/.env" \
    | tail -n 1 | tr -d "\"'\r")"
fi
if [[ -z "$CHAT_KEY" ]]; then
  echo "Camera chat: off (no ANTHROPIC_API_KEY in relay-text-feature/.env)."
fi

cd "$ROOT/relief-vision"
ANTHROPIC_API_KEY="$CHAT_KEY" "$VISION_BIN" --config "$CONFIG" --no-display &
pids+=($!)
names+=("Computer vision")

cd "$ROOT/dashboard"
VITE_CV_API_URL=http://localhost:8001 VITE_TEXT_API_BASE_URL=/relay-api \
  "$VITE_BIN" --host 127.0.0.1 --port 5173 --strictPort &
pids+=($!)
names+=("Dashboard")

# Deliberately omit --bg: the Serve mapping belongs to this process and is
# removed when the Serve process exits.
tailscale serve --bg=false --https=443 http://127.0.0.1:8001 &
pids+=($!)
names+=("Tailscale Serve")

echo "Dashboard: http://localhost:5173"
echo "Text app:  http://127.0.0.1:8000"
echo "Phone: open the HTTPS URL printed by Tailscale with /phone appended."
echo "Press Ctrl+C to stop all four services."

while true; do
  for ((i=0; i<${#pids[@]}; i++)); do
    if ! kill -0 "${pids[$i]}" 2>/dev/null; then
      status=0
      wait "${pids[$i]}" || status=$?
      echo "${names[$i]} exited (status $status); stopping the stack." >&2
      if [[ "$status" -eq 0 ]]; then status=1; fi
      exit "$status"
    fi
  done
  sleep 1
done
