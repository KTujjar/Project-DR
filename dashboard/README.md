# Current mission application

Use [../OPERATOR.md](../OPERATOR.md) for the complete launcher, recovery and safety
workflow. The live camera now uses the Pi hardware ISP/MJPEG pipeline with a raw/Mac
fallback. This document below retains the earlier component-level setup/history.

# TurtleBot Observatory

Pi-hosted browser dashboard for turtle19 (Burger, ROS 2 Humble). Live raw LiDAR,
odometry, IMU, wheel rates and battery are verified. Camera Module 2 / IMX219
now captures a verified 3280×2464 pRAA raw frame through the existing V4L2 setup.
Mac-side JPEG conversion is validated; live dashboard streaming is not yet integrated.
See [../camera/README.md](../camera/README.md). Driving remains unverified and locked.

## Open the running dashboard

On this Mac, open http://127.0.0.1:8872 while the Ethernet SSH tunnel is active.
The Pi serves only its own loopback address; the encrypted SSH tunnel carries
browser traffic. No ROS installation on the Mac is needed.

The app was installed at `/home/turtle/turtbot-dashboard`. It is a user process,
not a boot service. A reboot stops it. It never starts robot drivers.

To restart it from a Pi terminal after the existing bringup is running:

```bash
cd ~/turtbot-dashboard
TURTBOT_ALLOW_MOTION=0 bash dashboard/start.sh hardware
```

In another Mac terminal, open a tunnel (stop an older tunnel first if port 8872
is already occupied):

```bash
cd /Users/coletriebold/Documents/Turtbot
bash dashboard/connect.sh
```

SSH asks for the Pi account's password when needed. Passwords are never saved.
The `%en9` zone selects this Mac's Ethernet adapter; change `TURTBOT_TARGET` if
using a different adapter. Keep the tunnel terminal open. Ctrl-C closes it.

The background process created during setup records its PID in
`~/turtbot-dashboard/dashboard.pid` and its output in `dashboard.log`.
Check the PID's command before stopping it; do not stop the existing bringup.
To stop that app process on the Pi: `kill "$(cat dashboard.pid)"` from its folder.

## Install / mock development

On the Pi, the isolated virtual environment inherits ROS system packages.
The prepared `wheelhouse/` contains Python 3.10 aarch64 dependencies so no Pi
Internet connection, apt change or ROS replacement is needed:

```bash
cd ~/turtbot-dashboard
bash dashboard/install-offline.sh
```

