"""Subscribe to existing ROS hardware drivers. Never launches or replaces them."""
from io import BytesIO
import math
import os
import socket
import threading
import time

from .safety import ControlDenied
from .obstacle_guard import ObstacleGuard


def number(value):
    value = float(value)
    return value if math.isfinite(value) else None


class RosBridge:
    def __init__(self, store, control):
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import qos_profile_sensor_data
        from nav_msgs.msg import Odometry, OccupancyGrid
        from sensor_msgs.msg import BatteryState, CompressedImage, Image, Imu, JointState, LaserScan
        self.rclpy, self.store, self.control = rclpy, store, control
        self.finished = threading.Event()
        self.control.guard = ObstacleGuard()
        self.publisher = None
        self.release_at = None
        self.camera_topic = None
        self.node_name = "turtbot_dashboard_" + str(os.getpid())
        self.prefix = "/" + os.environ.get("TURTBOT_NAMESPACE", "").strip("/") if os.environ.get("TURTBOT_NAMESPACE", "").strip("/") else ""
        rclpy.init(args=[])
        self.node = Node(self.node_name, enable_rosout=False)
        self.types = (CompressedImage, Image)
        self.qos = qos_profile_sensor_data
        self.subscriptions = []
        for topic, cls, callback in (
            ("scan", LaserScan, self.scan), ("odom", Odometry, self.odom),
            ("imu", Imu, self.imu), ("battery_state", BatteryState, self.battery),
            ("joint_states", JointState, self.joints)):
            self.subscriptions.append(self.node.create_subscription(cls, self.prefix + "/" + topic, callback, self.qos))
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
        map_qos=QoSProfile(depth=1,reliability=ReliabilityPolicy.BEST_EFFORT,durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.subscriptions.append(self.node.create_subscription(OccupancyGrid, self.prefix + '/map', self.occupancy_map, map_qos))
        self.node.create_timer(0.05, self.watchdog)
        self.node.create_timer(1.0, self.graph)
        self.control.prepare = self.prepare_control
        self.control.publish = self.publish
        self.control.release = self.release_control
        self.control.conflicts = self.conflicts
        self.store.metadata.update({"robot": socket.gethostname(), "ros_distribution": os.environ.get("ROS_DISTRO"),
            "ros_domain_id": os.environ.get("ROS_DOMAIN_ID"), "camera_note": "Waiting for the authenticated Mac camera relay; V4L2 raw acquisition was verified.",
            "driver_status": "Subscribing to existing bringup; no drivers started"})
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def stamp(self, message):
        return message.header.stamp.sec + message.header.stamp.nanosec / 1e9

    def scan(self, message):
        ranges = [number(value) for value in message.ranges]
        valid = sum(value is not None and value > 0 and message.range_min <= value <= message.range_max for value in ranges)
        scan = {"ranges": ranges, "angle_min": message.angle_min,
            "angle_increment": message.angle_increment, "range_min": message.range_min,
            "range_max": message.range_max, "frame_id": message.header.frame_id, "valid_count": valid}
        self.control.guard.update(scan)
        self.store.update("scan", scan, self.stamp(message))

    def odom(self, message):
        pose, twist = message.pose.pose, message.twist.twist
        q = pose.orientation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        self.store.update("odom", {"x": number(pose.position.x), "y": number(pose.position.y),
            "yaw": number(yaw), "linear": number(twist.linear.x), "angular": number(twist.angular.z)}, self.stamp(message))

    def imu(self, message):
        self.store.update("imu", {"gyro": [number(getattr(message.angular_velocity, axis)) for axis in "xyz"],
            "acceleration": [number(getattr(message.linear_acceleration, axis)) for axis in "xyz"]}, self.stamp(message))

    def battery(self, message):
        fraction = number(message.percentage)
        # Some TurtleBot3 Humble drivers publish 0–100 despite BatteryState's 0–1 convention.
        percentage = fraction * 100 if fraction is not None and 0 <= fraction <= 1 else fraction if fraction is not None and 1 < fraction <= 100 else None
        self.store.update("battery", {"voltage": number(message.voltage),
            "percentage": percentage}, self.stamp(message))

    def joints(self, message):
        self.store.update("joints", {"names": list(message.name), "positions": [number(x) for x in message.position],
            "velocities": [number(x) for x in message.velocity]}, self.stamp(message))

    def camera(self, message):
        try:
            compressed, _ = self.types
            if isinstance(message, compressed):
                image = bytes(message.data)
                from PIL import Image
                with Image.open(BytesIO(image)) as decoded:
                    decoded.verify()
                with Image.open(BytesIO(image)) as decoded:
                    width, height = decoded.size
                mime = "image/png" if image.startswith(b"\x89PNG") else "image/jpeg"
            else:
                from PIL import Image
                layouts = {"rgb8": ("RGB", "RGB"), "bgr8": ("RGB", "BGR"), "mono8": ("L", "L"),
                           "rgba8": ("RGBA", "RGBA"), "bgra8": ("RGBA", "BGRA")}
                if message.encoding not in layouts:
                    raise ValueError("Unsupported camera encoding: " + message.encoding)
                mode, raw = layouts[message.encoding]
                frame = Image.frombytes(mode, (message.width, message.height), bytes(message.data), "raw", raw, message.step, 1).convert("RGB")
                output = BytesIO()
                frame.save(output, format="JPEG", quality=80)
                image, mime = output.getvalue(), "image/jpeg"
                width, height = frame.size
            self.store.update_camera({"width": width, "height": height, "verified": True,
                "format": mime, "topic": self.camera_topic}, image, mime, self.stamp(message))
            with self.store.lock:
                self.store.metadata["camera_note"] = "Receiving decoded images from the existing ROS publisher"
        except Exception as exc:
            with self.store.lock:
                self.store.metadata["camera_note"] = str(exc)

    def occupancy_map(self, message):
        if message.info.width*message.info.height>1_000_000:
            return
        origin=message.info.origin
        with self.store.lock:
            self.store.occupancy_map={'width':message.info.width,'height':message.info.height,'resolution':message.info.resolution,
                'frame_id':message.header.frame_id,'stamp':self.stamp(message),'origin':{'x':origin.position.x,'y':origin.position.y,
                'orientation':{'x':origin.orientation.x,'y':origin.orientation.y,'z':origin.orientation.z,'w':origin.orientation.w}},'data':list(message.data)}

    def graph(self):
        from .system_status import read
        with self.store.lock:
            self.store.metadata["system"] = read()
        graph = dict(self.node.get_topic_names_and_types())
        if self.camera_topic is None:
            explicit = os.environ.get("TURTBOT_CAMERA_TOPIC")
            candidates = [(topic, types) for topic, types in sorted(graph.items())
                if (not explicit or topic == explicit) and "depth" not in topic
                and any(name in types for name in ("sensor_msgs/msg/CompressedImage", "sensor_msgs/msg/Image"))]
            if candidates:
                topic, types = next((item for item in candidates if "sensor_msgs/msg/CompressedImage" in item[1]), candidates[0])
                cls = self.types[0] if "sensor_msgs/msg/CompressedImage" in types else self.types[1]
                self.camera_topic = topic
                self.subscriptions.append(self.node.create_subscription(cls, topic, self.camera, self.qos))
        with self.store.lock:
            self.store.metadata["cmd_vel_other_publishers"] = self.conflicts()
            self.store.metadata["ros_nodes"] = sorted(self.node.get_node_names())

    def conflicts(self):
        return sum(info.node_name != self.node_name for info in self.node.get_publishers_info_by_topic(self.prefix + "/cmd_vel"))

    def prepare_control(self):
        if self.conflicts():
            raise ControlDenied("Another /cmd_vel publisher is present")
        if not self.node.get_subscriptions_info_by_topic(self.prefix + "/cmd_vel"):
            raise ControlDenied("No robot velocity subscriber is present")
        from geometry_msgs.msg import Twist, TwistStamped
        types = dict(self.node.get_topic_names_and_types()).get(self.prefix + "/cmd_vel", [])
        if types == ["geometry_msgs/msg/TwistStamped"]:
            self.velocity_type = TwistStamped
        elif types == ["geometry_msgs/msg/Twist"]:
            self.velocity_type = Twist
        else:
            raise ControlDenied("Velocity topic type is missing or ambiguous")
        if self.publisher is None:
            self.publisher = self.node.create_publisher(self.velocity_type, self.prefix + "/cmd_vel", 10)
        self.release_at = None

    def publish(self, linear, angular):
        if self.publisher is None:
            raise ControlDenied("Velocity publisher is not prepared")
        message = self.velocity_type()
        if hasattr(message, "twist"):
            message.header.stamp = self.node.get_clock().now().to_msg()
            velocity = message.twist
        else:
            velocity = message
        velocity.linear.x, velocity.angular.z = linear, angular
        self.publisher.publish(message)

    def release_control(self):
        self.release_at = time.monotonic() + 0.3

    def watchdog(self):
        try:
            self.control.tick()
            if self.release_at and time.monotonic() >= self.release_at and self.control.owner is None:
                if self.publisher:
                    self.node.destroy_publisher(self.publisher)
                    self.publisher = None
                self.release_at = None
        except Exception as exc:
            try:
                self.control.disarm("ROS watchdog error")
            except Exception:
                pass
            with self.store.lock:
                self.store.metadata["errors"] = ["ROS control watchdog: " + str(exc)]

    def run(self):
        try:
            while not self.finished.is_set() and self.rclpy.ok():
                self.rclpy.spin_once(self.node, timeout_sec=0.05)
        except Exception as exc:
            with self.store.lock:
                self.store.metadata["errors"] = ["ROS bridge stopped: " + str(exc)]
            self.control.disarm("ROS bridge stopped")

    def close(self):
        try:
            self.control.disarm("Application shutdown")
            if self.publisher:
                time.sleep(0.3)
        finally:
            self.finished.set()
            self.thread.join(timeout=2)
            self.node.destroy_node()
            if self.rclpy.ok():
                self.rclpy.shutdown()
