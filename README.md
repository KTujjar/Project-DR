# Turtle SAR Mission Control

The existing dashboard is upgraded and running at http://127.0.0.1:8872 through
the private Ethernet SSH tunnel. Start with [OPERATOR.md](OPERATOR.md).

```bash
./scripts/start.sh
./scripts/status.sh
./scripts/restart.sh
./scripts/stop.sh
```

[Architecture](ARCHITECTURE.md) · [Measured performance](PERFORMANCE.md) ·
[Teammate model API](models/README.md) · [Changed files](MISSION_CHANGES.md).

Camera, LiDAR and telemetry are real. Mock detections are labeled. Physical driving
remains unvalidated: the approved wheel-test precheck was blocked by LiDAR gaps.
No autonomous movement or live SLAM was installed.

---

# TurtleBot3 connection tools

The Pi is connected and authenticated over direct Ethernet. Open the running
[live dashboard](http://127.0.0.1:8872) while the SSH tunnel is active.
Live LiDAR (~5 Hz), odometry, IMU, battery and wheel telemetry (~20 Hz) are verified.
The camera now captures a verified RAW10 frame; Mac-side JPEG conversion works.
Dashboard camera streaming is proposed but not integrated. Motion remains locked.
A LiDAR obstacle guard and expanded scan view are implemented. The guard awaits physical validation.

See [dashboard/README.md](dashboard/README.md) for installation, startup, camera
next steps and AI extension. [PROGRAMMING.md](PROGRAMMING.md) explains editing
Python programs on the Mac and running them on the Pi. Hardware evidence is in
[diagnostics/phase_a/latest.json](diagnostics/phase_a/latest.json).

## Working direct USB interface

The OpenCR connection was verified on October 30, 2026:

- Device: `/dev/cu.usbmodemFFFFFFFEFFFF1`
- Reported model: **Burger**; controller model `0x5000`; firmware version `5`
- Protocol: DYNAMIXEL 2.0, controller ID `200`, 1,000,000 baud
- Live battery voltage: approximately **12.17 V**
- Live IMU and wheel encoder data received; both wheel motors report connected
- No firmware was flashed and no wheel movement was commanded during setup

Run from this folder using the prepared virtual environment:

```sh
.venv/bin/python turtlectl.py usb status
.venv/bin/python turtlectl.py usb watch
.venv/bin/python turtlectl.py usb watch --json --count 10
```

The OpenCR is selected automatically. If more than one is attached, add
`--port /dev/cu.usbmodemFFFFFFFEFFFF1` after the action. Only one program can
open the port at a time; stop `watch` with Ctrl-C before running another command.
Sensor commands only send identification/read packets. Battery percentage is
the firmware's voltage-based estimate. Wheel position is in encoder ticks;
velocity and current are displayed in the firmware's raw motor units.
The readable monitor uses Eastern time; JSON timestamps use UTC.

Additional controls are available when you choose to run them:

```sh
# Play the firmware's connection melody.
.venv/bin/python turtlectl.py usb beep

# Clear USB linear and angular velocity commands.
.venv/bin/python turtlectl.py usb stop

# Physical motion: drive forward at 3 cm/s for one second, then send zero velocity.
.venv/bin/python turtlectl.py usb drive --linear 0.03 --seconds 1

# Physical motion: rotate at 0.2 rad/s for one second, then send zero velocity.
.venv/bin/python turtlectl.py usb drive --angular 0.2 --seconds 1
```

Place the robot on a clear, level surface before a drive command. Drives are
limited to 0.05 m/s, 0.5 rad/s, and two seconds per invocation. The interface
uses the firmware heartbeat watchdog and sends zero velocity on completion,
Ctrl-C, or an exception when communication remains available. The firmware
clears USB velocity after approximately 500 ms without changing heartbeats.
The tool refuses motion if debug mode disables that timeout. It does not change
motor torque settings. `stop` clears commands from USB; it does not cancel the
board's button-test or RC100 commands and is not a hardware emergency stop.

Sensor reads have been tested on the physical controller. Drive cleanup paths
have been tested with a simulated controller; **physical driving and the buzzer
have not been tested**. Lidar and camera data remain connected to the Pi and
are not available through this OpenCR connection.

To recreate the Python environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## Connect through the Pi for full ROS features

The normal connection is **Mac → Wi-Fi/Ethernet → Raspberry Pi → USB → OpenCR**.
The Pi also connects to the lidar and any camera. Plugging a Mac into an ordinary
USB host port on the Pi does not create a network or ROS connection. USB gadget
mode requires separate, model-specific setup and is not assumed here.

Use the robot's existing software first. There is no need to install ROS on the
Mac to use the SSH interface below. The robot needs to be booted, have a working
OS and ROS installation, and be reachable over the network. Keep the OpenCR's
micro-USB connection to the Pi for normal robot operation.

## Get the Pi's address

Connect the Pi and Mac to the same reachable network. If a monitor and keyboard
are available on the Pi, run `hostname -I` there. Alternatively, look for the Pi
in your own router's connected-device list. A configured hostname such as
`turtlebot3.local` may work, but the hostname is not guaranteed. Use the Pi's
actual username; `ubuntu` is used in the examples only.

## Interface from this folder

```sh
python3 turtlectl.py doctor
python3 turtlectl.py inspect ubuntu@192.168.1.42
python3 turtlectl.py topics ubuntu@192.168.1.42
python3 turtlectl.py nodes ubuntu@192.168.1.42
python3 turtlectl.py services ubuntu@192.168.1.42
python3 turtlectl.py actions ubuntu@192.168.1.42
```

Replace the example IP with the Pi's actual IP. SSH uses its normal host-key
verification and prompts for your Pi credentials in the terminal. No credentials
are saved by this tool. `inspect` does not start ROS, robot drivers, or motion.
The other commands use the Pi's existing ROS shell configuration; if there is
exactly one ROS distribution in `/opt/ros`, they can source it automatically.

If the workspace is not sourced, use the paths reported by `inspect`:

```sh
python3 turtlectl.py topics ubuntu@192.168.1.42 \
  --distro humble --setup /home/ubuntu/turtlebot3_ws/install/setup.bash
```

Use the distribution and setup file actually installed on the Pi. The tool
supports ROS 1 and ROS 2 topic inspection. Listing actions requires ROS 2.

## Read robot features

Choose exact names from `topics`; names can differ with a robot namespace and
installed hardware. Typical topics include `/scan` (lidar), `/imu`, `/odom`,
`/battery_state`, and camera topics if a camera and driver are installed.

```sh
python3 turtlectl.py read ubuntu@192.168.1.42 /battery_state
python3 turtlectl.py read ubuntu@192.168.1.42 /imu
python3 turtlectl.py hz ubuntu@192.168.1.42 /scan
python3 turtlectl.py shell ubuntu@192.168.1.42
```

Reading waits for a message; Ctrl-C stops it if the topic has no data. An empty
topic list can mean bringup is not running, the wrong ROS environment/domain is
selected, or the hardware is disconnected. The shell command opens a normal
terminal on the Pi for further setup. These inspection commands do not publish
velocity commands, invoke services, or send navigation goals.

For driving and graphical sensor viewing, first identify the actual Burger/
Waffle variant, ROS version, and available topics on the Pi. TurtleBot3 Jazzy
uses `geometry_msgs/msg/TwistStamped` for `/cmd_vel` by default; earlier versions
commonly use `Twist`. Inspect the actual topic type before building controls.
RViz is for visualizing live ROS data. Gazebo is for simulation, with a version
matched to the chosen ROS distribution. A camera image viewer, RViz, or browser
dashboard is a subsequent step once the real connection is verified.

## Initial network and Gazebo findings

- Mac: Apple Silicon; no local ROS command found.
- The original USB cable went to the Pi. Moving it to OpenCR established the
  working direct USB connection documented above.
- Gazebo components are installed, but `gz sim` is unavailable. The
  `gz-sim10/10.5.0_15` installation directory is empty.
- The network sweep of `172.27.160.0/20` found no reachable SSH server or match
  for the provided MAC `b8:27:eb:2c:81:5a`. That earlier sweep was superseded by the successful direct Ethernet connection.

## Official references

- [TurtleBot3 bringup and SSH](https://emanual.robotis.com/docs/en/platform/turtlebot3/bringup/)
- [OpenCR-to-Pi USB connection](https://emanual.robotis.com/docs/en/platform/turtlebot3/opencr_setup/)
- [TurtleBot3 ROS and PC setup](https://emanual.robotis.com/docs/en/platform/turtlebot3/quick-start/)
- [ROS/Gazebo version compatibility](https://gazebosim.org/docs/latest/ros_installation/)
- [OpenCR TurtleBot3 ROS 2 firmware and register map](https://github.com/ROBOTIS-GIT/OpenCR/blob/master/arduino/opencr_arduino/opencr/libraries/turtlebot3_ros2/src/turtlebot3/turtlebot3.cpp)

## Camera raw capture conversion

The camera now produces a verified raw frame. [camera/README.md](camera/README.md)
contains the Mac-side RAW10-to-JPEG utility, exact scp command, dependencies,
validation results and a streaming proposal that preserves the existing setup.
No capture configuration or ROS process was changed for this conversion.
