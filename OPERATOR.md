# Turtle SAR Mission Control — operator guide

This is a hackathon demonstrator for supervised indoor operation, not an autonomous
or deployment-ready rescue robot. Real camera, LiDAR, battery, IMU, wheel feedback
and odometry are integrated. ML demonstrations are explicitly marked MOCK.

## Start, stop and recover

On this Mac, from `/Users/coletriebold/Documents/Turtbot`:

```bash
./scripts/install.sh                 # first-time Mac dependencies only
./scripts/start.sh                   # deploy, verify/start services, open browser
./scripts/status.sh                  # process state + actual sensor freshness/rates
./scripts/diagnose.sh                # one-command diagnostic report
./scripts/restart.sh                 # restart app/relay; preserve running hardware drivers
./scripts/stop.sh                    # stop this app/relay; stop owned bringup only
```

Dashboard: **http://127.0.0.1:8872/**. Reopen that URL without restarting anything.
Use `--no-browser` with start/restart if a browser tab is already open.
This Mac now has an explicitly approved dedicated SSH key in `.robot/id_ed25519`.
The supervisor recreates a lost SSH master and local tunnel without a password.
The private key is ignored by Git and must never be copied into the repository.
Fresh clones without an enrolled key can ask for the Pi account password in the
terminal; no SSH password is saved or hardcoded. Keep Ethernet connected. The known-hosts
file is `.robot/known_hosts`; scoped IPv6 target is in `.robot/connection.json`.
Set `TURTBOT_TARGET` if the Ethernet adapter/address changes.

The one-time Mac installer uses Python 3.12+, NumPy, Pillow, FastAPI, Uvicorn,
WebSockets and test HTTP dependencies in `.camera-venv`. It preserves the original
RAW10 converter and the older USB environment. On this actual Pi the app virtual
environment and ROS dependencies were already installed; start verifies them.
It compiles two small C workers with the Pi's existing compiler and stock headers.
The vendored ISP UAPI header comes from Raspberry Pi's existing kernel interface;
it is not a driver installation. No apt upgrade, ROS replacement, firmware flash,
boot change, network change or major camera-stack installation is performed.

The deployed Pi project is `/home/turtle/turtbot-dashboard`. If its app `.venv`
is missing, restore the previously prepared offline wheelhouse and run
`bash dashboard/install-offline.sh` there before starting. Do not rebuild/reflash
the robot to repair an application dependency.

## What the launcher manages

1. Establish/reuse private SSH access; deploy changed project sources and API token.
2. Confirm Humble and reuse the running OpenCR/LDS drivers. Start one existing
   bringup only when both are absent and the two serial devices exist.
3. Start/reuse the Pi backend and connect Mac loopback port 8872 to Pi loopback 8765.
4. Apply the approved native camera runtime mode, exposure and gain.
5. Supervise a Mac relay and the Pi backend. The camera worker is started through
   an SSH session, owns a camera lock, and exits if capture fails or the session ends.
6. Open the dashboard disarmed. Default start locks motion; explicit motion flags enable manual arming.

A lifetime file lock prevents duplicate supervisors, including launches through
differently capitalized paths on macOS. `restart.sh` stops only the backend/relay
and preserves ROS bringup even when this launcher originally started it.
See [CONNECTION.md](CONNECTION.md) for the diagnosed failure and recovery checks.

No systemd units or login/boot services were installed. The Mac supervisor is a
user process. Backend crashes are restarted; each backend starts disarmed.
Hardware drivers are **not** repeatedly restarted by the supervisor. Partial or
duplicate bringup fails visibly instead of taking over a serial device.
`stop.sh` leaves a reused/unowned bringup running; it never kills unrelated drivers.
Only a bringup created and tracked by the new launcher is stopped as owned.
Process identities include Linux start time, so stale PIDs are not blindly killed.

## Camera modes and quality

The active/default live mode is **640×480**, nominal acquisition **15 fps**. This
keeps the corrected high-quality processing while reducing latency. The tested
1280×720 mode offers more detail for stationary inspection, but the complete
multi-client dashboard delivered only about 2 fps / 1.07 s median decode-ACK in the
noisy room scene, despite an 8.1 fps standalone capture/encode benchmark. It was
not retained as the live driving view. `restart.sh` preserves the selected mode.

The ISP performs Bayer demosaic, black subtraction (64 RAW10 counts), bounded
scene-estimated white balance, a reference color matrix and one sRGB gamma step.
The old 7× viewing brightness gain was removed; ISP and sensor digital gain are
unity. A small RAW histogram meter adjusts sensor exposure/gain twice per second:
mid-grey target 0.18, broad-highlight cap, maximum exposure about 33 ms, maximum
analogue gain 4×. It prefers exposure over analogue gain within those limits.
White balance uses unclipped, non-dark Bayer cells and smooths changes. This is
simple gray-world metering; it can misestimate scenes dominated by one color.

