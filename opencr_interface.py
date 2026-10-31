"""Direct TurtleBot3 OpenCR interface using ROBOTIS DYNAMIXEL protocol 2.

Register definitions and scaling follow the official TurtleBot3 ROS 2 firmware:
https://github.com/ROBOTIS-GIT/OpenCR/blob/master/arduino/opencr_arduino/opencr/libraries/turtlebot3_ros2/src/turtlebot3/turtlebot3.cpp
"""

import argparse
from datetime import datetime, timezone
import fcntl
import json
import math
import signal
import struct
import sys
import termios
import time
from zoneinfo import ZoneInfo


class OpenCRError(RuntimeError):
    pass


def decode_snapshot(data):
    if len(data) != 172:
        raise OpenCRError(f"Expected 172 sensor bytes, received {len(data)}")

    def unpack(fmt, address):
        return struct.unpack_from("<" + fmt, data, address - 10)

    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "uptime_ms": unpack("I", 10)[0],
        "device_status": unpack("b", 18)[0],
        "battery": {
            "voltage_V": unpack("I", 42)[0] / 100,
            "firmware_estimate_percent": unpack("I", 46)[0] / 100,
        },
        "imu": {
            "angular_velocity_xyz": unpack("3f", 60),
            "linear_acceleration_xyz": unpack("3f", 72),
            "magnetic_field_xyz": unpack("3f", 84),
            "orientation_wxyz": unpack("4f", 96),
        },
        "wheels": {
            "connected": bool(unpack("B", 148)[0]),
            "torque_enabled": bool(unpack("B", 149)[0]),
            "position_ticks_left_right": unpack("2i", 136),
            "velocity_raw_left_right": unpack("2i", 128),
            "current_raw_left_right": unpack("2i", 120),
        },
        "buttons": tuple(bool(x) for x in unpack("2B", 26)),
    }


class OpenCR:
    def __init__(self, device=None):
        try:
            from dynamixel_sdk import COMM_SUCCESS, PacketHandler, PortHandler
            from serial.tools import list_ports
        except ImportError as exc:
            raise OpenCRError("Run with .venv/bin/python, or install requirements.txt in a virtual environment") from exc
        if device is None:
            ports = [p.device for p in list_ports.comports()
                     if "OpenCR" in (p.product or "")]
            if len(ports) != 1:
                raise OpenCRError(f"Expected one OpenCR USB port, found {ports}. Reconnect it or specify --port.")
            device = ports[0]
        self.device = device
        self.packet = PacketHandler(2.0)
        self.port = PortHandler(device)
        self.success = COMM_SUCCESS
        try:
            if not self.port.openPort() or not self.port.setBaudRate(1_000_000):
                raise OpenCRError("Could not open the OpenCR at 1,000,000 baud")
            # Exclude another local process from opening this controller concurrently.
            fcntl.ioctl(self.port.ser.fileno(), termios.TIOCEXCL)
            model, result, error = self.packet.ping(self.port, 200)
            self._check(result, error)
            if model != 0x5000:
                raise OpenCRError(f"Unexpected controller model {model}; no commands will be sent")
            model_info = self.read_int(2, 4)
            self.info = {
                "port": device,
                "protocol": "DYNAMIXEL 2.0 / TurtleBot3 ROS 2 firmware",
                "controller_id": 200,
                "controller_model_number": model,
                "robot_model_code": model_info,
                "robot_model": {1: "Burger", 2: "Waffle", 3: "Waffle with OpenManipulator"}.get(model_info, "unknown"),
                "firmware_version": self.read_int(6, 1),
            }
        except BaseException:
            self.close()
            raise

    def _check(self, result, error):
        if result != self.success:
            raise OpenCRError(self.packet.getTxRxResult(result))
        if error:
            raise OpenCRError(self.packet.getRxPacketError(error))

    def read(self, address, length):
        data, result, error = self.packet.readTxRx(self.port, 200, address, length)
        self._check(result, error)
        if len(data) != length:
            raise OpenCRError(f"Short read at register {address}")
        return bytes(data)

    def read_int(self, address, length):
        return int.from_bytes(self.read(address, length), "little")

    def snapshot(self):
        return decode_snapshot(self.read(10, 172))

    def write(self, address, data):
        # No arbitrary register writes, bootloader requests, or firmware flashing.
        permitted = {19: 1, 50: 1, 150: 4, 170: 4}
        if self.info["firmware_version"] != 5 or self.info["robot_model_code"] not in (1, 2, 3):
            raise OpenCRError("Writes require a recognized TurtleBot3 with firmware version 5")
        if permitted.get(address) != len(data):
            raise OpenCRError("This register write is not supported")
        result, error = self.packet.writeTxRx(self.port, 200, address, len(data), list(data))
        self._check(result, error)

    def set_velocity(self, linear, angular):
        # Firmware stores hundredths of m/s and rad/s as signed little-endian integers.
        self.write(150, struct.pack("<i", round(linear * 100)))
        self.write(170, struct.pack("<i", round(angular * 100)))

    def zero_velocity(self):
        errors = []
        for address in (150, 170):
            try:
                self.write(address, bytes(4))
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise OpenCRError("Could not send all zero velocity commands: " + "; ".join(errors))

    def close(self):
        self.port.closePort()


