"""Profile boundary tests; no original calibration bytes are redistributed."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/prepare_iris_stream.py'
SPEC = importlib.util.spec_from_file_location('prepare_iris_stream', SCRIPT)
prepare = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(SCRIPT.parent))
try:
    SPEC.loader.exec_module(prepare)
finally:
    sys.path.pop(0)


class StreamProfileTests(unittest.TestCase):
    def test_changed_input_cannot_generate_a_profile(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported DCC'):
            prepare.prepare(bytes(prepare.DCC_SIZE))

    def test_selection_excludes_override_block_and_checks_program_hash(self):
        idle = b'\x30\x00\x01' * 87 + b'\0\0\0'
        mode = b'\x03\x4c\x05' * 30 + b'\0\0\0'
        blocks = [(0, 0, idle), (5, 0, b'never select'), (0xFF00, 0, mode)]
        # Mock only the source identity/directory boundary to reach the separate
        # program-hash rejection; this does not claim genuine input acceptance.
        with mock.patch.object(prepare, 'inspect_dcc'), mock.patch.object(
                prepare, 'parse_directory', return_value=blocks):
            with self.assertRaisesRegex(ValueError, 'program digest'):
                prepare.prepare(b'fixture')

    def test_cli_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'source', Path(directory) / 'output'
            source.write_bytes(bytes(prepare.DCC_SIZE))
            output.write_text('existing evidence\n')
            with mock.patch.object(prepare, 'prepare', return_value='fixture\n'):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(prepare.main([str(source), '--output', str(output)]), 1)
            self.assertEqual(output.read_text(), 'existing evidence\n')

    def test_download_is_pinned_https_and_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            response = io.BytesIO(bytes(prepare.DCC_SIZE + 100))
            with mock.patch.object(prepare.urllib.request, 'urlopen', return_value=response) as fetch:
                with mock.patch.object(prepare, 'prepare', return_value='fixture\n') as boundary:
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(prepare.main(['--download', '--output', str(output)]), 0)
            self.assertEqual(len(boundary.call_args.args[0]), prepare.DCC_SIZE + 1)
            url = fetch.call_args.args[0]
            self.assertTrue(url.startswith('https://raw.githubusercontent.com/'))
            self.assertIn(prepare.SOURCE_COMMIT, url)
            self.assertTrue(url.endswith(prepare.SOURCE_PATH))

    def test_invalid_download_creates_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            with mock.patch.object(prepare.urllib.request, 'urlopen', return_value=io.BytesIO(b'bad')):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(prepare.main(['--download', '--output', str(output)]), 1)
            self.assertFalse(output.exists())

    def test_interrupted_download_is_reported_without_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            response = mock.MagicMock()
            response.__enter__.return_value.read.side_effect = prepare.http.client.IncompleteRead(b'partial')
            with mock.patch.object(prepare.urllib.request, 'urlopen', return_value=response):
                errors = io.StringIO()
                with contextlib.redirect_stderr(errors):
                    self.assertEqual(prepare.main(['--download', '--output', str(output)]), 1)
            self.assertIn('Preparation failed:', errors.getvalue())
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