The already-installed `/dev/video31` hardware image encoder makes JPEGs at fixed
quality **92**, replacing the bitrate-controlled video MJPEG encoder that varied
compression. JPEGs travel through SSH to the Mac relay, are fully decoded/validated,
and return unchanged to authenticated camera ingest. No extra ISP-path resize,
brightness boost, color filter, or JPEG re-encoding occurs on the Mac/browser.
The only normal resize is ISP 1920×1080 → 1280×720. This is lossy display video,
not archival RAW. The original RAW still and converter are preserved.

Change mode with explicit stop/start (repeat your chosen motion flags if wanted):

```bash
./scripts/stop.sh
TURTBOT_CAMERA_WIDTH=1920 TURTBOT_CAMERA_HEIGHT=1080 ./scripts/start.sh
# Higher-detail 1280×720 output; plain start keeps motion locked.

./scripts/stop.sh
./scripts/start.sh
# Lower-latency 640×480 output, also with corrected processing and JPEG Q92.
```

Supported native inputs: 640×480, 1920×1080 → 1280×720, and 1640×1232 → 1280×960.
`TURTBOT_CAMERA_FPS` is a 5–30 target, not a delivery promise.
`TURTBOT_CAMERA_GAIN` (0–232, default 0) sets the initial capture gain; the ISP worker
then meters automatically within its 1–4× bound. `TURTBOT_CAMERA_PATH=auto|isp|raw`
selects the path. Configure starts near 16.7 ms with sensor digital gain unity.

After three consecutive hardware-path failures, auto mode tries native RAW capture
and the Mac converter. That fallback uses gray-world WB, zero viewing EV, Lanczos
resize and one quality-92 JPEG encode with 4:4:4 sampling. It does not run sensor
AE; it keeps the last capture settings, so changing light can need attention.
The source label changes to show the active path.

Color correction remains approximate: no chart calibration, calibrated intrinsics,
automatic lens shading, or guarantee of focus. Small lights can saturate and dim
scenes remain noisy. The quality HUD warns when most sampled pixels are near white
or black. See `diagnostics/camera-quality/REPORT.md` for the same-RAW comparison,
adaptation and end-to-end integrity checks. Existing `camera/convert_raw10.py`
and its original eight tests remain available for full-resolution still processing.

Video HUD shows actual decoded display FPS, ingest rate, resolution, pipeline
latency and browser-ACK latency. Latency is measured from the Pi's **end-of-frame**
timestamp; ACK includes browser decode and return travel. It excludes sensor
exposure before that timestamp and is **not optical glass-to-glass latency**.
See `diagnostics/mission/performance.json` and PERFORMANCE.md for measured results.

## Driving and stopping

**Physical movement has not been tested in this setup run. The operator approved
a brief elevated-wheel test, but LiDAR prechecks blocked it. The operator subsequently
requested manual motion with obstacle blocking bypassed. This does not validate physical stopping.** The software contains WASD/arrow-key and pointer controls, arming,
exclusive browser ownership, conflict checks, limits and an independent ROS timer
watchdog. No nonzero velocity command was sent during installation/diagnostics.

Before an initial test, obtain explicit approval, put both wheels securely off the
ground, and keep the operator physically present. Only then stop and start with:

```bash
./scripts/stop.sh
./scripts/start.sh --allow-motion --wheels-elevated
```

The operator can explicitly enable manual control with the LiDAR veto bypassed:

```bash
./scripts/stop.sh
./scripts/start.sh --allow-motion --bypass-obstacles
```

This setting persists through `restart.sh` and backend recovery, but every backend
still starts disarmed. The UI displays **Obstacle guard · bypassed**. Obstacles,
missing/stale scans and coverage gaps do not veto motion in this mode. LiDAR
continues displaying and reporting its scan diagnostics. Arming, one-browser
ownership, velocity limits, acceleration limits, release/Stop, heartbeat and
command watchdogs, and competing-publisher checks remain active.

To restore guarded operation, stop and start with `--allow-motion --wheels-elevated`.
To lock movement again, stop and run plain `./scripts/start.sh`.

Those flags are the operator's deliberate assertion of readiness, not a substitute
for the approval or physical setup. Press **Arm controls** separately in the UI.
No service restart re-arms the controller. Use low speed and one brief direction,
then verify release, stop, heartbeat and disconnect behavior before floor driving.
Never use a mock-mode result as physical safety validation.

