#!/usr/bin/env python3
"""Interface with TurtleBot3 over OpenCR USB or the Pi's existing ROS via SSH."""

import argparse
import glob
import io
import ipaddress
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile

PROJECT = Path(__file__).resolve().parent


def run_local(arguments, timeout=8):
    try:
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip() or result.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)


def doctor():
    print("USB devices (a Pi's ordinary USB port is not a host connection):")
    print(run_local(["ioreg", "-p", "IOUSB", "-w", "0"]))
    ports = [p for p in glob.glob("/dev/cu.*")
             if not p.endswith(("Bluetooth-Incoming-Port", "debug-console"))]
    print("\nUSB serial ports:", ", ".join(ports) or "none detected")
    print("\nLocal ROS:", shutil.which("ros2") or shutil.which("roscore") or "not found; SSH mode does not require local ROS")
    print("SSH:", shutil.which("ssh") or "not found")
    if shutil.which("gz"):
        commands = run_local(["gz", "--commands"])
        print("Gazebo simulator command:", "available" if "sim" in commands.splitlines() else "missing (Gazebo installation is incomplete)")
    else:
        print("Gazebo: not found")
    return 0


INSPECT = r'''
printf 'Robot: '; hostname
printf '\nOperating system:\n'
if [ -r /etc/os-release ]; then cat /etc/os-release; else uname -a; fi
printf '\nROS distributions installed:\n'
if [ -d /opt/ros ]; then ls -1 /opt/ros; else printf 'No /opt/ros directory\n'; fi
printf '\nCurrent ROS environment:\n'
env | LC_ALL=C sort | grep -E '^(ROS_|RMW_|TURTLEBOT3_|LDS_MODEL=|CYCLONEDDS_URI=|FASTRTPS_DEFAULT_PROFILES_FILE=)' || true
printf '\nROS commands in this shell:\n'
command -v ros2 || command -v rostopic || true
printf '\nRobot USB serial devices:\n'
ls /dev/ttyACM* /dev/ttyUSB* /dev/serial/by-id/* 2>/dev/null || true
printf '\nPotential workspace setup files:\n'
for workspace in "$HOME/turtlebot3_ws" "$HOME/turtlebot_ws" "$HOME/catkin_ws"; do
  for setup in "$workspace/install/setup.bash" "$workspace/devel/setup.bash"; do
    if [ -r "$setup" ]; then printf '%s\n' "$setup"; fi
  done
done
'''


def remote_script(command, topic=None, distro=None, setup=None, program=None, program_args=()):
    if command == "inspect":
        body = INSPECT
    elif command == "run":
        body = 'exec python3 "$HOME/turtbot_programs/"' + shlex.quote(program)
        if program_args:
            body += " " + shlex.join(program_args)
    else:
        ros2 = {
            "topics": "ros2 topic list -t",
            "nodes": "ros2 node list",
            "services": "ros2 service list -t",
            "actions": "ros2 action list -t",
            "read": "ros2 topic echo " + shlex.quote(topic or "") + " --once",
            "hz": "ros2 topic hz " + shlex.quote(topic or ""),
        }[command]
        ros1 = {
            "topics": "rostopic list -v",
            "nodes": "rosnode list",
            "services": "rosservice list",
            "actions": "printf '%s\\n' 'ROS 1: inspect action topics with the topics command.'; exit 2",
            "read": "rostopic echo -n 1 " + shlex.quote(topic or ""),
            "hz": "rostopic hz " + shlex.quote(topic or ""),
        }[command]
        body = """
if command -v ros2 >/dev/null 2>&1; then
  exec %s
elif command -v rostopic >/dev/null 2>&1; then
  %s
else
  printf 'ROS tools are not available. Run inspect, then specify --distro and/or --setup.\\n' >&2
  exit 2
fi
""" % (ros2, ros1)

    prelude = ""
    if distro:
        prelude += ". " + shlex.quote("/opt/ros/" + distro + "/setup.bash") + " || exit\n"
    elif command != "inspect":
        prelude += r'''
if ! command -v ros2 >/dev/null 2>&1 && ! command -v rostopic >/dev/null 2>&1; then
  shopt -s nullglob
  ros_setups=(/opt/ros/*/setup.bash)
  if [ "${#ros_setups[@]}" -eq 1 ]; then
    . "${ros_setups[0]}" || exit
  fi
fi
'''
    if setup:
        prelude += ". " + shlex.quote(setup) + " || exit\n"
    return prelude + body


