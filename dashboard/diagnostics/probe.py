#!/usr/bin/env python3
"""Bounded Phase A observation on the Pi. Never launches drivers or commands motion."""

import argparse
import base64
from datetime import datetime, timezone
import getpass
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time

BEGIN = "TURTBOT_PHASE_A_REPORT_BEGIN"
END = "TURTBOT_PHASE_A_REPORT_END"


def finite(value):
    value = float(value)
    return value if math.isfinite(value) else None


def scan_sample(message):
    ranges = [finite(x) for x in message.ranges]
    valid = [x for x in ranges if x is not None and x > 0 and message.range_min <= x <= message.range_max]
    return {
        "frame_id": message.header.frame_id,
        "stamp": {"sec": message.header.stamp.sec, "nanosec": message.header.stamp.nanosec},
        "angle_min": finite(message.angle_min), "angle_max": finite(message.angle_max),
        "angle_increment": finite(message.angle_increment),
        "range_min_m": finite(message.range_min), "range_max_m": finite(message.range_max),
        "range_count": len(ranges), "valid_count": len(valid),
        "invalid_or_out_of_range_count": len(ranges) - len(valid),
        "nearest_valid_m": min(valid) if valid else None,
        "ranges_m": ranges,
    }


def image_dimensions(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return list(struct.unpack(">II", data[16:24]))
    if not data.startswith(b"\xff\xd8"):
        return None
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 255:
            return None
        while offset < len(data) and data[offset] == 255:
            offset += 1
        if offset >= len(data):
            return None
        marker = data[offset]
        offset += 1
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(data):
            return None
        length = int.from_bytes(data[offset:offset + 2], "big")
        if length < 2 or offset + length > len(data):
            return None
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF) and length >= 7:
            height, width = struct.unpack(">HH", data[offset + 3:offset + 7])
            return [width, height]
        if marker == 0xDA:
            return None
        offset += length
    return None


def complete_image(data):
    dimensions = image_dimensions(data)
    if not dimensions or not all(0 < x <= 16384 for x in dimensions):
        return False
    if data.startswith(b"\xff\xd8"):
        return data.endswith(b"\xff\xd9")
    return data.startswith(b"\x89PNG\r\n\x1a\n") and data.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82")


class Samples:
    def __init__(self):
        self.times = []
        self.latest = None
        self.valid_scan_frames = 0

    def record(self, sample):
        self.times.append(time.monotonic())
        self.latest = sample
        if sample.get("valid_count", 0) > 0:
            self.valid_scan_frames += 1

    def report(self, now=None):
        now = time.monotonic() if now is None else now
        elapsed = self.times[-1] - self.times[0] if len(self.times) > 1 else 0
        return {
            "message_count": len(self.times),
            "observed_receive_hz": (len(self.times) - 1) / elapsed if elapsed > 0 else None,
            "last_message_age_s": now - self.times[-1] if self.times else None,
            "valid_scan_frames": self.valid_scan_frames,
            "latest": self.latest,
        }


def process_inventory():
    roles = {"opencr_driver": ("turtlebot3_node", "turtlebot3_ros"), "lidar_driver": ("hlds_laser_publisher",), "bringup": ("robot.launch.py",)}
    found = {key: [] for key in roles}
    for entry in Path("/proc").glob("[0-9]*"):
        try:
            arguments = (entry / "cmdline").read_bytes().split(b"\0")
            names = [Path(os.fsdecode(arg)).name for arg in arguments if arg]
            for role, candidates in roles.items():
                # A `ros2 run` wrapper isn't itself another hardware driver.
                searched = names if role == "bringup" else names[:1]
                if any(name in candidates for name in searched):
                    found[role].append(int(entry.name))
        except (OSError, ValueError):
            continue
    return found


