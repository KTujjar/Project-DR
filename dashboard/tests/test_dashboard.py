import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from dashboard.backend.ai import UnconfiguredAdapter
from dashboard.backend.app import create_app
from dashboard.backend.safety import ControlDenied, SafetyController
from dashboard.backend.state import SensorStore


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.time = 1.0
        self.commands = []
        self.control = SafetyController(enabled=True, publish=lambda v, w: self.commands.append((v, w)), clock=lambda: self.time)

    def test_default_disabled_controller_cannot_arm_or_move(self):
        controller = SafetyController(publish=lambda *args: self.fail("Unexpected publication"))
        with self.assertRaises(ControlDenied):
            controller.arm("browser")
        with self.assertRaises(ControlDenied):
            controller.command("browser", .05, 0)
        controller.stop()

    def test_command_timeout_zeros_and_revokes_lease(self):
        self.control.arm("a")
        self.control.command("a", .05, 0)
        self.time += .26
        self.control.heartbeat("a")
        self.control.tick()
        self.assertIsNone(self.control.owner)
        self.assertEqual(self.commands[-1], (0, 0))

    def test_connection_loss_and_heartbeat_timeout_zero_even_without_js(self):
        for cause in ("disconnect", "heartbeat"):
            self.control.arm("a")
            self.control.command("a", .04, .2)
            if cause == "disconnect":
                self.control.disconnect("a")
            else:
                self.time += .61
                self.control.tick()
            self.assertEqual(self.commands[-1], (0, 0))
            self.assertIsNone(self.control.owner)

    def test_other_browser_cannot_extend_or_use_a_lease(self):
        self.control.arm("a")
        with self.assertRaises(ControlDenied):
            self.control.arm("b")
        with self.assertRaises(ControlDenied):
            self.control.command("b", .05, 0)
        self.time += .61
        self.control.heartbeat("b")
        self.control.tick()
        self.assertIsNone(self.control.owner)

    def test_release_zeros_but_preserves_arm_and_limits_are_server_side(self):
        self.control.arm("a")
        self.control.command("a", 10, -10)
        self.assertEqual((self.control.target_linear,self.control.target_angular), (.08, -.5))
        self.time += .1
        self.control.tick()
        self.assertAlmostEqual(self.commands[-1][0], .012)
        self.assertAlmostEqual(self.commands[-1][1], -.08)
        self.control.stop()
        self.assertEqual(self.commands[-1], (0, 0))
        self.assertEqual(self.control.owner, "a")
        with self.assertRaises(ControlDenied):
            self.control.command("a", float("nan"), 0)

    def test_competing_publisher_stops_and_prevents_arming(self):
        self.control.arm("a")
        self.control.command("a", .04, 0)
        self.control.conflicts = lambda: 1
        self.control.tick()
        self.assertEqual(self.commands[-1], (0, 0))
        with self.assertRaises(ControlDenied):
            self.control.arm("a")

    def test_ramp_limits_independent_ticks_and_release_is_immediate(self):
        self.control.arm('a');self.control.command('a',.08,.5)
        self.assertEqual(self.commands[-1],(0,0))
        self.time+=.05;self.control.tick()
        self.assertAlmostEqual(self.commands[-1][0],.006)
        self.assertAlmostEqual(self.commands[-1][1],.04)
        self.control.stop();self.assertEqual(self.commands[-1],(0,0))
        self.assertEqual(self.control.target_linear,0)

    def test_zero_target_does_not_ramp_a_safety_stop(self):
        self.control.arm('a');self.control.command('a',.08,0)
        self.time+=.1;self.control.tick();self.assertGreater(self.commands[-1][0],0)
        self.control.command('a',0,0);self.assertEqual(self.commands[-1],(0,0))



