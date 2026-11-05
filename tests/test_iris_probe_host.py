"""Compile and run the Android probe's pure-Java diagnostics on synthetic data."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class IrisProbeHostTests(unittest.TestCase):
    @staticmethod
    def java_method_body(source, signature):
        start = source.index(signature)
        opening = source.index('{', start)
        depth = 0
        for index in range(opening, len(source)):
            if source[index] == '{':
                depth += 1
            elif source[index] == '}':
                depth -= 1
                if depth == 0:
                    return source[opening + 1:index]
        raise AssertionError(f'Unterminated Java method: {signature}')

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
            source_root / 'YuvPlaneCopier.java',
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

    def test_ir_pulse_uses_in_memory_analysis_not_the_save_path(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / 'android/iris-camera-probe/src/com/lumia/irisprobe/IrisProbeActivity.java').read_text()
        pulse = self.java_method_body(source, 'private void pulseAndCaptureOnce()')
        request = self.java_method_body(source, 'private void requestPulseAnalysisFrame(CountDownLatch frameComplete)')
        self.assertIn('requestPulseAnalysisFrame(frameComplete)', pulse)
        self.assertIn('frameComplete.await(850, TimeUnit.MILLISECONDS)', pulse)
        self.assertNotIn('captureOneFrame(', pulse)
        self.assertNotIn('saveNextFrame', pulse)
        self.assertIn('analyzeNextFrame = true', request)
        self.assertNotIn('saveYuvFrame(', request)

        reader_start = source.index('frameReader.setOnImageAvailableListener')
        reader_end = source.index('}, cameraHandler);', reader_start)
        reader = source[reader_start:reader_end]
        self.assertLess(reader.index('signalPulseFrameDelivery()'), reader.index('analyzeImageInMemory(image, compare)'))


if __name__ == '__main__':
    unittest.main()
