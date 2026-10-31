#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
task_mode="${1:-mock}"
case "$task_mode" in
  mock) ;;
  hardware)
    # Existing drivers must already be running. This script never launches bringup.
    set +u
    source /opt/ros/humble/setup.bash
    set -u
    export TURTLEBOT3_MODEL=burger
    export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-30}"
    export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
    ;;
  *) echo 'Usage: bash dashboard/start.sh [mock|hardware]' >&2; exit 2 ;;
esac
export TURTBOT_MODE="$task_mode"
export TURTBOT_ALLOW_MOTION="${TURTBOT_ALLOW_MOTION:-0}"
cd "$task_root"
exec "$task_root/.venv/bin/python" -m uvicorn dashboard.backend.app:app --host 127.0.0.1 --timeout-graceful-shutdown 3 --port "${TURTBOT_PORT:-8765}"
