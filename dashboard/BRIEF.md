Build a polished, browser-based TurtleBot3 Control and Perception Dashboard that I can access from my MacBook over Ethernet.
The following information was verified through successful terminal commands on the Raspberry Pi:
- Hostname: turtle19
- Username: turtle
- ROS distribution: ROS 2 Humble
- Robot model: TurtleBot3 Burger
- LiDAR model: LDS-01
- LiDAR port: /dev/ttyUSB0
- LiDAR ROS package: hls_lfcd_lds_driver
- OpenCR port: /dev/ttyACM0
- TurtleBot packages installed: turtlebot3, turtlebot3_bringup, turtlebot3_node, turtlebot3_msgs, turtlebot3_teleop, and others
- Additional Raspberry Pi camera module connected, not yet tested
The following commands successfully launched the existing robot drivers:
```bash
source /opt/ros/humble/setup.bash
export TURTLEBOT3_MODEL=burger
ros2 launch turtlebot3_bringup robot.launch.py
```
The logs confirmed:
- hlds_laser_publisher started on /dev/ttyUSB0, using frame base_scan.
- turtlebot3_node successfully opened /dev/ttyACM0.
- Gyro calibration completed.
- Motors and wheels were initialized.
- Battery, IMU, sensor state, and joint state publishers were created.
- Differential-drive odometry initialized successfully.
The /scan topic and its actual range measurements have not yet been verified after bringup.
Create a system that runs on the Raspberry Pi and exposes a modern GUI accessible from my MacBook's web browser.
The interface should have four major areas:
1. Robot control
- WASD or arrow-key driving.
- On-screen directional controls.
- Adjustable speed limits.
- Live motor/odometry information.
- Prominent stop control.
- Require explicit arming before allowing movement.
- Automatic zero-velocity command on control release, heartbeat timeout, lost browser connection, or application shutdown.
- Avoid conflicting motor control publishers.
2. Live LiDAR visualization
- Subscribe to ROS topic /scan using sensor_msgs/msg/LaserScan.
- Display live, top-down, 360-degree distance measurements.
- Include range circles, robot orientation, obstacle points, and adjustable zoom.
- Show LiDAR update frequency and diagnostic status.
- Handle missing, invalid, or disconnected sensor data.
- Eventually support persistent 2D mapping using SLAM, but prioritize live raw scans first.
3. Raspberry Pi camera
- Detect the newly installed camera module.
- Identify the compatible camera driver and interface.
- Show live video in the browser.
- Allow snapshots.
- Display stream status, resolution, and frame rate.
- Avoid unnecessary camera-driver reinstalls.
4. AI perception
- Create an extensible pipeline combining camera frames, LiDAR data, odometry, and timestamps.
- Provide a button to capture a synchronized sensor snapshot.
- Support future integration with a vision-language AI model.
- Display AI interpretations in a separate panel.
- Keep AI analysis entirely separate from movement commands initially.
- Allow mock AI responses until a model is configured.
Prefer:
- Python ROS 2 node using rclpy for robot communications.
- FastAPI backend with WebSockets.
- Responsive React frontend or another lightweight, polished browser UI.
- Existing ROS driver packages for hardware.
- Optional separate AI inference service.
- Browser access from macOS without installing ROS locally.
Keep the architecture modular and understandable.
1. Do not reinstall ROS, reflash the SD card, or replace existing working TurtleBot drivers.
2. Use the existing turtlebot3_bringup system.
3. Verify /scan actually publishes valid measurements before declaring LiDAR functional.
4. Test camera compatibility before selecting its software driver.
5. Build a working dashboard using mock data before connecting real hardware.
6. Keep wheel movement disabled by default.
7. Require my explicit approval before any physical movement test.
8. Do not start multiple instances of the OpenCR or LiDAR drivers.
9. Implement timeouts and safe stopping in the ROS control node itself, not only in JavaScript.
10. Keep commands limited to conservative Burger speed limits.
11. Make the interface resilient to network disconnects.
12. Do not hardcode credentials or API keys.
13. Provide straightforward commands for starting everything and accessing the dashboard from my Mac.
14. Never confuse a simulated sensor with a verified hardware sensor.
Phase A: Verify ROS
Confirm that /scan, /odom, /imu, and battery topics are publishing. Inspect topic types, QoS settings, and sensor frequencies. Detect the camera and test image acquisition.
Phase B: Mock dashboard
Build the GUI with simulated LiDAR points, placeholder camera images, dummy telemetry, and disabled movement controls.
Phase C: Real sensor integration
Replace mocked LiDAR and telemetry with actual ROS subscriptions. Integrate the real camera feed.
Phase D: Manual robot control
Implement safe /cmd_vel publishing, controls, watchdogs, and arm/disarm behavior. Test with wheels elevated after obtaining approval.
Phase E: AI integration
Implement a sensor snapshot API and an optional AI interpretation adapter.
- Working project source code.
- Clear folder structure.
- Installation and launch instructions.
- Startup script that sources ROS 2 Humble and sets the correct environment variables.
- Responsive browser dashboard.
- Diagnostic status panel.
- Mock-data mode.
- Real LiDAR display.
- Camera feed if hardware is compatible.
- Manual driving after safety validation.
- Documentation for future AI integration.
Start by inspecting the existing environment and implementing Phase A. Report any hardware or software blockers before proceeding. Do not change system configuration or move the robot without approval.
Our priority is getting a beautiful, functional live LiDAR and camera dashboard first. Robot control comes second, and AI integration comes third.