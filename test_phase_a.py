"""Phase A data validation and non-actuation checks; fixtures are not hardware evidence."""

import ast
import json
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dashboard.diagnostics.probe import Samples, complete_image, image_dimensions, inspect_camera, scan_sample
from dashboard.diagnostics.run_phase_a import BEGIN, END, parse_report


class PhaseATests(unittest.TestCase):
    def test_scan_rejects_missing_and_physically_out_of_range_values(self):
        message = SimpleNamespace(ranges=[float("nan"), float("inf"), 0.0, 0.05, 0.5, 2.0, 5.0],
            range_min=0.1, range_max=3.5, angle_min=-3.14, angle_max=3.14, angle_increment=0.01,
            header=SimpleNamespace(frame_id="base_scan", stamp=SimpleNamespace(sec=12, nanosec=30)))
        result = scan_sample(message)
        self.assertEqual(result["valid_count"], 2)
        self.assertEqual(result["nearest_valid_m"], 0.5)
        self.assertEqual(result["invalid_or_out_of_range_count"], 5)
        self.assertEqual(result["ranges_m"][:2], [None, None])
        json.dumps(result, allow_nan=False)

    def test_frequency_uses_receipt_intervals_and_exposes_staleness(self):
        samples = Samples()
        samples.times = [10.0, 10.2, 10.4]
        result = samples.report(now=15.0)
        self.assertAlmostEqual(result["observed_receive_hz"], 5.0)
        self.assertAlmostEqual(result["last_message_age_s"], 4.6)
        self.assertIsNone(Samples().report()["observed_receive_hz"])

    def test_image_resolution_must_come_from_real_image_header(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 640, 480)
        jpeg = b"\xff\xd8\xff\xc0\x00\x0b\x08" + struct.pack(">HH", 480, 640) + b"\x01\x01\x11\x00"
        self.assertEqual(image_dimensions(png), [640, 480])
        self.assertEqual(image_dimensions(jpeg), [640, 480])
        self.assertIsNone(image_dimensions(b"not an image"))
        self.assertIsNone(image_dimensions(b"\xff\xd8\xff\xc0\xff\xff"))
        self.assertFalse(complete_image(png))
        self.assertFalse(complete_image(jpeg))
        self.assertTrue(complete_image(png + b"\x00\x00\x00\x00IEND\xaeB`\x82"))
        self.assertTrue(complete_image(jpeg + b"\xff\xd9"))

    def test_camera_capture_is_not_attempted_if_enumeration_fails(self):
        with patch("dashboard.diagnostics.probe.shutil.which", side_effect=lambda name: "/usr/bin/" + name if name in ("libcamera-hello", "libcamera-still") else None), \
             patch("dashboard.diagnostics.probe.importlib.util.find_spec", return_value=None), \
             patch("dashboard.diagnostics.probe.Path.glob", return_value=[]), \
             patch("dashboard.diagnostics.probe.command_result", return_value={"exit_code": 0, "output": "No cameras available"}) as commands:
            result, image = inspect_camera({}, None)
        self.assertFalse(result["image_acquisition_verified"])
        self.assertIsNone(image)
        commands.assert_called_once_with(["/usr/bin/libcamera-hello", "--list-cameras"])

    def test_existing_image_publisher_prevents_competing_camera_capture(self):
        with patch("dashboard.diagnostics.probe.shutil.which", return_value="/usr/bin/unused"), \
             patch("dashboard.diagnostics.probe.importlib.util.find_spec", return_value=None), \
             patch("dashboard.diagnostics.probe.Path.glob", return_value=[]), \
             patch("dashboard.diagnostics.probe.command_result") as commands:
            result, _ = inspect_camera({"camera": {"topic": "/image_raw", "message_count": 0}}, None)
        self.assertFalse(result["image_acquisition_verified"])
        commands.assert_not_called()

    def test_no_partial_or_non_probe_output_is_treated_as_sensor_evidence(self):
        with self.assertRaises(ValueError):
            parse_report("Permission denied")
        with self.assertRaises(ValueError):
            parse_report(BEGIN + '{"phase":"A","source":"mock"}' + END)
        data = {"phase": "A", "source": "live_pi_probe", "blockers": ["no scan"]}
        self.assertEqual(parse_report("shell banner\n" + BEGIN + json.dumps(data) + END), data)

    def test_probe_has_no_motion_publishers_or_driver_launches(self):
        source = Path("dashboard/diagnostics/probe.py").read_text()
        tree = ast.parse(source)
        called = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertNotIn("create_publisher", called)
        self.assertNotIn("writeTxRx", called)
        self.assertNotIn("set_velocity", called)
        self.assertNotIn("ros2 launch", source)
        self.assertNotIn("sudo ", source)


if __name__ == "__main__":
    unittest.main()
