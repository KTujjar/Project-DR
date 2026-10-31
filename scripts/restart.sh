#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
exec "$task_root/.camera-venv/bin/python" "$task_root/scripts/missionctl.py" "restart" "$@"
