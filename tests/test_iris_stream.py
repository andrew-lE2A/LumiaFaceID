"""Run production sensor-stream code with simulated CCI and power operations."""
from pathlib import Path
import re
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
            self.assertIn('28 actual production-sequence scenarios passed', run.stdout)
            baseline = re.search(r'Baseline: (\d+) startup transactions, (\d+) profile bursts, '
                                 r'(\d+) read transactions', run.stdout)
            self.assertIsNotNone(baseline, run.stdout)
            startup, bursts, reads = map(int, baseline.groups())
            self.assertGreater(startup, bursts)
            self.assertEqual(bursts, (87 + 7) // 8 + (30 + 7) // 8)
            self.assertEqual(reads, 1 + 20 + 16 + 20)
            # Baseline plus all startup/read failures, three stalled counters,
            # twenty stalled-counter/post-snapshot failures, two mismatches,
            # four stop failures, a wrong post-reset identity, and four
            # no-stream/profile-gate scenarios.
            expected = 1 + startup + reads + 3 + 20 + 2 + 4 + 1 + 4
            self.assertIn(f'{expected} actual integrated stream scenarios passed', run.stdout)


if __name__ == '__main__':
    unittest.main()
