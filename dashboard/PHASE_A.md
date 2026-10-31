# Phase A — live hardware verification

This phase observes existing ROS drivers and tests existing camera capture tools.
It does not launch TurtleBot/OpenCR/LiDAR drivers, install packages, change system
configuration, or publish motion commands. Dashboard implementation waits until
the findings and any hardware/software blockers are reported.

## Verified results

SSH login as `turtle` is verified over direct Ethernet at
`fe80::ba27:ebff:fe79:d40f%en9`. The live report is
`../diagnostics/phase_a/latest.json`: 71 valid scans at 5.009 Hz, odometry,
IMU and battery at approximately 20 Hz. Scan QoS is BEST_EFFORT/VOLATILE;
telemetry publishers use RELIABLE/VOLATILE. No velocity publisher was created.
One OpenCR and one LDS driver were present.

Camera Module 2 / IMX219 has no bound sensor or real image topic. Both CSI
interfaces report disabled. The kernel sensor module exists but is not loaded.
The user subsequently approved an IMX219 overlay and reboot. The module now loads,
but sensor chip-ID reading fails with I/O error -5, so acquisition remains blocked.
See camera_after_overlay.json in the report directory and README.md for the physical
check required next. No camera capture stack was selected or installed.

Rerun the read-only probe if needed:

```sh
cd /Users/coletriebold/Documents/Turtbot
python3 dashboard/diagnostics/run_phase_a.py
```

Keep the existing bringup running on the Pi. Do not start a second bringup.
If bringup is stopped, the probe reports missing data instead of starting it.
OpenCR must be connected to the Pi for Pi-side telemetry; a cable from OpenCR
to the Mac cannot simultaneously serve the Pi's driver.

The launcher sources the already installed `/opt/ros/humble/setup.bash`, retains
the account's existing domain/RMW settings, sets `TURTLEBOT3_MODEL=burger` only
for that process, and runs the probe from standard input without installing it.
It copies no passwords, keys, or configuration to the robot.

For a different Ethernet adapter or address:

```sh
python3 dashboard/diagnostics/run_phase_a.py \
  --target 'turtle@fe80::ba27:ebff:fe79:d40f%en9' --seconds 15
```

Use `--namespace NAME` only if the existing topics have a namespace. Credentials
are not command arguments or saved in the report. The launcher doesn't start a
long-lived authenticated session or change SSH authentication settings.

## Evidence collected

- Actual hostname, account, ROS environment, and serial-device permissions.
- Read-only process inventory to flag duplicate OpenCR or LiDAR drivers.
- `/scan`, `/odom`, `/imu`, and `/battery_state`: advertised types, publisher
  names, publisher QoS, received message counts, observed reception frequencies,
  last-message age, and latest data. Reception rates may be lower than source
  rates under load.
- LiDAR: actual distance array, bounds, scan angles, frame ID, source timestamp,
  finite/in-range return count, and nearest valid distance. Valid measurements
  require at least two valid scans and a fresh final sample.
- Existing `/cmd_vel` publishers, without creating a command publisher.
- Camera: existing ROS image publishers first, video-device names, installed
  camera tools, and camera enumeration. A direct still acquisition is attempted
  only if an already installed `rpicam`/`libcamera` enumeration detects a camera
  and a matching still tool is available. No camera driver is selected or
  installed automatically. An advertised image topic prevents a competing
  direct capture, even if its images are currently missing.

A successful still acquisition verifies one image, not video FPS or browser
streaming. Raw video device names alone do not prove camera compatibility.
Picamera2 availability is recorded, but the probe doesn't change camera stacks
or guess a V4L2 format. If only those interfaces are present, it reports that
further compatibility testing is needed.

## Results

The launcher saves `diagnostics/phase_a/latest.json`. A captured hardware JPEG
or PNG, if available, is saved beside the report with a unique timestamp.
Connection/authentication errors produce an explicitly blocked report, never
simulated measurements. Independent topic samples are **not** represented as a
synchronized perception snapshot.

After the report is available, review its blockers before moving to Phase B.
The next dashboard will be served locally by the Pi over Ethernet; it will not
be published to external hosting. Mock and hardware modes will be explicitly
separated. Physical movement testing still requires the user's explicit approval.