def command_result(arguments, timeout=6):
    try:
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)
        return {"command": arguments, "exit_code": result.returncode,
                "output": (result.stdout + result.stderr)[-6000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": arguments, "exit_code": None, "error": str(exc)}


def observe_ros(seconds, namespace):
    try:
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import qos_profile_sensor_data
        from nav_msgs.msg import Odometry
        from sensor_msgs.msg import BatteryState, CompressedImage, Image, Imu, LaserScan
    except ImportError as exc:
        return {"status": "blocked", "error": str(exc), "topics": {}}, None
    rclpy.init(args=[])
    node = Node("turtbot_phase_a_probe_" + str(os.getpid()), enable_rosout=False, start_parameter_services=False)
    prefix = "/" + namespace.strip("/") if namespace.strip("/") else ""
    definitions = {
        "scan": (prefix + "/scan", "sensor_msgs/msg/LaserScan", LaserScan),
        "odom": (prefix + "/odom", "nav_msgs/msg/Odometry", Odometry),
        "imu": (prefix + "/imu", "sensor_msgs/msg/Imu", Imu),
        "battery": (prefix + "/battery_state", "sensor_msgs/msg/BatteryState", BatteryState),
    }
    samples = {name: Samples() for name in definitions}
    subscriptions = {}
    camera_image = None
    camera_selected = None
    camera_samples = Samples()
    graph = {}

    def callback(name, message):
        if name == "scan":
            sample = scan_sample(message)
        elif name == "odom":
            sample = {"frame_id": message.header.frame_id,
                      "position_xy_m": [finite(message.pose.pose.position.x), finite(message.pose.pose.position.y)],
                      "linear_x_m_s": finite(message.twist.twist.linear.x),
                      "angular_z_rad_s": finite(message.twist.twist.angular.z)}
        elif name == "imu":
            sample = {"frame_id": message.header.frame_id,
                      "angular_velocity_xyz": [finite(getattr(message.angular_velocity, axis)) for axis in "xyz"],
                      "linear_acceleration_xyz": [finite(getattr(message.linear_acceleration, axis)) for axis in "xyz"]}
        else:
            sample = {"voltage_V": finite(message.voltage), "percentage_fraction": finite(message.percentage)}
        sample["stamp"] = {"sec": message.header.stamp.sec, "nanosec": message.header.stamp.nanosec}
        sample["frame_id"] = message.header.frame_id
        samples[name].record(sample)

    def camera_callback(message):
        nonlocal camera_image
        if isinstance(message, CompressedImage):
            data = bytes(message.data)
            dimensions = image_dimensions(data)
            valid = complete_image(data)
            sample = {"format": message.format, "resolution": dimensions, "bytes": len(data), "valid_frame": valid}
            if valid and camera_image is None and len(data) <= 4_000_000:
                camera_image = data
        else:
            valid = message.width > 0 and message.height > 0 and message.step > 0 and len(message.data) >= message.step * message.height
            sample = {"encoding": message.encoding, "resolution": [message.width, message.height],
                      "bytes": len(message.data), "valid_frame": valid}
        sample["stamp"] = {"sec": message.header.stamp.sec, "nanosec": message.header.stamp.nanosec}
        sample["frame_id"] = message.header.frame_id
        camera_samples.record(sample)

    def endpoints(topic):
        result = []
        for info in node.get_publishers_info_by_topic(topic):
            qos = info.qos_profile
            result.append({"node_name": info.node_name, "node_namespace": info.node_namespace,
                           "topic_type": info.topic_type,
                           "qos": {key: getattr(getattr(qos, key), "name", str(getattr(qos, key)))
                                   for key in ("reliability", "durability", "history")},
                           "qos_depth": qos.depth})
        return result

    try:
        deadline = time.monotonic() + seconds
        refresh = 0
        while time.monotonic() < deadline:
            if time.monotonic() >= refresh:
                graph = dict(node.get_topic_names_and_types())
                for name, (topic, type_name, message_type) in definitions.items():
                    if name not in subscriptions and type_name in graph.get(topic, []):
                        subscriptions[name] = node.create_subscription(message_type, topic,
                            lambda message, name=name: callback(name, message), qos_profile_sensor_data)
                if camera_selected is None:
                    candidates = [(topic, types) for topic, types in sorted(graph.items())
                                  if "sensor_msgs/msg/CompressedImage" in types or "sensor_msgs/msg/Image" in types]
                    if candidates:
                        # Reuse an existing image publisher; never start a second camera driver.
                        topic, types = next((item for item in candidates if "sensor_msgs/msg/CompressedImage" in item[1]), candidates[0])
                        message_type = CompressedImage if "sensor_msgs/msg/CompressedImage" in types else Image
                        camera_selected = topic
                        subscriptions["camera"] = node.create_subscription(message_type, topic, camera_callback, qos_profile_sensor_data)
                refresh = time.monotonic() + 0.5
            rclpy.spin_once(node, timeout_sec=0.05)
        topics = {}
        for name, (topic, expected_type, _) in definitions.items():
            observation = samples[name].report()
            observation.update({"topic": topic, "expected_type": expected_type,
                                "advertised_types": graph.get(topic, []), "publishers": endpoints(topic)})
            observation["publishing_verified"] = observation["message_count"] >= 2 and observation["last_message_age_s"] < 3
            if name == "scan":
                observation["valid_measurements_verified"] = observation["publishing_verified"] and samples[name].valid_scan_frames >= 2 and observation["latest"]["valid_count"] > 0
            topics[name] = observation
        commands = {topic: endpoints(topic) for topic in graph if topic == prefix + "/cmd_vel"}
        return {"status": "observed", "sample_duration_s": seconds, "topics": topics,
                "synchronization": "Independent topic observations; this report is not a synchronized sensor snapshot",
                "motion_command_publishers": commands,
                "camera_topics_advertised": [topic for topic, types in graph.items()
                    if any(t in types for t in ("sensor_msgs/msg/CompressedImage", "sensor_msgs/msg/Image"))],
                "camera": {"topic": camera_selected, "publishers": endpoints(camera_selected) if camera_selected else [], **camera_samples.report()}}, camera_image
    finally:
        node.destroy_node()
        rclpy.shutdown()


def inspect_camera(ros, existing_image):
    tools = {name: shutil.which(name) for name in (
        "rpicam-hello", "rpicam-still", "rpicam-vid", "libcamera-hello", "libcamera-still", "libcamera-vid", "v4l2-ctl", "cam")}
    devices = []
    for path in sorted(Path("/sys/class/video4linux").glob("video*")):
        try:
            devices.append({"device": "/dev/" + path.name, "name": (path / "name").read_text().strip()})
        except OSError:
            continue
    result = {"available_tools": tools, "video_devices": devices, "driver_selected": None,
              "picamera2_installed": importlib.util.find_spec("picamera2") is not None,
              "image_acquisition_verified": False, "video_stream_verified": False}
    camera_ros = ros.get("camera", {})
    if camera_ros.get("topic"):
        latest = camera_ros.get("latest") or {}
        age = camera_ros.get("last_message_age_s")
        result.update({"source": "existing_ros_publisher", "ros_topic": camera_ros["topic"],
                       "image_acquisition_verified": bool(latest.get("valid_frame")) and age is not None and age < 3,
                       "video_stream_verified": camera_ros.get("message_count", 0) >= 2 and bool(latest.get("valid_frame")) and age is not None and age < 3,
                       "observed_receive_hz": camera_ros.get("observed_receive_hz"), "latest": latest})
        result["publishers"] = camera_ros.get("publishers", [])
        if not result["image_acquisition_verified"]:
            result["blocker"] = "An image topic is advertised but no fresh valid frame arrived; do not open a competing camera capture."
        return result, existing_image
    hello = next((tools[name] for name in ("rpicam-hello", "libcamera-hello") if tools[name]), None)
    if hello:
        listing = command_result([hello, "--list-cameras"])
        result["enumeration"] = listing
        detected = listing.get("exit_code") == 0 and bool(re.search(r"(?m)^\s*\d+\s*:", listing.get("output", "")))
        still_name = "rpicam-still" if Path(hello).name.startswith("rpicam") else "libcamera-still"
        if detected and tools[still_name]:
            with tempfile.TemporaryDirectory(prefix="turtbot-camera-probe-") as directory:
                output = Path(directory) / "camera.jpg"
                acquisition = command_result([tools[still_name], "--nopreview", "--timeout", "1000", "--width", "640", "--height", "480", "--encoding", "jpg", "--output", str(output)], timeout=8)
                result["acquisition"] = acquisition
                if acquisition.get("exit_code") == 0 and output.is_file():
                    data = output.read_bytes()
                    resolution = image_dimensions(data)
                    if complete_image(data) and len(data) <= 4_000_000:
                        result.update({"image_acquisition_verified": True, "tested_capture_tool": still_name,
                                       "resolution": resolution, "source": "hardware_still_capture"})
                        return result, data
    elif tools["cam"]:
        result["enumeration"] = command_result([tools["cam"], "-l"])
    if tools["v4l2-ctl"]:
        result["v4l2_devices"] = command_result([tools["v4l2-ctl"], "--list-devices"])
    result["blocker"] = "No image acquisition verified with existing software. Review camera enumeration before selecting or installing a driver."
    return result, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--namespace", default="")
    args = parser.parse_args()
    if not 5 <= args.seconds <= 30:
        parser.error("--seconds must be between 5 and 30")
    if sys.platform != "linux":
        parser.error("Run this probe on the Pi using run_phase_a.py, not directly on macOS")
    report = {"phase": "A", "source": "live_pi_probe", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
              "host": socket.gethostname(), "username": getpass.getuser(),
              "ros_environment": {key: os.environ.get(key) for key in ("ROS_DISTRO", "ROS_DOMAIN_ID", "RMW_IMPLEMENTATION", "TURTLEBOT3_MODEL", "LDS_MODEL")},
              "driver_processes": process_inventory(),
              "serial_devices": {device: {"exists": Path(device).exists(), "readable": os.access(device, os.R_OK), "writable": os.access(device, os.W_OK)}
                                 for device in ("/dev/ttyACM0", "/dev/ttyUSB0")},
              "motion_commands_sent": False, "drivers_started": False, "system_configuration_changed": False}
    blockers = []
    if report["host"] != "turtle19" or report["username"] != "turtle":
        blockers.append("Pi identity differs from the expected turtle@turtle19; review before integration")
    if report["ros_environment"]["ROS_DISTRO"] != "humble":
        blockers.append("Expected ROS 2 Humble environment is not active")
    try:
        report["ros"], image = observe_ros(args.seconds, args.namespace)
    except Exception as exc:
        report["ros"], image = {"status": "error", "error": type(exc).__name__ + ": " + str(exc), "topics": {}}, None
    report["camera"], image = inspect_camera(report["ros"], image)
    for name in ("scan", "odom", "imu", "battery"):
        topic = report["ros"].get("topics", {}).get(name, {})
        if not topic.get("publishing_verified"):
            blockers.append(name + ": fresh publishing not verified")
        elif name == "scan" and not topic.get("valid_measurements_verified"):
            blockers.append("scan: messages arrived but valid distance measurements were not verified")
    for role in ("opencr_driver", "lidar_driver"):
        if len(report["driver_processes"][role]) > 1:
            blockers.append(role + ": multiple driver processes detected; review before starting anything")
    if not report["camera"]["image_acquisition_verified"]:
        blockers.append("camera: image acquisition not verified")
    report["unverified_later_phases"] = ["Browser dashboard", "Physical movement", "Synchronized sensor snapshots", "AI interpretation"]
    if not report["camera"]["video_stream_verified"]:
        report["unverified_later_phases"].append("Camera video streaming")
    report["blockers"] = blockers
    report["phase_a_status"] = "blockers_reported" if blockers else "sensor_checks_passed"
    if image:
        report["camera_image_base64"] = base64.b64encode(image).decode("ascii")
    print(BEGIN)
    print(json.dumps(report, allow_nan=False))
    print(END, flush=True)


if __name__ == "__main__":
    main()
