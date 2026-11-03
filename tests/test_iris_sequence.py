"""Build and exercise the actual driver sequence with simulated kernel APIs."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class IrisSequenceTests(unittest.TestCase):
    def test_production_sequence_success_failures_unwind_and_blocking(self):
        compiler = shutil.which('cc')
        self.assertIsNotNone(compiler, 'A host C compiler is required for kernel sequence tests')
        source = Path(__file__).with_name('iris_sequence_host.c')
        with tempfile.TemporaryDirectory() as temporary:
            program = Path(temporary) / 'iris-sequence-test'
            build = subprocess.run([compiler, '-std=gnu99', '-Wall', '-Wextra', '-Werror',
                                    str(source), '-o', str(program)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(program)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('28 actual production-sequence scenarios passed', run.stdout)


if __name__ == '__main__':
    unittest.main()
