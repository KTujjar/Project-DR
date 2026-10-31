#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
task_target="${TURTBOT_TARGET:-turtle@fe80::ba27:ebff:fe79:d40f%en9}"
exec ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
  -o "UserKnownHostsFile=$task_root/.robot/known_hosts" \
  -L "127.0.0.1:${TURTBOT_LOCAL_PORT:-8872}:127.0.0.1:8765" "$task_target"