def validate_target(target):
    user, separator, host = target.rpartition("@")
    if not separator:
        user, host = "", target
    if separator and not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", user):
        raise ValueError("Invalid SSH username")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if ":" in host:
        address, scoped, interface = host.partition("%")
        try:
            ipaddress.IPv6Address(address)
        except ValueError as exc:
            raise ValueError("Invalid IPv6 address") from exc
        if scoped and not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", interface):
            raise ValueError("Invalid IPv6 network interface")
    elif not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", host):
        raise ValueError("Use an IPv4 address, hostname, or scoped IPv6 address")
    return (user + "@" if separator else "") + host


def ssh_arguments(target, script=None, read_shell_config=True, terminal=False):
    target = validate_target(target)
    arguments = ["ssh", "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2",
                 "-o", "StrictHostKeyChecking=accept-new", "-o", "UserKnownHostsFile=" + str(PROJECT / ".robot" / "known_hosts")]
    if script is None:
        return arguments + ["-t", target]
    # Interactive bash reads the Pi user's .bashrc, including its ROS/domain configuration.
    shell = "bash -ic " if read_shell_config else "bash -c "
    return arguments + (["-tt"] if terminal else ["-T"]) + [target, shell + shlex.quote(script)]


def program_archive():
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for path in sorted((PROJECT / "programs").iterdir()):
            if path.is_file() and not path.is_symlink() and path.suffix in (".py", ".md"):
                archive.add(path, arcname=path.name, recursive=False)
    return buffer.getvalue()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "usb":
        from opencr_interface import main as usb_main
        return usb_main(sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check this Mac's USB and software; does not open serial ports")
    commands.add_parser("usb", help="Direct OpenCR connection; use usb --help for commands")
    for name, help_text in {
        "inspect": "Read the Pi's OS, ROS configuration, and serial device names",
        "topics": "List available ROS topics and message types",
        "nodes": "List running ROS nodes",
        "services": "List available ROS services (does not call them)",
        "actions": "List available ROS 2 actions (does not send goals)",
        "read": "Read one sensor/topic message; Ctrl-C if no data arrives",
        "hz": "Measure a topic's update rate until Ctrl-C",
        "shell": "Open an interactive SSH terminal on the Pi",
        "deploy": "Upload this folder's programs to ~/turtbot_programs on the Pi",
        "run": "Run an uploaded Python program in the Pi's ROS environment",
    }.items():
        cmd = commands.add_parser(name, help=help_text)
        cmd.add_argument("target", help="Pi address, e.g. ubuntu@192.168.1.42")
        if name in ("read", "hz"):
            cmd.add_argument("topic", help="Exact topic name from the topics command")
        if name not in ("shell", "deploy"):
            cmd.add_argument("--distro", help="Explicit installed ROS distribution, e.g. humble or jazzy")
            cmd.add_argument("--setup", help="Absolute path of an existing workspace setup.bash on the Pi")
        if name == "run":
            cmd.add_argument("program", help="Uploaded program filename, e.g. ros2_sensor_report.py")
            cmd.add_argument("program_args", nargs=argparse.REMAINDER, help="Arguments passed to the program")
    args = parser.parse_args()
    if args.command == "doctor":
        return doctor()
    if getattr(args, "distro", None) and not re.fullmatch(r"[a-z][a-z0-9_]*", args.distro):
        parser.error("--distro must be a ROS distribution name")
    if getattr(args, "setup", None) and not args.setup.startswith("/"):
        parser.error("--setup must be an absolute path on the Pi")
    if getattr(args, "topic", None) and not re.fullmatch(r"/[A-Za-z0-9_/]+", args.topic):
        parser.error("Use a full topic name beginning with /, as listed by topics")
    if args.command == "run" and not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.py", args.program):
        parser.error("Use a plain uploaded .py filename, without directories")
    program_args = getattr(args, "program_args", [])
    if program_args[:1] == ["--"]:
        program_args = program_args[1:]
    if args.command == "deploy":
        script = 'mkdir -p "$HOME/turtbot_programs" && tar -xf - -C "$HOME/turtbot_programs"'
    else:
        script = None if args.command == "shell" else remote_script(
            args.command, getattr(args, "topic", None), getattr(args, "distro", None),
            getattr(args, "setup", None), getattr(args, "program", None), program_args)
    try:
        arguments = ssh_arguments(args.target, script, read_shell_config=args.command != "deploy", terminal=args.command == "run")
    except ValueError as exc:
        parser.error(str(exc))
    if not shutil.which("ssh"):
        parser.error("ssh is not installed")
    (PROJECT / ".robot").mkdir(exist_ok=True, mode=0o700)
    if args.command == "deploy":
        return subprocess.run(arguments, input=program_archive()).returncode
    os.execvp(arguments[0], arguments)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
