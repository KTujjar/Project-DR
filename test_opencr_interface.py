"""Protocol decoding and motion cleanup tests; never open a hardware port."""

import struct
import unittest

from opencr_interface import OpenCR, OpenCRError, decode_snapshot, drive_for


class SimulatedBoard:
    def __init__(self):
        self.events = []
        self.now = 0.0
        self.interrupt = False
        self.fail_velocity = False

    def snapshot(self):
        return {"wheels": {"connected": True, "torque_enabled": True}}

    def read_int(self, address, length):
        return 0

    def zero_velocity(self):
        self.events.append(("zero",))

    def write(self, address, data):
        self.events.append((address, data))

    def set_velocity(self, linear, angular):
        if self.fail_velocity:
            raise OpenCRError("simulated cable failure")
        self.events.append(("velocity", linear, angular))

    def sleep(self, seconds):
        if self.interrupt:
            raise KeyboardInterrupt
        self.now += seconds

    def drive(self, linear=0.03, angular=0, seconds=0.3):
        drive_for(self, linear, angular, seconds, clock=lambda: self.now, sleep=self.sleep)


class OpenCRTests(unittest.TestCase):
    def test_decode_firmware_byte_layout_and_signed_encoder_values(self):
        payload = bytearray(172)
        struct.pack_into("<I", payload, 42 - 10, 1217)
        struct.pack_into("<3f", payload, 60 - 10, -0.125, 0.25, 0)
        struct.pack_into("<2i", payload, 136 - 10, -40, 5000)
        struct.pack_into("<2B", payload, 148 - 10, 1, 1)
        state = decode_snapshot(payload)
        self.assertEqual(state["battery"]["voltage_V"], 12.17)
        self.assertEqual(state["imu"]["angular_velocity_xyz"], (-0.125, 0.25, 0))
        self.assertEqual(state["wheels"]["position_ticks_left_right"], (-40, 5000))
        self.assertTrue(state["wheels"]["torque_enabled"])

    def test_timed_drive_starts_and_ends_with_zero_velocity(self):
        board = SimulatedBoard()
        board.drive()
        self.assertEqual(board.events[0], ("zero",))
        self.assertEqual(board.events[-1], ("zero",))
        self.assertLessEqual(board.now, 0.3)
        self.assertTrue(any(event[0] == 19 for event in board.events))

    def test_interrupt_sends_zero_velocity(self):
        board = SimulatedBoard()
        board.interrupt = True
        with self.assertRaises(KeyboardInterrupt):
            board.drive()
        self.assertEqual(board.events[-1], ("zero",))

    def test_transport_failure_attempts_zero_velocity(self):
        board = SimulatedBoard()
        board.fail_velocity = True
        with self.assertRaisesRegex(OpenCRError, "cable failure"):
            board.drive()
        self.assertEqual(board.events[-1], ("zero",))

    def test_stop_attempts_both_axes_when_first_write_fails(self):
        board = OpenCR.__new__(OpenCR)
        attempted = []

        def write(address, data):
            attempted.append((address, data))
            if address == 150:
                raise OpenCRError("simulated first-axis failure")

        board.write = write
        with self.assertRaises(OpenCRError):
            board.zero_velocity()
        self.assertEqual(attempted, [(150, bytes(4)), (170, bytes(4))])

    def test_invalid_motion_limits_send_no_commands(self):
        for linear, angular, seconds in [(0.06, 0, 1), (0, 0.6, 1), (0.03, 0, 3), (float("nan"), 0, 1)]:
            board = SimulatedBoard()
            with self.assertRaises(OpenCRError):
                board.drive(linear, angular, seconds)
            self.assertEqual(board.events, [])

    def test_debug_mode_refuses_motion_without_watchdog(self):
        board = SimulatedBoard()
        board.read_int = lambda address, length: 1
        with self.assertRaisesRegex(OpenCRError, "watchdog"):
            board.drive()
        self.assertEqual(board.events, [])


if __name__ == "__main__":
    unittest.main()
