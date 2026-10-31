We have a working TurtleBot3 Burger with ROS 2 Humble, LiDAR, OpenCR, and a functioning Raspberry Pi CSI camera.
I want you to upgrade our existing project into a reliable, real-time, browser-based Search and Rescue Robot Mission Control application.
This is a 12-hour hackathon project. Prioritize getting the system working, avoiding unnecessary complexity, and delivering an excellent live demonstration.
The immediate priorities are:
1. Achieve the best reasonably possible low-latency live video stream from the Raspberry Pi camera to my MacBook.
2. Restore and improve our existing robot dashboard.
3. Establish a reliable, repeatable startup and restart process.
4. Integrate the live camera, LiDAR, odometry, and robot controls.
5. Build a clean, modular interface for future machine-learning models developed by my teammates.
6. Add search-and-rescue functionality using our existing hardware.
Do not rewrite working code unnecessarily. Inspect the existing repository first.
Robot: TurtleBot3 Burger
Onboard computer:
- Raspberry Pi 3 Model B Rev 1.2
- Ubuntu 22.04.5 LTS
- ROS 2 Humble
- SSH username: turtle
- Hostname: turtle19
- Existing connection: Ethernet to my MacBook
- Previous successful SSH connection used IPv6 link-local address fe80::ba27:ebff:fe79:d40f%en9
LiDAR:
- LDS-01
- /dev/ttyUSB0
- Existing ROS driver: hls_lfcd_lds_driver
OpenCR:
- /dev/ttyACM0
- Existing turtlebot3_node initializes successfully
Camera:
- Sony IMX219 CSI camera
- V4L2 Unicam interface /dev/video0
- Successfully captured 3280×2464 packed RAW10 RGGB images.
- pRAA format, 4128 bytes per row.
- Existing converter: camera/convert_raw10.py
- Existing camera documentation: camera/README.md
- Existing requirements: camera/requirements.txt
- Eight converter tests passing.
- A full-resolution JPEG was produced successfully.
Existing image quality issue:
- Camera image was underexposed.
- Existing conversion required +3.61 EV compensation.
- Colors and white balance are approximate.
- Investigate sensor exposure and gain before relying on software brightening.
Existing ROS launch command:
```bash
source /opt/ros/humble/setup.bash
export TURTLEBOT3_MODEL=burger
ros2 launch turtlebot3_bringup robot.launch.py
```
This previously initialized the robot's motor interface, IMU, battery telemetry, and LiDAR driver successfully. Verify live topic data rather than assuming all sensors are working.
First, inspect the repository at:
/Users/coletriebold/Documents/Turtbot
Locate:
- Current dashboard implementation.
- Existing backend and frontend.
- ROS bridge code.
- Existing camera converter.
- Tests and dependencies.
- Current launch and shutdown scripts.
- SSH connectivity utilities.
- Any existing safety mechanisms.
Identify which components already work and which are incomplete.
Do not create a second independent dashboard if an existing dashboard can be extended.
Report the current architecture and propose the smallest changes needed.
This is the highest priority.
Deliver the best practically achievable live camera stream from the Raspberry Pi 3 to the MacBook dashboard.
Optimize for:
- Low latency.
- Smooth motion.
- Reliable operation.
- Adequate image quality for later computer-vision inference.
- Minimal CPU burden on the Pi.
- Sustainable bandwidth usage.
Investigate available hardware and software capabilities:
1. Supported IMX219 camera modes and frame rates.
2. V4L2 streaming capabilities.
3. Existing Raspberry Pi image-processing hardware.
4. Available and compatible libcamera implementations.
5. GStreamer, FFmpeg, or direct V4L2 options.
6. Available H.264 hardware-encoding support.
7. Whether a lightweight camera processing service can run without upgrading the operating system.
8. Whether using the MacBook for image processing is more efficient.
Important: Do not assume that video codec devices automatically provide a working camera-to-H.264 pipeline.
Do not install a major new camera stack or change kernel/boot configurations without first demonstrating why it is needed.
Choose the best working solution, not the most theoretically sophisticated one.
Preferred approaches, in order of proven compatibility and performance:
A. Camera capture with hardware-assisted image processing and compressed streaming.
B. Compatible GStreamer or FFmpeg capture/encoding pipeline.
C. Optimized raw Bayer capture with processing and encoding on the MacBook.
D. A simpler fallback stream if other approaches prove incompatible.
Our previous full-resolution raw-frame transfer method is a fallback, not the desired final solution.
Benchmark several possible modes, where supported:
- 640×480
- 1280×720
- Other sensor-native modes if more appropriate
Target 15–30 fps if sustainable, but do not sacrifice stability for an arbitrary target.
Accept a stable 5–10 fps if that is the best practical result.
Measure:
- Actual delivered FPS.
- End-to-end latency.
- CPU usage on the Pi.
- RAM consumption.
- Network bandwidth.
- Dropped frames.
- Stream recovery after connection loss.
Do not report estimated FPS as measured FPS.
Investigate why the captured image required +3.61 EV of brightening.
Where supported, configure:
- Sensor exposure time.
- Analog gain.
- Automatic exposure.
- White balance.
- Image brightness and contrast.
- Resolution and frame rate.
Prefer improving image quality at acquisition instead of amplifying dark images afterward.
A live camera panel that opens in the MacBook dashboard and streams continuously with FPS, latency, and connection status indicators.
Restore the existing dashboard and upgrade it into a unified search-and-rescue operator interface.
Use a professional dark interface with a layout suitable for field robotics.
Camera view
- Largest panel.
- Low-latency video.
- Full-screen option.
- Snapshot button.
- Recording controls if feasible.
- FPS, resolution, and latency indicators.
- Overlay support for future ML detections.
LiDAR view
- Live 360-degree scan.
- Correct polar geometry and distance scales.
- Robot orientation.
- Clear nearby obstacle visualization.
- Adjustable zoom.
- Sensor update rate.
- Option for a persistent SLAM map later.
Robot controls
- WASD / arrow-key steering.
- On-screen directional controls.
- Adjustable linear and angular velocity.
- Arm/disarm control.
- Stop button.
- Speed limitations.
- Connection-loss safety stop.
Telemetry
- Battery voltage.
- Robot orientation.
- Odometry.
- Current commanded velocity.
- Sensor connection status.
- CPU load and temperature.
- Wi-Fi/Ethernet connection status.
- Last received sensor timestamps.
Mission events
- Timestamped event log.
- Operator annotations.
- Snapshot history.
- Placeholder detection alerts.
- Exportable mission data.
The system should be easy to start, stop, and recover during a live hackathon demonstration.
I do not want to manually run five commands in separate terminal windows whenever something crashes.
Create a simple operator workflow for starting the entire application.
Prefer a Mac-side launcher script that:
1. Checks SSH connectivity to the Pi.
2. Confirms the existing ROS environment.
3. Starts or verifies the ROS bringup process.
4. Starts or verifies the camera service.
5. Starts or verifies the dashboard backend.
6. Opens the dashboard automatically in my MacBook's browser.
7. Prints clear diagnostic information.
Use the existing connection mechanism, including the configured SSH known-hosts file where applicable.
Provide commands or scripts such as:
```bash
./scripts/start.sh
./scripts/status.sh
./scripts/stop.sh
./scripts/restart.sh
```
Implement these commands for the actual architecture; don't create placeholder scripts.
- Detect crashed services.
- Automatically restart non-motion-critical services where appropriate.
- Avoid duplicate ROS bringup instances.
- Avoid competing serial-device access.
- Detect disconnected cameras and LiDAR.
- Handle lost SSH or Ethernet connections.
- Reconnect WebSocket streams automatically.
- Log errors to accessible locations.
- Clearly display degraded operation.
- Do not automatically resume physical movement after a crash or restart.
Consider systemd for Raspberry Pi services and a separate MacBook launcher for the dashboard.
Use service dependencies and sensible restart policies.
Avoid automatically restarting hardware drivers repeatedly if a restart could interfere with robot safety.
Provide a concise operator README covering:
- First-time installation.
- How to launch the complete system.
- How to reopen the dashboard.
- How to stop the robot.
- How to restart after a crash.
- How to recover if the camera stops streaming.
- How to recover if the LiDAR disappears.
- How to view logs.
- How to test whether everything is healthy.
Include a one-command diagnostic tool.
Build toward a search-and-rescue demonstrator, not a fully autonomous deployment-ready rescue system.
Allow the operator to control the robot safely while watching the live camera and LiDAR.
Prioritize responsiveness and safe stopping.
Use real LiDAR distance measurements to:
- Detect nearby obstacles.
- Display the closest obstacle.
- Warn about collision risk.
- Implement configurable forward-motion safety limits where reliable.
Do not assume this 2D LiDAR detects stairs, drop-offs, low obstacles, or overhanging hazards.
Investigate compatibility with ROS 2 SLAM Toolbox.
If practical, support:
- Building a 2D occupancy map.
- Displaying the map in the dashboard.
- Showing the robot's estimated location.
- Saving and reopening maps.
Initially support operator-guided mapping; autonomous exploration is optional.
Allow the operator to:
- Mark points of interest.
- Capture photos.
- Record timestamps.
- Add notes.
- Export observations.
Connect these observations with robot pose and sensor timestamps when available.
My teammates are developing computer-vision models to recognize specific features.
Do not implement their models yet.
Instead, create a stable model integration interface supporting:
Input:
- Camera frame.
- Frame timestamp.
- Optional LiDAR scan.
- Optional robot pose.
- Sensor calibration metadata where available.
Output:
- Detection label.
- Confidence.
- Bounding box or segmentation mask.
- Timestamp.
- Optional additional metadata.
Allow external model services to run on the MacBook or another machine without requiring inference on the Pi.
Support multiple model outputs through a documented, versioned API.
Render bounding boxes and labels on the live video.
Include a mock detector for end-to-end testing.
Do not let unvalidated ML outputs directly control the robot.
The robot must be safe to operate indoors during development.
Implement:
- Disarmed state by default.
- Explicit operator arming.
- Conservative speed limits.
- Acceleration limits.
- Command timeout watchdog running independently of browser code.
- Zero-velocity command on lost heartbeat.
- Zero-velocity command on keyboard release.
- Zero-velocity command on connection failure.
- Emergency stop control.
- No automatic re-arming after a restart.
- No movement during installation or diagnostics.
The software stop must not be described as a safety-rated hardware emergency stop.
Do not operate autonomous movement without explicit approval.
For initial motor testing, require the wheels to be elevated and the operator physically present.
Restrict control access to the trusted MacBook-to-Pi connection. Do not expose unauthenticated movement controls to public Wi-Fi.
- Preserve the existing repository and working camera converter.
- Keep hardware drivers separate from dashboard logic.
- Reuse ROS 2 Humble and existing TurtleBot packages.
- Use a dedicated ROS bridge.
- Keep streaming and ML inference independent.
- Avoid unnecessary dependencies.
- Respect Pi 3 memory and CPU limits.
- Add tests for camera processing and backend control logic.
- Provide simulation/mock modes.
- Track service health and data freshness.
- Handle camera and network failures gracefully.
- Use environment variables for configuration.
- Never hardcode credentials.
Execute in the following order:
1. Audit the existing project.
2. Verify live LiDAR and robot telemetry.
3. Benchmark available camera streaming paths.
4. Implement the best stable camera stream.
5. Reopen the existing dashboard with live video.
6. Add robust startup, shutdown, and restart scripts.
7. Integrate live LiDAR and telemetry.
8. Integrate safe manual control.
9. Add obstacle awareness.
10. Add mapping if feasible.
11. Implement mock ML detection overlays and API.
Do not spend the entire development time researching theoretical optimizations.
Prefer a working, measurable implementation with graceful fallbacks.
After each major phase, run tests and report results.
The MVP should demonstrate:
- Dashboard opens from my MacBook.
- Live camera feed is visible with measured FPS and latency.
- Live LiDAR measurements are displayed.
- Battery, IMU, and odometry data appear when available.
- Robot responds to manually approved control commands.
- Robot stops when operator input ends or connectivity is lost.
- At least one mission snapshot can be saved with metadata.
- Mock ML detections render over the camera feed.
- Services can be restarted without reflashing or reinstalling the Pi.
- The complete demo can be relaunched using simple documented commands.
At completion, provide:
1. Files added and modified.
2. Architecture summary.
3. Exact commands to launch the system.
4. Exact commands to restart after a crash.
5. Dashboard URL.
6. Measured video performance.
7. Known limitations.
8. Verified hardware features versus mocked features.
9. Clear instructions for teammates to integrate their ML models.
Proceed autonomously on ordinary code development and non-destructive testing.
Ask before changing system-level camera configuration, installing major hardware drivers, or conducting physical motion tests.
Primary objective: Deliver the strongest reliable live search-and-rescue robot demo possible using our existing Raspberry Pi 3, LiDAR, OpenCR, camera, and MacBook.