"""Compile and run the Android probe's pure-Java diagnostics on synthetic data."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class IrisProbeHostTests(unittest.TestCase):
    def test_geometry_boundary_and_phase_code_prototypes(self):
        compiler = shutil.which('javac')
        runtime = shutil.which('java')
        self.assertIsNotNone(compiler, 'A JDK is required for the iris probe host checks')
        self.assertIsNotNone(runtime, 'A JRE is required for the iris probe host checks')
        root = Path(__file__).resolve().parents[1]
        source_root = root / 'android/iris-camera-probe/src/com/lumia/irisprobe'
        test_source = Path(__file__).parent / 'iris_probe_host/IrisProbeHostTest.java'
        sources = [
            source_root / 'EyeRegionGeometry.java',
            source_root / 'CircularBoundaryProposal.java',
            source_root / 'DiagnosticFrameQuality.java',
            source_root / 'LogGaborIrisCodePrototype.java',
            test_source,
        ]
        with tempfile.TemporaryDirectory() as directory:
            build = subprocess.run(
                [compiler, '-source', '8', '-target', '8', '-d', directory,
                 *map(str, sources)], capture_output=True, text=True, timeout=30)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run(
                [runtime, '-cp', directory, 'com.lumia.irisprobe.IrisProbeHostTest'],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('synthetic checks passed', run.stdout)


if __name__ == '__main__':
    unittest.main()