def drive_for(board, linear, angular, seconds, clock=time.monotonic, sleep=time.sleep):
    if not all(math.isfinite(x) for x in (linear, angular, seconds)):
        raise OpenCRError("Motion values must be finite")
    if abs(linear) > 0.05 or abs(angular) > 0.5 or not 0 < seconds <= 2:
        raise OpenCRError("Limits: 0.05 m/s, 0.5 rad/s, and 2 seconds per command")
    state = board.snapshot()
    if not state["wheels"]["connected"] or not state["wheels"]["torque_enabled"]:
        raise OpenCRError("Wheel motors must already be connected and enabled")
    if board.read_int(14, 1) != 0:
        raise OpenCRError("Debug mode is active or the control table differs; refusing motion without the watchdog")
    count = board.read_int(19, 1)
    active_error = None
    try:
        board.zero_velocity()
        deadline = clock() + seconds
        while clock() < deadline:
            count = (count + 1) % 256
            board.write(19, bytes([count]))
            board.set_velocity(linear, angular)
            sleep(min(0.1, max(0, deadline - clock())))
    except BaseException as exc:
        active_error = exc
        raise
    finally:
        try:
            board.zero_velocity()
        except Exception as exc:
            if active_error is None:
                raise
            print(f"Stop transmission failed: {exc}. Heartbeats have stopped.", file=sys.stderr)


def configure_parser(parser):
    actions = parser.add_subparsers(dest="usb_command", required=True)
    for name, description in {
        "status": "Read controller identity, battery, IMU, buttons, and wheel feedback",
        "watch": "Continuously read live sensors; Ctrl-C to end",
        "beep": "Play the firmware's connection melody",
        "stop": "Zero the velocity commands from this USB interface",
        "drive": "Run one brief, slow base velocity command",
    }.items():
        action = actions.add_parser(name, help=description)
        action.add_argument("--port", help="Serial device; a single OpenCR is selected automatically")
        if name == "watch":
            action.add_argument("--hz", type=float, default=2, help="Readings per second, 0.2–10")
            action.add_argument("--count", type=int, default=0, help="Number of samples; 0 means until Ctrl-C")
            action.add_argument("--json", action="store_true", help="Emit one full JSON snapshot per line")
        elif name == "drive":
            action.add_argument("--linear", type=float, default=0, help="m/s, limited to ±0.05")
            action.add_argument("--angular", type=float, default=0, help="rad/s, limited to ±0.5")
            action.add_argument("--seconds", type=float, default=1, help="Duration, maximum 2 seconds")


def run(args):
    if args.usb_command == "watch" and (not 0.2 <= args.hz <= 10 or args.count < 0):
        raise OpenCRError("Use --hz between 0.2 and 10 and a nonnegative --count")
    if args.usb_command == "drive" and args.linear == 0 and args.angular == 0:
        raise OpenCRError("Specify --linear or --angular, or use stop")
    board = OpenCR(args.port)
    try:
        if args.usb_command == "status":
            print(json.dumps({"controller": board.info, **board.snapshot()}, indent=2))
        elif args.usb_command == "watch":
            n = 0
            while args.count == 0 or n < args.count:
                state = board.snapshot()
                if args.json:
                    print(json.dumps(state), flush=True)
                else:
                    display_time = datetime.fromisoformat(state["captured_at"]).astimezone(ZoneInfo("America/New_York"))
                    print(f"{display_time:%H:%M:%S %Z}  "
                          f"battery={state['battery']['voltage_V']:.2f} V  "
                          f"wheels={state['wheels']['position_ticks_left_right']} ticks  "
                          f"gyro={tuple(round(x, 3) for x in state['imu']['angular_velocity_xyz'])}  "
                          f"buttons={state['buttons']}", flush=True)
                n += 1
                if args.count == 0 or n < args.count:
                    time.sleep(1 / args.hz)
        elif args.usb_command == "beep":
            board.write(50, b"\x01")
            print("Connection melody requested")
        elif args.usb_command == "stop":
            board.zero_velocity()
            print("USB linear and angular velocity commands set to zero")
        elif args.usb_command == "drive":
            drive_for(board, args.linear, args.angular, args.seconds)
            print("Timed velocity command completed; zero velocity sent")
    finally:
        board.close()
    return 0


def handle_termination(signum, frame):
    raise KeyboardInterrupt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    configure_parser(parser)
    args = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, handle_termination)
    try:
        return run(args)
    except (OpenCRError, OSError) as exc:
        print(f"OpenCR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
