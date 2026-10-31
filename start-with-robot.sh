#!/usr/bin/env bash
# Compatibility entry point: use the same launcher and cleanup as ./start.sh.
# Mission Control must be started separately in the rescue-bot checkout.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
if [[ "${1:-}" == "--help" ]]; then
  exec "$ROOT/start.sh" --help
fi
ROBOT_DIR="${1:-${RESCUE_BOT_DIR:-}}"
if [[ "$#" -gt 1 || -z "$ROBOT_DIR" ]]; then
  echo "Usage: $0 /path/to/rescue-bot-folder" >&2
  echo "Or set RESCUE_BOT_DIR to that folder and run ./start.sh." >&2
  exit 1
fi

exec "$ROOT/start.sh" "$ROBOT_DIR"
