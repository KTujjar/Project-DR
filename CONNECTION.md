# Connection reliability repair — 2026-10-31

Two Mac supervisors were simultaneously managing the same Pi, one launched through
`Documents/Turtbot`, the other through `documents/turtbot`. The PID owner check
compared literal paths, so it missed the duplicate on the case-insensitive Mac
filesystem. The supervisors held different motion settings and repeatedly asked
the Pi manager to restart the app to their preferred setting. This caused real
backend shutdowns while the Ethernet link itself remained reachable.

## Repair

- A lifetime `flock` on `.robot/runtime/supervisor.lock` prevents a second daemon.
- PID ownership compares filesystem identity rather than path spelling.
- The daemon owns its PID record and clears only its own PID on shutdown.
- Supervisor, camera relay and SSH worker get explicit `/dev/null` standard input,
  avoiding invalid inherited input descriptors after launch terminals close.
- The supervisor checks/recreates its SSH master and repairs its own loopback
  forward, even when the master survives but the forwarding listener was canceled.
- The operator explicitly approved a dedicated Ed25519 login key for the Pi turtle
  account. The private key is local-only at `.robot/id_ed25519`, mode 0600; never
  committed. Existing authorized keys were preserved. This key disables agent/X11
  forwarding and PTY allocation, and limits local forwarding to 127.0.0.1:8765.
- SSH keepalives use a 5-second interval and three unanswered probes on new masters.
- `restart.sh` now restarts app/relay while preserving ROS bringup and its ownership
  record. Explicit `stop.sh` retains the documented ability to stop owned bringup.
- No network addresses, boot configuration, ROS packages, firmware or drivers changed.

## Checks

- Ethernet negotiated 100 Mbps full duplex. Five direct IPv6 probes had 0% packet
  loss and approximately 0.8 ms average RTT during diagnosis.
- Starting via an alternate capitalization reused the existing daemon.
- A direct second supervisor was rejected before creating any child services.
- A fresh SSH connection authenticated using the dedicated key without relying on
  the preexisting control session.
- Deliberately terminating the SSH master restored fresh camera and scan in **8.40 s**;
  backend PID and both hardware driver PIDs remained unchanged, controller disarmed.
- Canceling only the local forward restored the dashboard in **1.17 s**.
- A 45-second sampling window (47 seconds including final status checks) kept every
  camera/scan sample live with the same backend, drivers and bringup ownership.
- 76 unit/API tests passed, including filesystem-alias ownership, duplicate rejection,
  forwarding repair and preservation of hardware ownership on backend-only stop.
- Generated detailed evidence is under ignored `diagnostics/connection/` locally.

## Power is separate from application recovery

The Pi also recorded undervoltage and Ethernet link down/up events during this boot.
The operator confirmed power comes through OpenCR. A later check reported
`throttled=0x50000`: historical undervoltage/throttling flags, no active undervoltage
at that sample. Software recovery cannot correct a physical power drop. If this
returns, check the OpenCR-to-Pi power lead and robot power connections/battery.
Do not infer that all previous reboots were caused by undervoltage; that was not proved.
See [Raspberry Pi power documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#power-supply).

## Operator commands

```bash
./scripts/status.sh
./scripts/diagnose.sh
./scripts/restart.sh --no-browser
```

Keep Ethernet connected and the Mac awake for the dashboard. A deliberate Pi reboot
stops user-owned hardware bringup; the supervisor does not repeatedly restart drivers.
Run a deliberate start after reconnecting if bringup is absent. Every restarted
backend remains disarmed. Start uses motion locked by default; restart preserves
the selected motion configuration, including an explicitly selected obstacle override.

## Fresh clone

```bash
git clone --branch rescue-bot https://github.com/KTujjar/Project-DR.git
cd Project-DR
./scripts/install.sh
./scripts/start.sh --mock
```

For real hardware, use your own reachable Pi account/address and verify its SSH
host key into `.robot/known_hosts` before using the strict launcher. Set
`TURTBOT_TARGET=user@robot-address` or copy `config/connection.example.json` into
`.robot/connection.json` and edit it. Do not copy another operator's private key or
runtime token. The Pi must already have its ROS/hardware setup and the app virtual
environment described in OPERATOR.md. Gazebo is not needed for this connection.
