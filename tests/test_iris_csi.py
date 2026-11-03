"""Exercise production CSI ownership and sensor ordering with fault injection."""
from pathlib import Path
import subprocess
import tempfile
import unittest


class IrisCsiTests(unittest.TestCase):
    def test_production_receiver_lifecycle(self):
        self.run_harness('iris_csi_host.c', '20 production receiver lifecycle scenarios passed')

    def test_sensor_receiver_integration(self):
        self.run_harness('iris_csi_sequence_host.c', '5 production sensor/receiver integration scenarios passed')

    def run_harness(self, filename, expected):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'test'
            build = subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror',
                                    str(Path(__file__).with_name(filename)), '-o', str(output)],
                                   capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(output)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn(expected, run.stdout)
