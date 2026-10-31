#!/usr/bin/env python3
"""Run the read-only Pi probe over SSH; credentials are entered privately in your terminal."""

import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from turtlectl import ssh_arguments

BEGIN = "TURTBOT_PHASE_A_REPORT_BEGIN"
END = "TURTBOT_PHASE_A_REPORT_END"


def parse_report(output):
    if BEGIN not in output or END not in output:
        raise ValueError("The Pi did not return a complete probe report")
    body = output.split(BEGIN, 1)[1].split(END, 1)[0].strip()
    report = json.loads(body)
    if report.get("source") != "live_pi_probe" or report.get("phase") != "A":
        raise ValueError("Unexpected probe report format")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    try:
        connection = json.loads((ROOT / ".robot" / "connection.json").read_text())
        default_target = connection["username"] + "@" + connection["host"]
    except (OSError, ValueError, KeyError, TypeError):
        default_target = None
    parser.add_argument("--target", default=default_target)
    parser.add_argument("--seconds", type=int, default=15, choices=range(5, 31), metavar="5–30")
    parser.add_argument("--namespace", default="")
    args = parser.parse_args()
    if not args.target:
        parser.error("Specify --target USER@HOST, or configure username and host in .robot/connection.json")
    command = ("source /opt/ros/humble/setup.bash || exit $?\n"
               "export TURTLEBOT3_MODEL=burger\n"
               "exec python3 - --seconds " + str(args.seconds) + " --namespace " + shlex.quote(args.namespace))
    try:
        arguments = ssh_arguments(args.target, command)
    except ValueError as exc:
        parser.error(str(exc))
    (ROOT / ".robot").mkdir(exist_ok=True, mode=0o700)
    destination = ROOT / "diagnostics" / "phase_a"
    destination.mkdir(parents=True, exist_ok=True)
    print("Connecting to the Pi. If prompted, enter your SSH password privately in this terminal.", flush=True)
    print("Observing existing ROS publishers and testing existing camera tools; no driver starts or movement.", flush=True)
    try:
        result = subprocess.run(arguments, input=Path(__file__).with_name("probe.py").read_bytes(), capture_output=True, timeout=60)
        output = result.stdout.decode(errors="replace")
        report = parse_report(output)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        report = {"phase": "A", "source": "local_connection_check", "phase_a_status": "blocked",
                  "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                  "blockers": [str(exc)], "hardware_sensor_verification_completed": False}
        if "result" in locals():
            report["ssh_exit_code"] = result.returncode
            report["connection_error"] = result.stderr.decode(errors="replace")[-2000:]
        (destination / "latest.json").write_text(json.dumps(report, indent=2) + "\n")
        print("Phase A blocked. See " + str(destination / "latest.json"), file=sys.stderr)
        if report.get("connection_error"):
            print(report["connection_error"], file=sys.stderr)
        return 1
    encoded = report.pop("camera_image_base64", None)
    if encoded:
        image = base64.b64decode(encoded, validate=True)
        if len(image) > 4_000_000:
            raise ValueError("Camera image exceeds the probe limit")
        suffix = ".png" if image.startswith(b"\x89PNG\r\n\x1a\n") else ".jpg"
        image_path = destination / ("camera-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + suffix)
        image_path.write_bytes(image)
        report["camera"]["captured_image_file"] = str(image_path)
    path = destination / "latest.json"
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print("Report saved: " + str(path))
    for name, topic in report.get("ros", {}).get("topics", {}).items():
        rate = topic.get("observed_receive_hz")
        print(f"{name}: {topic.get('message_count', 0)} messages; observed rate {rate:.1f} Hz" if rate is not None else f"{name}: no frequency verified")
    for blocker in report.get("blockers", []):
        print("BLOCKER: " + blocker)
    return 0


if __name__ == "__main__":
    sys.exit(main())