class DashboardTests(unittest.TestCase):
    def test_mock_api_provenance_capture_and_ai(self):
        with tempfile.TemporaryDirectory() as directory:
            with TestClient(create_app("mock", directory)) as client:
                self.assertEqual(client.get("/").status_code, 200)
                health = client.get("/api/health").json()
                self.assertEqual(health["mode"], "mock")
                self.assertFalse(health["motion_enabled"])
                response = client.get("/api/camera")
                self.assertEqual(response.headers["x-sensor-provenance"], "mock")
                capture = client.post("/api/snapshots").json()
                self.assertEqual(capture["mode"], "mock")
                self.assertIn("synchronization", capture)
                self.assertTrue(Path(directory, capture["id"] + ".json").exists())
                ai = client.post("/api/snapshots/" + capture["id"] + "/interpret").json()
                self.assertEqual(ai["source"], "mock_response")
                self.assertIn("not an AI observation", ai["text"])

    def test_cross_origin_mutations_and_websockets_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with TestClient(create_app("mock", directory)) as client:
                self.assertEqual(client.post("/api/snapshots", headers={"Origin": "https://attacker.invalid"}).status_code, 403)
                with self.assertRaises(WebSocketDisconnect):
                    with client.websocket_connect("/ws", headers={"Origin": "https://attacker.invalid"}):
                        pass

    def test_mock_websocket_cannot_arm(self):
        with TestClient(create_app("mock")) as client:
            with client.websocket_connect("/ws", headers={"Origin": "http://testserver"}) as socket:
                first = socket.receive_json()
                self.assertEqual(first["mode"], "mock")
                socket.send_json({"action": "arm"})
                for _ in range(10):
                    message = socket.receive_json()
                    if message["type"] == "notice":
                        self.assertIn("disabled", message["message"])
                        break
                else:
                    self.fail("No disabled-motion notice")

    def test_missing_camera_never_produces_synchronized_hardware_capture(self):
        store = SensorStore("hardware")
        store.update("scan", {"ranges": [1]}, 100)
        store.update("odom", {"x": 0}, 100)
        capture = store.aligned_snapshot()
        self.assertFalse(capture["synchronized"])
        self.assertIn("camera", capture["synchronization"]["missing"])

    def test_hardware_startup_failure_never_falls_back_to_mock(self):
        with patch("dashboard.backend.ros_bridge.RosBridge", side_effect=RuntimeError("ROS unavailable")):
            with self.assertRaisesRegex(RuntimeError, "ROS unavailable"):
                with TestClient(create_app("hardware")):
                    pass

    def test_real_ai_does_not_fabricate_an_interpretation(self):
        response = asyncio.run(UnconfiguredAdapter().interpret({"mode": "hardware"}))
        self.assertEqual(response["status"], "unconfigured")
        self.assertIn("No image analysis", response["text"])

