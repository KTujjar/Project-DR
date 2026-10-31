# Your robot programs

Edit Python files here on your Mac, then upload them to the Pi using
`python3 turtlectl.py deploy USER@HOST`. Uploading only copies these `.py` and
`.md` files to `~/turtbot_programs`; it does not start the robot or install packages.

Start with `ros2_sensor_report.py`. It observes battery, IMU, and lidar topics and
prints a report every second. It publishes no messages and never moves the robot.
Adjust the callbacks to build your own logging or decision logic. A missing or
stale sensor is reported explicitly. The nearest lidar return is an observation,
not a collision avoidance controller.

Run it using `python3 turtlectl.py run USER@HOST ros2_sensor_report.py --seconds 30`.
For a namespaced robot, append `--namespace YOUR_NAMESPACE`. Use `topics` to verify
actual topic names first. This program requires ROS 2 and the standard
`sensor_msgs` package on the Pi; its runtime cannot be verified until SSH login
and the onboard ROS installation are inspected.
