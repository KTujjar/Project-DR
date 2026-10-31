# Programming your TurtleBot

## Ethernet connection found

The directly connected Pi is reachable at:

```text
fe80::ba27:ebff:fe79:d40f%en9
```

The `%en9` selects this Mac's Ethernet adapter and is required for this link-local
IPv6 address. No router, DHCP server, or static IPv4 configuration is needed.
The Pi's Ethernet MAC is `b8:27:eb:79:d4:0f`. Its SSH server identifies itself as
OpenSSH 8.9 on Ubuntu. The host key is saved in `.robot/known_hosts` in this
project, separately from your global SSH settings.

SSH login as `turtle` is verified. The Pi runs Ubuntu 22.04.5 and ROS 2 Humble,
with domain 30 and `rmw_fastrtps_cpp`. The existing drivers publish live LiDAR,
odometry, IMU and battery data. No password is saved in this project. After
plugging into a different adapter, the `%en9` suffix may change.

The browser dashboard and its startup instructions are in
[dashboard/README.md](dashboard/README.md). It subscribes to the existing bringup.

## First login and inspection

```sh
python3 turtlectl.py shell turtle@fe80::ba27:ebff:fe79:d40f%en9
python3 turtlectl.py inspect turtle@fe80::ba27:ebff:fe79:d40f%en9
python3 turtlectl.py topics turtle@fe80::ba27:ebff:fe79:d40f%en9
```

SSH prompts for credentials privately in the terminal. The tools do not save
passwords. `inspect` reads the installed software and device information. It
does not install anything or launch robot drivers.

For full robot operation, the OpenCR's micro-USB cable must connect **to the
Pi**, and the lidar must be connected to the Pi. When OpenCR is plugged into
the Mac instead, use the direct USB programming path described below. Its one
USB port cannot simultaneously serve both computers.

## Edit on the Mac, execute on the Pi

Start with [programs/ros2_sensor_report.py](programs/ros2_sensor_report.py).
It is a small ROS 2 Python program that listens to battery, IMU, and lidar
messages and prints a report. It does not publish commands or move the robot.

After login and ROS 2 have been verified:

1. Edit or add Python files in `programs/` using your editor.
2. Upload the programs:

   ```sh
   python3 turtlectl.py deploy turtle@fe80::ba27:ebff:fe79:d40f%en9
   ```

3. Run your program on the Pi:

   ```sh
   python3 turtlectl.py run turtle@fe80::ba27:ebff:fe79:d40f%en9 ros2_sensor_report.py --seconds 30
   ```

The upload copies `.py` and `.md` files from `programs/` into the dedicated
`~/turtbot_programs` directory. It replaces files of the same name there,
does not delete other files, and does not copy credentials or the Mac's Python
environment. Running uses the Pi's Python and existing ROS shell configuration.
Ctrl-C ends a program through the SSH terminal.

If inspection finds the ROS workspace is not already sourced, specify its
actual installed distribution and setup file **before the program name**:

```sh
python3 turtlectl.py run turtle@fe80::ba27:ebff:fe79:d40f%en9 \
  --distro humble --setup /home/turtle/turtlebot3_ws/install/setup.bash \
  ros2_sensor_report.py --seconds 30
```

`humble` is verified. The workspace setup path above is only an example; use an existing path from inspection. For standard installed TurtleBot messages, sourcing `/opt/ros/humble/setup.bash` is sufficient.
For a robot namespace, append `--namespace NAME` to the sensor program. Use
`topics` to confirm its actual topic names and that drivers are publishing.
The dashboard ROS runtime is verified. The separate deploy/run helper has unit coverage; its end-to-end upload example has not been rerun during dashboard setup.

## Program the base directly over USB now

The earlier direct OpenCR connection already works independently of Pi login.
With OpenCR connected to your Mac, you can use its Python API from this folder:

```python
from opencr_interface import OpenCR

robot = OpenCR()
try:
    state = robot.snapshot()
    print(state["battery"])
    print(state["imu"])
    print(state["wheels"])
finally:
    robot.close()
```

Run this using `.venv/bin/python your_program.py`. `OpenCR.snapshot()` is
read-only. The existing `drive_for(robot, linear, angular, seconds)` function
supports brief bounded motor commands; it commands physical movement, so start
with the sensor example. See README.md for the exact limits and available USB
commands. No native ROS installation on the Mac is required for either the
SSH workflow or this direct USB API.

## References

- [ROBOTIS TurtleBot3 bringup](https://emanual.robotis.com/docs/en/platform/turtlebot3/bringup/)
- [ROBOTIS onboard computer setup](https://emanual.robotis.com/docs/en/platform/turtlebot3/sbc_setup/)
- [ROS 2 Python subscriber example](https://github.com/ros2/examples/blob/humble/rclpy/topics/minimal_subscriber/examples_rclpy_minimal_subscriber/subscriber_member_function.py)
