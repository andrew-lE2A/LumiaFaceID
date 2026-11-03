"""Run production sensor-stream code with simulated CCI and power operations."""
from pathlib import Path
import subprocess
import tempfile
import unittest


class IrisStreamTests(unittest.TestCase):
    def test_production_stream_program_failure_stop_and_power_unwind(self):
        source = Path(__file__).with_name('iris_stream_host.c')
        with tempfile.TemporaryDirectory() as directory:
            program = Path(directory) / 'stream-test'
            build = subprocess.run(['cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror',
                                    str(source), '-o', str(program)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(program)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('160 actual integrated stream scenarios passed', run.stdout)


if __name__ == '__main__':
    unittest.main()