Limits: 0.08 m/s, 0.5 rad/s; acceleration 0.12 m/s² and 0.8 rad/s². Release/zero/Stop
bypasses the acceleration ramp. Command deadman is 250 ms, heartbeat expiry 600 ms;
ROS watchdog ticks at 50 ms. The guard requires fresh scans within 500 ms and stops
and disarms for obstacles, missing/invalid coverage or another velocity publisher.
Its default envelope is 0.30 m plus speed-dependent allowance. At 0.08 m/s the
forward envelope is about 0.36 m. `TURTBOT_STOP_ENVELOPE_M` on the Pi backend can
increase it, within validated code bounds of 0.28–0.8 m. It cannot be disabled in
the UI; the explicit launcher override above bypasses it for manual operation.

The visible red **STOP MOTION** button and Space key stop this dashboard's commands.
They are **not a safety-rated hardware emergency stop**, cannot stop another
controller, and do not guarantee stopping after power/CPU/hardware failure.
The horizontal LiDAR misses drop-offs, stairs and objects above/below its plane.
Keep access private; the backend binds loopback and uses SSH, same-origin/host
checks and authenticated service APIs. Never expose unauthenticated controls to
public Wi-Fi. AI/model results have no control path.

## Mission and model workflow

- **Sensor snapshot / Capture frame:** save the current JPEG and time-matched
  camera/LiDAR/odometry metadata. Alignment is approximate (250 ms tolerance).
  Missing/stale sensors mark the capture partial. Snapshot history survives restart.
- **Save observation:** append a timestamped note with available pose/sensor context.
- **Mark POI:** record the current odometry pose with a note. Odom drifts and is not
  a map/global coordinate. The button requires fresh odometry.
- **Export mission ZIP:** download records, captures and current sensor metadata.
- **Record:** browser-local WebM video, limited to three minutes. Stop recording to
  download. This is operator video, not a scientifically synchronized dataset.
- **Enable mock detections:** draw a labeled synthetic box and placeholder alert.
  It performs no recognition. Capture interpretation is separately unconfigured.

Teammates: [models/README.md](models/README.md) documents versioned API v1.0,
exact-frame inputs, optional pose/LiDAR, bounding boxes, polygon masks and multiple
model streams. `models/example_client.py` is an executable external mock example.

## Mapping

SLAM Toolbox supports Humble, but is **not installed on this Pi**. No SLAM or
navigation process was installed/launched, and no persistent live map is claimed.
The bridge can consume an existing `/map` OccupancyGrid, display it, export it and
reopen saved grids. A reopened map is explicitly labeled saved, not live. Robot
odometry is not drawn on it without a verified map transform.
A future operator-guided mapping step needs the Humble package, verified
`map → odom → base_footprint → base_scan` transforms, timestamps and a low-rate
configuration suited to Pi 3. Do not add autonomous exploration as a demo shortcut.

## Recovery and logs

- Camera stale: wait for worker retry; inspect `.robot/runtime/camera-relay.log`.
  If another camera app owns the device, stop that known app, then restart. Do not
  launch a second capture program against `/dev/video0`.
- LiDAR missing: stop movement, inspect its USB cable and `/dev/ttyUSB0`. The
  supervisor will not blindly relaunch hardware. Correct the connection, inspect
  bringup logs and use a deliberate restart after checking for existing drivers.
- Ethernet/SSH lost: watchdog stops/disarms active control. Short interruptions may
  recover on the existing SSH connection. If the authenticated master expires,
  `start.sh` can prompt again; passwords are not cached for silent reauthentication.
- Backend crash: supervisor retries the app, preserving mission files and leaving
  motor control disarmed. Browser telemetry/video reconnect automatically.
- Any unhealthy state: `./scripts/diagnose.sh`, then `./scripts/restart.sh`.

Mac logs: `.robot/runtime/supervisor.log`, `.robot/runtime/camera-relay.log`.
Pi logs: `~/turtbot-dashboard/dashboard.log`, `bringup.log`.
Pi process state: `~/turtbot-dashboard/.runtime/pi-processes.json`.

```bash
tail -f .robot/runtime/camera-relay.log
ssh -o UserKnownHostsFile="$PWD/.robot/known_hosts" \
  'turtle@fe80::ba27:ebff:fe79:d40f%en9' \
  'tail -n 60 ~/turtbot-dashboard/dashboard.log'
```

## Tests and mock mode

```bash
.camera-venv/bin/python -m unittest \
  dashboard.tests.test_dashboard dashboard.tests.test_mission \
  dashboard.tests.test_startup camera.test_convert_raw10 \
  test_phase_a test_programming_tools test_opencr_interface

./scripts/stop.sh
./scripts/start.sh --mock              # Mac only; no Pi/ROS/hardware connection
./scripts/stop.sh
./scripts/start.sh                     # return to hardware
```

The mock camera is an illustration; LiDAR and telemetry are synthetic and labeled.
Movement stays disabled. Sixty automated tests passed at delivery. Physical motion,
real inference, optical latency and cable-unplug recovery remain separate tests.
Software process-failure recovery was tested with motion disabled; see the reports
under `diagnostics/mission/recovery-*.json`.
