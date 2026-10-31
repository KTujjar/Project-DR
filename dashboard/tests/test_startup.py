import hashlib,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from scripts import pi_runtime, missionctl

class StartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'dashboard/backend').mkdir(parents=True)
        self.patches=[patch.object(pi_runtime,'ROOT',self.root),patch.object(pi_runtime,'STATE',self.root/'state.json'),patch.object(pi_runtime,'status',return_value={'test':True})]
        for p in self.patches:p.start()
        self.healthy={'version':'mission-v1','source_revision':hashlib.sha256(b'').hexdigest()[:16]}
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def test_reuse_existing_drivers_and_backend_without_launch(self):
        with patch.object(pi_runtime,'drivers',return_value={'lidar':[1],'opencr':[2]}),patch.object(pi_runtime,'health',return_value=self.healthy),patch.object(pi_runtime,'spawn') as spawn:
            pi_runtime.ensure(initial=True);spawn.assert_not_called()
    def test_duplicate_or_partial_hardware_never_gets_competing_launch(self):
        for drivers in ({'lidar':[1,2],'opencr':[3]},{'lidar':[1],'opencr':[]}):
            with patch.object(pi_runtime,'drivers',return_value=drivers),patch.object(pi_runtime,'spawn') as spawn:
                with self.assertRaises(RuntimeError):pi_runtime.ensure(initial=True)
                spawn.assert_not_called()
    def test_supervisor_never_automatically_restarts_missing_hardware(self):
        with patch.object(pi_runtime,'drivers',return_value={'lidar':[],'opencr':[]}),patch.object(pi_runtime,'health',return_value=self.healthy),patch.object(pi_runtime,'spawn') as spawn:
            pi_runtime.ensure(initial=False);spawn.assert_not_called()
    def test_crashed_backend_restarts_disarmed_without_restarting_drivers(self):
        with patch.object(pi_runtime,'drivers',return_value={'lidar':[1],'opencr':[2]}),patch.object(pi_runtime,'health',return_value=None),patch.object(pi_runtime,'spawn',return_value={'pid':123,'start':'unit'}) as spawn:
            pi_runtime.ensure(initial=False)
            self.assertEqual(spawn.call_args.args[0],'dashboard')
            self.assertEqual(spawn.call_args.args[2]['TURTBOT_ALLOW_MOTION'],'0')

    def test_override_is_explicit_and_passed_to_recovered_backend(self):
        with self.assertRaises(ValueError):pi_runtime.ensure(bypass_obstacles=True)
        with patch.object(pi_runtime,'drivers',return_value={'lidar':[1],'opencr':[2]}),patch.object(pi_runtime,'health',return_value=None),patch.object(pi_runtime,'spawn',return_value={'pid':123,'start':'unit'}) as spawn:
            pi_runtime.ensure(allow_motion=True,bypass_obstacles=True)
            self.assertEqual(spawn.call_args.args[2]['TURTBOT_ALLOW_MOTION'],'1')
            self.assertEqual(spawn.call_args.args[2]['TURTBOT_BYPASS_OBSTACLES'],'1')

    def test_changed_motion_mode_requires_owned_restart(self):
        with patch.object(pi_runtime,'drivers',return_value={'lidar':[1],'opencr':[2]}),patch.object(pi_runtime,'health',return_value=self.healthy),patch.object(pi_runtime,'load',return_value={}),patch.object(pi_runtime,'spawn') as spawn:
            with self.assertRaisesRegex(RuntimeError,'ownership is unknown'):
                pi_runtime.ensure(allow_motion=True,bypass_obstacles=True)
            spawn.assert_not_called()

class ConnectionDefaultsTests(unittest.TestCase):
    def test_fresh_clone_can_select_mock_without_private_connection_file(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(missionctl,'ROOT',Path(tmp)),patch.dict('os.environ',{},clear=True):
            self.assertEqual(missionctl.defaults(),'turtle@turtlebot3.local')
    def test_explicit_target_does_not_require_private_connection_file(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(missionctl,'ROOT',Path(tmp)),patch.dict('os.environ',{'TURTBOT_TARGET':'user@robot.example'},clear=True):
            self.assertEqual(missionctl.defaults(),'user@robot.example')
if __name__=='__main__':unittest.main()
