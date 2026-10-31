#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$task_root"
python3 -c 'import sys; assert sys.version_info >= (3,12), "Use Python 3.12 or newer on the Mac"'
if [[ ! -x .camera-venv/bin/python ]]; then python3 -m venv .camera-venv; fi
.camera-venv/bin/python -m pip install -r camera/requirements.txt -r dashboard/requirements.txt httpx
printf '%s\n' 'Mac dependencies ready. The existing Pi ROS and app environment are preserved.' 'Run ./scripts/start.sh to deploy and launch.'
