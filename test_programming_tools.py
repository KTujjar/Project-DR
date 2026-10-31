"""Check IPv6 transport and program packaging without contacting a robot."""

import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

import turtlectl


class ProgrammingToolsTests(unittest.TestCase):
    def test_scoped_ipv6_is_a_single_ssh_destination(self):
        target = "ubuntu@fe80::ba27:ebff:fe79:d40f%en9"
        args = turtlectl.ssh_arguments(target, "hostname")
        self.assertIn(target, args)
        self.assertEqual(args.count(target), 1)
        self.assertEqual(turtlectl.validate_target("ubuntu@[fe80::1%en9]"), "ubuntu@fe80::1%en9")

    def test_destinations_cannot_inject_ssh_options_or_shell_syntax(self):
        for target in ("-oProxyCommand=anything", "user@host;anything", "user@fe80::1%en9;anything", "user@host\nanything", "user@@host"):
            with self.assertRaises(ValueError, msg=target):
                turtlectl.validate_target(target)

    def test_program_arguments_remain_literal_on_remote_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "injection-marker"
            binary = root / "python3"
            binary.write_text('#!/bin/sh\nprintf "%s\\0" "$@"\n')
            binary.chmod(0o755)
            arguments = ["two words", "$(touch " + str(marker) + ")", "; echo unsafe", "'quoted'"]
            script = turtlectl.remote_script("run", program="example.py", program_args=arguments)
            result = subprocess.run(["/bin/bash", "-c", script], env={**os.environ, "PATH": str(root) + ":/usr/bin:/bin"}, capture_output=True, check=True)
            actual = result.stdout.decode().split("\0")[:-1]
            self.assertTrue(actual[0].endswith("/turtbot_programs/example.py"))
            self.assertEqual(actual[1:], arguments)
            self.assertFalse(marker.exists())

    def test_upload_contains_only_program_sources(self):
        with tarfile.open(fileobj=io.BytesIO(turtlectl.program_archive())) as archive:
            names = archive.getnames()
            self.assertIn("ros2_sensor_report.py", names)
            self.assertTrue(all("/" not in name and name.endswith((".py", ".md")) for name in names))
            self.assertFalse(any(".robot" in name or ".venv" in name for name in names))


if __name__ == "__main__":
    unittest.main()