class ObstacleGuardTests(unittest.TestCase):
    def setUp(self):
        from dashboard.backend.obstacle_guard import ObstacleGuard
        import math
        self.time = 1.
        self.guard = ObstacleGuard(clock=lambda: self.time, bypass=False)
        self.scan = {'ranges': [2.] * 360, 'angle_min': 0., 'angle_increment': math.tau/360,
                     'range_min': .12, 'range_max': 3.5, 'frame_id': 'base_scan'}
        self.guard.update(self.scan)

    def test_fresh_complete_free_scan_allows_bounded_commands(self):
        for v,w in ((.08,0),(-.08,0),(0,.5),(.05,.2)):
            self.assertIsNone(self.guard.reason(v,w))

    def test_front_obstacle_blocks_forward_and_turn_but_allows_reverse(self):
        self.scan['ranges'][0] = .2
        self.guard.update(self.scan)
        self.assertIn('Obstacle', self.guard.reason(.05,0))
        self.assertIn('Obstacle', self.guard.reason(0,.3))
        self.assertIsNone(self.guard.reason(-.05,0))

    def test_reverse_obstacle_and_speed_dependent_margin(self):
        self.scan['ranges'][180] = .34
        self.guard.update(self.scan)
        self.assertIsNone(self.guard.reason(-.01,0))
        self.assertIn('Obstacle', self.guard.reason(-.08,0))

    def test_missing_stale_unknown_and_wrong_frame_fail_closed(self):
        self.time += .51
        self.assertIn('older', self.guard.reason(.01,0))
        self.scan['ranges'][10:40] = [None]*30
        self.guard.update(self.scan)
        self.assertIn('Unknown', self.guard.reason(.01,0))
        self.scan['frame_id'] = 'other_frame'
        self.assertIn('frame', self.guard.reason(.01,0))

    def test_partial_scan_cannot_claim_turn_coverage(self):
        self.scan['ranges'] = [2.]*180
        self.guard.update(self.scan)
        self.assertIn('Incomplete', self.guard.reason(0,.1))

    def test_ros_watchdog_veto_stops_and_disarms_without_browser_command(self):
        commands=[]
        control=SafetyController(enabled=True, guard=self.guard, clock=lambda:self.time,
                                 publish=lambda v,w:commands.append((v,w)))
        control.arm('a');control.command('a',.05,0)
        self.scan['ranges'][0]=.2;self.guard.update(self.scan)
        control.tick()
        self.assertEqual(commands[-1],(0,0));self.assertIsNone(control.owner)
        self.assertIn('Obstacle guard',control.reason)

    def test_guard_rejection_never_publishes_nonzero(self):
        self.scan['ranges'][0]=.2;self.guard.update(self.scan)
        commands=[]
        control=SafetyController(enabled=True,guard=self.guard,clock=lambda:self.time,
                                 publish=lambda v,w:commands.append((v,w)))
        control.arm('a')
        with self.assertRaises(ControlDenied):control.command('a',.05,0)
        self.assertEqual(commands,[(0,0)])

    def test_explicit_override_allows_obstacles_and_missing_scans_but_keeps_deadman(self):
        from dashboard.backend.obstacle_guard import ObstacleGuard
        guard=ObstacleGuard(clock=lambda:self.time,bypass=True)
        commands=[]
        control=SafetyController(enabled=True,guard=guard,clock=lambda:self.time,
                                 publish=lambda v,w:commands.append((v,w)))
        self.assertFalse(control.state()['armed'])
        self.assertIsNone(guard.reason(.08,0))  # No scan at all.
        self.assertEqual(guard.state()['status'],'bypassed')
        self.scan['ranges'][0]=.2;guard.update(self.scan)
        self.assertIn('Obstacle',guard.state()['directions']['forward'])
        control.arm('operator');self.time+=.05;control.command('operator',1.,0)
        self.assertGreater(commands[-1][0],0)
        self.assertLessEqual(control.target_linear,.08)
        self.time+=.26;control.tick()
        self.assertEqual(commands[-1],(0.,0.))
        self.assertIsNone(control.owner)
        self.assertIn('deadman',control.reason)

    def test_override_keeps_release_heartbeat_and_publisher_conflict_stops(self):
        from dashboard.backend.obstacle_guard import ObstacleGuard
        commands=[];conflicts=[0]
        control=SafetyController(enabled=True,guard=ObstacleGuard(bypass=True),clock=lambda:self.time,
                                 conflicts=lambda:conflicts[0],publish=lambda v,w:commands.append((v,w)))
        control.arm('operator');self.time+=.05;control.command('operator',.05,0)
        control.command('operator',0,0)
        self.assertEqual(commands[-1],(0.,0.))
        self.time+=.61;control.tick();self.assertIsNone(control.owner)
        self.assertIn('heartbeat',control.reason)
        control.arm('operator');conflicts[0]=1;control.tick()
        self.assertIsNone(control.owner);self.assertEqual(commands[-1],(0.,0.))
        self.assertIn('Competing',control.reason)


if __name__ == "__main__":
    unittest.main()
