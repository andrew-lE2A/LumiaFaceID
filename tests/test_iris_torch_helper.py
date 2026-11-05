"""Exercise the torch helper transaction against a temporary fake LED node."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest


class IrisTorchHelperTests(unittest.TestCase):
    def setUp(self):
        self.shell = shutil.which('sh')
        self.assertIsNotNone(self.shell, 'A POSIX shell is required')
        self.script = Path(__file__).resolve().parents[1] / 'android/iris-camera-probe/iris-torch-server.sh'
        syntax = subprocess.run([self.shell, '-n', str(self.script)], capture_output=True, text=True)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def start_worker(self, directory):
        led = Path(directory) / 'brightness'
        led.write_text('0\n')
        process = subprocess.Popen(
            [self.shell, str(self.script), '--connection', str(led)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        return process, led

    @staticmethod
    def dispose(process):
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        for stream in (process.stdin, process.stdout):
            if stream is not None and not stream.closed:
                stream.close()

    def pulse(self, process):
        process.stdin.write('PULSE\n')
        process.stdin.flush()
        self.assertEqual(process.stdout.readline().strip(), 'ON')

    def test_stop_turns_fake_led_off_and_confirms(self):
        with tempfile.TemporaryDirectory() as directory:
            process, led = self.start_worker(directory)
            try:
                self.pulse(process)
                self.assertEqual(led.read_text().strip(), '14')
                stop_started = time.monotonic()
                process.stdin.write('STOP\n')
                process.stdin.flush()
                self.assertEqual(process.stdout.readline().strip(), 'OFF')
                self.assertLess(time.monotonic() - stop_started, 0.75,
                                'OFF acknowledgement waited for the watchdog deadline')
                self.assertEqual(process.wait(timeout=2), 0)
                self.assertEqual(led.read_text().strip(), '0')
            finally:
                self.dispose(process)

    def test_watchdog_turns_led_off_if_client_stalls(self):
        with tempfile.TemporaryDirectory() as directory:
            process, led = self.start_worker(directory)
            try:
                self.pulse(process)
                self.assertEqual(process.wait(timeout=1.5), 0)
                self.assertEqual(led.read_text().strip(), '0')
                self.assertEqual(process.stdout.readline().strip(), 'OFF')
            finally:
                self.dispose(process)

    def test_disconnect_and_signal_cleanup_turn_off_led(self):
        with tempfile.TemporaryDirectory() as directory:
            process, led = self.start_worker(directory)
            self.pulse(process)
            self.assertEqual(led.read_text().strip(), '14')
            process.stdin.close()
            process.wait(timeout=2)
            self.assertEqual(led.read_text().strip(), '0')
            self.dispose(process)

        with tempfile.TemporaryDirectory() as directory:
            process, led = self.start_worker(directory)
            try:
                self.pulse(process)
                process.terminate()
                process.wait(timeout=2)
                self.assertEqual(led.read_text().strip(), '0')
            finally:
                self.dispose(process)


if __name__ == '__main__':
    unittest.main()
