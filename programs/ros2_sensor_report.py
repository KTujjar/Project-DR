#!/usr/bin/env python3
"""A first robot program: observe battery, IMU, and lidar without commanding motion."""

import argparse
import math
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="", help="Robot namespace, if configured")
    parser.add_argument("--seconds", type=float, default=30, help="Run duration; 0 means until Ctrl-C")
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or args.seconds < 0:
        parser.error("--seconds must be finite and nonnegative")
    try:
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import BatteryState, Imu, LaserScan
    except ImportError:
        parser.exit(2, "ROS 2 Python modules are unavailable. Source the Pi's installed ROS 2 environment first.\n")

    class SensorReport(Node):
        def __init__(self):
            super().__init__("turtbot_sensor_report", namespace=args.namespace or "/")
            self.latest = {}
            self.subscriptions_ = [
                self.create_subscription(BatteryState, "battery_state", self.battery, qos_profile_sensor_data),
                self.create_subscription(Imu, "imu", self.imu, qos_profile_sensor_data),
                self.create_subscription(LaserScan, "scan", self.scan, qos_profile_sensor_data),
            ]
            self.timer_ = self.create_timer(1.0, self.report)

        def battery(self, message):
            self.latest["battery"] = (time.monotonic(), f"{message.voltage:.2f} V")

        def imu(self, message):
            angular = message.angular_velocity
            self.latest["imu"] = (time.monotonic(), f"gyro=({angular.x:.3f}, {angular.y:.3f}, {angular.z:.3f}) rad/s")

        def scan(self, message):
            valid = [r for r in message.ranges if math.isfinite(r) and message.range_min <= r <= message.range_max]
            closest = f"nearest return={min(valid):.2f} m" if valid else "no valid lidar returns"
            self.latest["lidar"] = (time.monotonic(), closest)

        def report(self):
            now = time.monotonic()
            parts = []
            for key in ("battery", "imu", "lidar"):
                if key not in self.latest:
                    parts.append(f"{key}: waiting for messages")
                else:
                    timestamp, text = self.latest[key]
                    age = now - timestamp
                    parts.append(f"{key}: {text}" + (f" (stale, {age:.0f}s old)" if age > 3 else ""))
            self.get_logger().info(" | ".join(parts))

    rclpy.init()
    node = SensorReport()
    started = time.monotonic()
    try:
        while rclpy.ok() and (args.seconds == 0 or time.monotonic() - started < args.seconds):
            rclpy.spin_once(node, timeout_sec=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