For a fresh development environment with Internet access:

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r dashboard/requirements.txt
TURTBOT_PORT=8871 bash dashboard/start.sh mock
```

Mock mode always labels simulated data and disables movement. Hardware mode
requires the Pi's existing Humble installation and running bringup. It never
falls back to simulated data. Startup sets domain 30 and Fast DDS unless the
process environment already specifies alternatives. Set `TURTBOT_NAMESPACE`
only for an actual robot topic namespace. No firmware is flashed.

## Interface and safety

The LiDAR view shows raw current `/scan` ranges, range circles, robot-forward
orientation, zoom, fit, pause and JSON export. It is not a persistent SLAM map.
Use Expand view for a full-window plot and the 0.5–6 m zoom range for closer inspection.
The renderer uses the screen pixel density; the LDS-01 itself remains a 2D, 1-degree,
roughly 5 Hz sensor. The footer reports actual scan geometry and received frequency.
Telemetry freshness and rates come from actual message receipts. Pausing the
plot leaves ingestion and diagnostics active. Camera status stays unavailable
until actual images decode successfully. The dashboard can subscribe to an
existing ROS Image or CompressedImage publisher; use `TURTBOT_CAMERA_TOPIC` to
select one explicitly. It never launches a competing camera driver.

Motion is disabled in the server by default and remains disabled on this Pi.
Implementation includes explicit browser arming, exclusive ownership, publisher
conflict checks, release/blur/disconnect stops, and a ROS timer watchdog. Server
caps are 0.08 m/s and 0.5 rad/s; command expiry is 250 ms and heartbeat expiry
600 ms. Enabling and physical validation require the user's explicit approval.
No movement or real stopping-distance test has been performed. The browser Stop
button only cancels this dashboard's commands and is not a hardware emergency stop.

## Captures and AI extension

`POST /api/snapshots` stores a JSON capture and an image when available under
`dashboard/data/`. Alignment selects nearest recorded sensor header timestamps
within 250 ms; it is approximate, not hardware triggered. Missing or stale camera,
scan or odometry makes the capture partial. Pi header timestamps are used for
alignment; receipt age uses a monotonic clock. Capture files can reveal surroundings.

`backend/ai.py` contains independent async adapters. A real adapter should accept
capture data, call a chosen inference service and return `status`, `title`, `text`
and `source`. Configure secrets through environment variables. No model or API key
is configured. The hardware adapter reports that fact; mock interpretations are
explicit demonstrations. AI has no reference to motor control. No capture is
sent to an external service by the current implementation.

## Source layout and programming

- `backend/ros_bridge.py`: existing ROS subscriptions, image decoding and watchdog.
- `backend/safety.py`: ownership, limits, expiry and stop behavior.
- `backend/state.py`: telemetry histories, freshness and capture alignment.
- `backend/app.py`: HTTP, WebSocket, snapshots and local static assets.
- `static/`: responsive, buildless HTML/CSS/JavaScript interface.
- `diagnostics/`: read-only Phase A probe and camera inventory.
- `tests/`: API, provenance and simulated safety behavior.

Edit these files on the Mac, copy the changed dashboard sources into the Pi's
app folder over SSH, then restart only the dashboard. For separate ROS Python
programs and the upload/run helper, see [../PROGRAMMING.md](../PROGRAMMING.md).
The existing `programs/ros2_sensor_report.py` is a read-only subscriber example.

## LiDAR obstacle guard

`backend/obstacle_guard.py` vetoes this dashboard's nonzero commands before ROS
publication and from the ROS timer watchdog. It requires a fresh scan (at most
500 ms old), the verified `base_scan` frame, and usable directional coverage.
Invalid readings and missing scan sectors are unknown space, never clear space.

The prototype uses a conservative 0.30 m circular envelope measured from the
scanner (footprint/offset allowance plus margin), with extra clearance for speed:
`0.30 + abs(linear)*0.6 + linear**2/0.4` meters. Front/rear motion checks a 140°
sector; turns and curved commands check the full circle. Coverage must span the
required sector, have at least 85% valid measurements, and contain no unknown gap
over 12°. These assumptions need measured robot calibration and physical stopping
validation. A veto sends zero and disarms; clearing an obstacle does not resume
motion automatically. The live panel shows direction-specific veto reasons.

This is an unvalidated protective aid, not crash prevention or a hardware emergency
stop. It only filters dashboard commands, not another ROS publisher or controller.
The 2D plane cannot detect drop-offs or obstacles above/below the scanner, and some
surfaces may not yield usable returns. No physical driving test was performed.
Controls remain locked until the user approves supervised elevated-wheel tests.

## Camera setup history (superseded by successful raw capture)

The chip-ID failure below was an earlier observation. A subsequent user capture
and read-only inventory confirm the sensor is now linked to Unicam and produces
a valid raw frame; no further physical camera repair is inferred from the old error.
The live app may retain the old message until its camera integration is updated.

The user approved the boot configuration backup, overlay change and reboot.
Backup on the Pi:
`/boot/firmware/config.txt.before-imx219-20261031T005745Z`.
The original `camera_auto_detect=1` is now `camera_auto_detect=0` followed by
`dtoverlay=imx219` in `[all]`. Reboot verified by a changed Linux boot ID.
No camera package was installed, and existing ROS/drivers were preserved.

The camera kernel module now loads, but dmesg reports:

```text
imx219 10-0010: failed to read chip id 219
imx219: probe of 10-0010 failed with error -5
```

The I2C device declaration exists but has no bound driver or image device. It is
not evidence of a working sensor. Next, shut down the Pi and disconnect power,
then check both ends of the ribbon for full insertion, latch closure, correct
contact orientation and connection to the CSI CAMERA connector, rather than DSI
DISPLAY. A faulty cable/sensor or a different actual sensor model remains possible.
Do not reconnect the camera ribbon while powered. After the physical check, boot
and inspect sensor binding before choosing capture software for Ubuntu 22.04.
Hardware evidence is `../diagnostics/phase_a/camera_after_overlay.json`.

The existing bringup was stopped by the reboot. It was restored once after
verifying neither hardware driver was running. Current setup logs/PIDs are
`bringup.log` / `bringup.pid` in the Pi app directory. Dashboard movement remains
disabled; no velocity command was published during restoration.

References: [ROBOTIS LDS-01 specifications](https://emanual.robotis.com/docs/en/platform/turtlebot3/appendix_lds_01/),
[Raspberry Pi camera overlays](https://www.raspberrypi.com/documentation/accessories/camera-software.html).
