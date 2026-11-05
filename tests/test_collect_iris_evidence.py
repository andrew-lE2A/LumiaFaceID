import sys
import tempfile
import contextlib
import io
from unittest import mock
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import collect_iris_evidence as evidence


def clock_log():
    return ''.join(
        f'RXCLK sample={sample} clock={clock} rate_before_hz=200000000 '
        'enable_before=1 measured_hz=199999414 rate_after_hz=200000000 enable_after=1\n'
        for sample in range(1, 7) for clock in evidence.CLOCK_SETS[2])


class FakeAdb:
    def __init__(self, paths=None, changed=False, failed=None):
        self.commands = []
        self.status_reads = 0
        self.paths = paths if paths is not None else ['/data/local/tmp/cityman-iris-rxclk.ABC123']
        self.changed = changed
        self.failed = failed

    def shell(self, command):
        self.commands.append(command)
        status = 'status=failed errno=-110 attempts=1 cleanup_errno=0\n'
        if command == evidence.STATUS_COMMAND:
            self.status_reads += 1
            output = status if not self.changed or self.status_reads == 1 else 'changed\n'
        elif command == evidence.SNAPSHOT_COMMAND:
            output = ''.join(f'FILE {name}\n' + (status if name == "result" else "saved\n") + 'END\n'
                             for name in evidence.FILES)
        elif command == evidence.LOG_LIST_COMMAND:
            output = '\n'.join(self.paths)
        elif command.startswith('cat /data/local/tmp/cityman-iris-rxclk.'):
            output = clock_log()
        elif command == evidence.SERVICES_COMMAND:
            output = 'cameraserver=running\n'
        elif command == 'cat /proc/version':
            output = 'Linux #8\n'
        else:
            raise AssertionError('Unexpected command: ' + command)
        return {'status': 'error' if command == self.failed else 'ok',
                'stdout': output, 'stderr': 'read failed' if command == self.failed else ''}


class CollectIrisEvidenceTests(unittest.TestCase):
    def test_transition_and_disabled_samples_are_not_stable_enabled(self):
        raw = clock_log().replace('enable_before=1', 'enable_before=0', 1)
        rows = evidence.parse_rxclk(raw)
        self.assertFalse(rows[0]['stable_enabled'])
        self.assertTrue(rows[1]['stable_enabled'])
        raw = clock_log().replace('rate_after_hz=200000000', 'rate_after_hz=240000000', 1)
        self.assertFalse(evidence.parse_rxclk(raw)[0]['stable_enabled'])

    def test_incomplete_duplicate_and_non_numeric_samples_rejected(self):
        for raw in (clock_log().split('\n', 1)[1],
                    clock_log().replace('sample=2', 'sample=1', 1),
                    clock_log().replace('measured_hz=199999414', 'measured_hz=error', 1),
                    clock_log() + 'sampler failed\n'):
            with self.subTest(raw=raw[:100]), self.assertRaises(ValueError):
                evidence.parse_rxclk(raw)

    def test_incomplete_or_duplicate_snapshot_rejected(self):
        for raw in ('FILE result\nsaved\n', 'FILE result\nsaved\nEND\n' * 2):
            with self.assertRaises(ValueError):
                evidence.parse_snapshot(raw)

    def test_collect_uses_only_fixed_read_commands(self):
        adb = FakeAdb()
        report = evidence.collect(adb)
        self.assertEqual(len(report['saved_receiver_clock_logs'][0]['samples']), 30)
        self.assertEqual(adb.status_reads, 2)
        self.assertEqual(set(adb.commands), {
            evidence.STATUS_COMMAND, evidence.SNAPSHOT_COMMAND, evidence.LOG_LIST_COMMAND,
            evidence.SERVICES_COMMAND, 'cat /proc/version',
            'cat /data/local/tmp/cityman-iris-rxclk.ABC123'})
        self.assertNotIn('serial', report)

    def test_device_supplied_shell_path_is_rejected_before_read(self):
        adb = FakeAdb(paths=['/data/local/tmp/cityman-iris-rxclk.ABC123; reboot'])
        with self.assertRaisesRegex(ValueError, 'path'):
            evidence.collect(adb)
        self.assertFalse(any(command.startswith('cat /data/local/tmp') for command in adb.commands))

    def test_changed_result_or_failed_read_refuses_report(self):
        for adb in (FakeAdb(changed=True), FakeAdb(failed=evidence.SNAPSHOT_COMMAND)):
            with self.assertRaises(ValueError):
                evidence.collect(adb)

    def test_existing_output_refuses_before_adb_access(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'evidence.json'
            output.write_text('original evidence')
            with mock.patch.object(evidence, 'Adb') as adb, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(evidence.main(['--output', str(output)]), 1)
                adb.assert_not_called()
            self.assertEqual(output.read_text(), 'original evidence')

    def test_clock_logs_can_be_excluded_from_a_new_non_clock_run(self):
        adb = FakeAdb()
        report = evidence.collect(adb, include_clock_logs=False)
        self.assertFalse(report['clock_logs_requested'])
        self.assertEqual(report['saved_receiver_clock_logs'], [])
        self.assertNotIn(evidence.LOG_LIST_COMMAND, adb.commands)

    def test_missing_clock_log_retains_saved_diagnostic(self):
        report = evidence.collect(FakeAdb(paths=[]))
        self.assertEqual(report['saved_receiver_clock_logs'], [])
        self.assertIn('attempts=1', report['diagnostic_files']['result'])


if __name__ == '__main__':
    unittest.main()
