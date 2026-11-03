"""Exercise the actual device helper with simulated init services and sysfs.

Only the absolute sysfs root is redirected into a fixture. The shell control
flow and write are unchanged; Android commands are supplied through PATH.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SERVICES = ['cameraserver', 'vendor.camera-provider-2-4', 'qcamerasvr']
INITIAL = ('status=ready stage=idle errno=0 model=0x0000 cleanup_errno=0 '
           'attempts=0 blocked=0 rail_uv=0')
SUCCESS = ('status=identified stage=model-read errno=0 model=0x0861 '
           'cleanup_errno=0 attempts=1 blocked=0 rail_uv=1200000')
COMMAND = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
root = Path(os.environ['FIXTURE'])
state = json.loads((root / 'state.json').read_text())
name = Path(sys.argv[0]).name
if name == 'id':
    print(state.get('uid', '0'))
elif name == 'getprop':
    print(state['services'].get(sys.argv[1].removeprefix('init.svc.'), ''))
elif name in ('stop', 'start'):
    service = sys.argv[1]
    state['events'].append([name, service])
    if service != state.get(name + '_fails'):
        state['services'][service] = 'stopped' if name == 'stop' else 'running'
    (root / 'state.json').write_text(json.dumps(state))
elif name == 'cat':
    path = Path(sys.argv[1])
    if path.name == 'stream_readback' and state.get('readback_fails'):
        sys.exit(1)
    node = root / 'driver/device'
    if path.name == 'stream_result' and (node / 'stream_profile').read_text() == 'profile\\n':
        path.write_text('profile_loaded=1 stage=idle stop_errno=0\\n')
    triggered = (node / 'identify').read_text() == 'identify\\n'
    streaming = (node / 'stream_once').read_text() == 'stream-once\\n'
    if (node / 'csi_once').exists():
        streaming = streaming or (node / 'csi_once').read_text() == 'csi-once\\n'
        if (node / 'csi2_once').exists():
            streaming = streaming or (node / 'csi2_once').read_text() == 'csi2-once\\n'
        if streaming and path.name == 'csi_result':
            path.write_text(state.get('csi_after', 'requested=1 stage=listening errno=0 cleanup_errno=0 packets_before=0 packets_after=100\\n'))
    if triggered or (streaming and path.name in ('result', 'stream_result')):
        if state.get('unreadable_after'):
            sys.exit(1)
        path.write_text(state.get('stream_after', '') if path.name == 'stream_result' else state['after'])
    print(path.read_text(), end='')
elif name == 'sleep':
    pass
else:
    sys.exit(99)
'''


class IdentifyHelperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        node = self.root / 'driver/device'
        node.mkdir(parents=True)
        (node / 'result').write_text(INITIAL + '\n')
        (node / 'identify').write_text('')
        (node / 'stream_once').write_text('')
        (node / 'stream_profile').write_text('')
        (node / 'stream_result').write_text('profile_loaded=0 stage=idle stop_errno=0\n')
        (self.root / 'profile.hex').write_text('profile\n')
        self.state = {'services': dict.fromkeys(SERVICES, 'running'),
                      'events': [], 'after': SUCCESS + '\n'}
        binary = self.root / 'bin'
        binary.mkdir()
        for name in ['id', 'getprop', 'stop', 'start', 'cat', 'sleep']:
            command = binary / name
            command.write_text(COMMAND)
            command.chmod(0o755)
        source = Path(__file__).parents[1] / 'tools/identify_cityman.sh'
        self.helper = self.root / 'helper.sh'
        self.helper.write_text(source.read_text().replace(
            'driver=/sys/bus/platform/drivers/cityman-iris-id',
            f'driver={self.root}/driver').replace(
            '/data/local/tmp/cityman-iris-stream-profile.hex', str(self.root / 'profile.hex')))

    def run_helper(self, fail_write=False, operation=None):
        (self.root / 'state.json').write_text(json.dumps(self.state))
        command = ['sh', str(self.helper)]
        if fail_write:
            # A sysfs write can return an error after the driver has unwound.
            command = ['sh', '-c',
                       'printf() { command printf "$@"; return 1; }; helper_path=$1; shift; . "$helper_path"',
                       'test-helper', str(self.helper)]
        if operation:
            command.append(operation)
        run = subprocess.run(command, capture_output=True,
                             text=True, timeout=10, env={**os.environ,
                             'FIXTURE': str(self.root),
                             'PATH': str(self.root / 'bin') + os.pathsep + os.environ['PATH']})
        self.state = json.loads((self.root / 'state.json').read_text())
        return run

    def assert_not_attempted(self):
        self.assertEqual((self.root / 'driver/device/identify').read_text(), '')

    def test_success_restores_in_dependency_order_and_refuses_second_run(self):
        run = self.run_helper()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('model=0x0861', run.stdout)
        events = ([['stop', service] for service in SERVICES] +
                  [['start', service] for service in reversed(SERVICES)])
        self.assertEqual(self.state['events'], events)
        self.assertEqual((self.root / 'driver/device/identify').read_text(), 'identify\n')
        run = self.run_helper()
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(self.state['events'], events)

    def test_preserves_previously_stopped_services(self):
        self.state['services'][SERVICES[1]] = 'stopped'
        self.assertEqual(self.run_helper().returncode, 0)
        self.assertNotIn(['start', SERVICES[1]], self.state['events'])
        self.assertEqual(self.state['services'][SERVICES[1]], 'stopped')

    def test_mismatched_model_restores_services_but_returns_failure(self):
        self.state['after'] = SUCCESS.replace('status=identified', 'status=failed').replace(
            'model=0x0861', 'model=0x1234').replace('errno=0 model', 'errno=-19 model')
        run = self.run_helper()
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertEqual(list(self.state['services'].values()), ['running'] * 3)

    def test_cleanup_failure_leaves_services_stopped(self):
        self.state['after'] = SUCCESS.replace('cleanup_errno=0', 'cleanup_errno=-5').replace(
            'blocked=0', 'blocked=1')
        run = self.run_helper()
        self.assertEqual(run.returncode, 3, run.stdout + run.stderr)
        self.assertIn('REBOOT_REQUIRED', run.stderr)
        self.assertEqual(list(self.state['services'].values()), ['stopped'] * 3)
        self.assertTrue(all(event[0] == 'stop' for event in self.state['events']))

    def test_write_error_still_reads_result_and_restores_after_clean_cleanup(self):
        self.state['after'] = SUCCESS.replace('status=identified', 'status=failed').replace(
            'errno=0 model=0x0861', 'errno=-5 model=0x0000')
        run = self.run_helper(fail_write=True)
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn('After: status=failed', run.stdout)
        self.assertIn('errno=-5', run.stdout)
        self.assertEqual(list(self.state['services'].values()), ['running'] * 3)

    def test_unreadable_result_leaves_services_stopped(self):
        self.state['unreadable_after'] = True
        run = self.run_helper()
        self.assertEqual(run.returncode, 3)
        self.assertIn('REBOOT_REQUIRED', run.stderr)
        self.assertEqual(list(self.state['services'].values()), ['stopped'] * 3)

    def test_stop_timeout_aborts_and_restores_prior_running_services(self):
        self.state['stop_fails'] = SERVICES[1]
        run = self.run_helper()
        self.assertEqual(run.returncode, 1)
        self.assert_not_attempted()
        self.assertNotIn(['stop', SERVICES[2]], self.state['events'])
        self.assertIn(['start', SERVICES[0]], self.state['events'])
        self.assertEqual(list(self.state['services'].values()), ['running'] * 3)

    def test_missing_service_aborts_before_any_stop(self):
        del self.state['services'][SERVICES[2]]
        self.assertEqual(self.run_helper().returncode, 1)
        self.assertEqual(self.state['events'], [])
        self.assert_not_attempted()

    def test_nonroot_aborts_before_any_stop(self):
        self.state['uid'] = '2000'
        self.assertEqual(self.run_helper().returncode, 1)
        self.assertEqual(self.state['events'], [])
        self.assert_not_attempted()

    def test_service_restore_failure_is_reported(self):
        self.state['start_fails'] = SERVICES[2]
        run = self.run_helper()
        self.assertEqual(run.returncode, 4)
        self.assertIn('SERVICE_RESTORE_FAILED', run.stderr)

    def stream_fixture(self):
        self.state['after'] = SUCCESS.replace('status=identified stage=model-read',
                                             'status=sensor-streamed stage=stream-test')
        self.state['stream_after'] = ('profile_loaded=1 stage=mode-readback first=0x00 last=0x09 '
                                      'changes=9 samples=16 program_writes=117 stop_errno=0\n')

    def test_stream_mode_loads_profile_and_restores_services(self):
        self.stream_fixture()
        run = self.run_helper(operation='stream-once')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('changes=9', run.stdout)
        self.assertEqual(list(self.state['services'].values()), ['running'] * 3)
        self.assertEqual((self.root / 'driver/device/stream_once').read_text(), 'stream-once\n')
        self.assert_not_attempted()  # The identify control was not written.

    def test_stream_stop_failure_leaves_services_stopped(self):
        self.stream_fixture()
        self.state['stream_after'] = self.state['stream_after'].replace('stop_errno=0', 'stop_errno=-5')
        run = self.run_helper(operation='stream-once')
        self.assertEqual(run.returncode, 3)
        self.assertIn('REBOOT_REQUIRED', run.stderr)
        self.assertEqual(list(self.state['services'].values()), ['stopped'] * 3)

    def test_stream_prints_saved_readback_before_restoring_services(self):
        self.stream_fixture()
        (self.root / 'driver/device/stream_readback').write_text('mode before=0 after=1\n')
        run = self.run_helper(operation='stream-once')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('mode before=0 after=1', run.stdout)
        self.assertLess(run.stdout.index('mode before'), run.stdout.index('Restored:'))
        self.assertEqual(list(self.state['services'].values()), ['running'] * 3)

    def test_unavailable_saved_readback_preserves_confirmed_clean_restoration(self):
        self.stream_fixture()
        self.state['readback_fails'] = True
        (self.root / 'driver/device/stream_readback').write_text('fixture\n')
        run = self.run_helper(operation='stream-once')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('Saved register readback unavailable.', run.stderr)
        self.assertEqual(list(self.state['services'].values()), ['running'] * 3)

    def test_stream_requires_new_controls_before_stopping_services(self):
        (self.root / 'driver/device/stream_once').unlink()
        run = self.run_helper(operation='stream-once')
        self.assertEqual(run.returncode, 1)
        self.assertEqual(self.state['events'], [])

    def test_unknown_operation_is_rejected_before_any_stop(self):
        self.assertEqual(self.run_helper(operation='anything').returncode, 1)
        self.assertEqual(self.state['events'], [])

    def csi_fixture(self):
        self.stream_fixture()
        node = self.root / 'driver/device'
        (node / 'csi_once').write_text('')
        (node / 'csi_result').write_text('requested=0 stage=idle errno=0 cleanup_errno=0\n')

    def test_csi_mode_uses_separate_control_and_prints_packet_result(self):
        self.csi_fixture()
        (self.root / 'driver/device/csi_readback').write_text('csid_control1 before=0x0005000f after=0x0005000f\n')
        run = self.run_helper(operation='csi-once')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((self.root / 'driver/device/csi_once').read_text(), 'csi-once\n')
        self.assertEqual((self.root / 'driver/device/stream_once').read_text(), '')
        self.assertIn('CSI after:', run.stdout)
        self.assertIn('packets_after=100', run.stdout)
        self.assertIn('csid_control1 before=0x0005000f after=0x0005000f', run.stdout)
        self.assertLess(run.stdout.index('CSI after:'), run.stdout.index('Restored:'))
        self.assertEqual(list(self.state['services'].values()), ['running'] * 3)

    def test_csi_cleanup_failure_leaves_services_stopped(self):
        self.csi_fixture()
        self.state['csi_after'] = 'requested=1 stage=phy-config errno=-5 cleanup_errno=-5\n'
        run = self.run_helper(operation='csi-once')
        self.assertEqual(run.returncode, 3)
        self.assertEqual(list(self.state['services'].values()), ['stopped'] * 3)

    def test_csi_requires_receiver_build_before_stopping_services(self):
        run = self.run_helper(operation='csi-once')
        self.assertEqual(run.returncode, 1)
        self.assertEqual(self.state['events'], [])

    def test_csi_preserves_packet_result_after_clean_counter_timeout(self):
        self.csi_fixture()
        self.state['after'] = self.state['after'].replace('status=sensor-streamed', 'status=failed').replace('errno=0 model=', 'errno=-110 model=')
        run = self.run_helper(fail_write=True, operation='csi-once')
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn('packets_after=100', run.stdout)
        self.assertEqual(list(self.state['services'].values()), ['running'] * 3)

    def test_csi2_variant_requires_separate_control_and_preserves_result_dump(self):
        self.csi_fixture()
        run = self.run_helper(operation='csi2-once')
        self.assertEqual(run.returncode, 1)
        self.assertEqual(self.state['events'], [])
        (self.root / 'driver/device/csi2_once').write_text('')
        run = self.run_helper(operation='csi2-once')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('CSI after:', run.stdout)
        self.assertEqual((self.root / 'driver/device/csi2_once').read_text(), 'csi2-once\n')
        self.assertEqual((self.root / 'driver/device/csi_once').read_text(), '')
        self.assertEqual(list(self.state['services'].values()), ['running'] * 3)


if __name__ == '__main__':
    unittest.main()
