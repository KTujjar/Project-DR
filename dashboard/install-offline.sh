#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ! -x "$task_root/.venv/bin/python" ]]; then
  python3 -m venv --without-pip --system-site-packages "$task_root/.venv"
fi
shopt -s nullglob
task_pip_wheels=("$task_root"/wheelhouse/pip-*.whl)
if [[ ${#task_pip_wheels[@]} -ne 1 ]]; then
  echo 'Offline wheelhouse needs exactly one pip wheel.' >&2
  exit 2
fi
PYTHONPATH="${task_pip_wheels[0]}" "$task_root/.venv/bin/python" -m pip install \
  --disable-pip-version-check --no-index --find-links "$task_root/wheelhouse" pip -r "$task_root/dashboard/requirements.txt"
"$task_root/.venv/bin/python" -c 'import fastapi, uvicorn, websockets; print("Dashboard application dependencies ready")'
