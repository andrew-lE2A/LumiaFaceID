"""Exercise the actual device helper with simulated init services and sysfs.

Filesystem paths are redirected into a fixture. The shell control flow and
diagnostic write are unchanged; Android commands are supplied through PATH.
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
    if path.name == 'measure' and state.get('measure_fails'):
        sys.exit(1)
    node = root / 'driver/device'
    if path.name == 'stream_result' and (node / 'stream_profile').read_text() == 'profile\\n':
        path.write_text('profile_loaded=1 stage=idle stop_errno=0\\n')
    triggered = (node / 'identify').read_text() == 'identify\\n'
    streaming = (node / 'stream_once').read_text() == 'stream-once\\n'
    trial = (node / 'csi_trial').exists() and (node / 'csi_trial').read_text().startswith('settle=')
    nvm = (node / 'nvm_once').exists() and (node / 'nvm_once').read_text() == 'nvm-once\\n'
    tpg = (node / 'csi_tpg_once').exists() and (node / 'csi_tpg_once').read_text() == 'run\\n'
    if (node / 'csi_once').exists():
        streaming = streaming or (node / 'csi_once').read_text() == 'csi-once\\n'
        if (node / 'csi2_once').exists():
            streaming = streaming or (node / 'csi2_once').read_text() == 'csi2-once\\n'
        if (streaming or trial) and path.name == 'csi_result':
            path.write_text(state.get('csi_after', 'requested=1 stage=listening errno=0 cleanup_errno=0 packets_before=0 packets_after=100\\n'))
    if tpg and path.name == 'csi_tpg_result':
        path.write_text(state.get('tpg_after', 'requested=1 stage=released errno=0 cleanup_errno=0 version=0x30010003 before_valid=1 after_valid=1 packets_before=0 packets_after=480 ecc_before=0 ecc_after=0 crc_before=0 crc_after=0 irq_before=0x00000000 irq_after=0x00000000\\n'))
    if tpg and path.name == 'result':
        path.write_text(state.get('tpg_main_after', 'status=ready stage=idle errno=0 model=0x0000 cleanup_errno=0 attempts=0 blocked=0 rail_uv=0\\n'))
    if nvm and path.name == 'nvm_result':
        path.write_text(state.get('nvm_after', 'requested=1 valid=1 errno=0 cleanup_errno=0 size_bytes=256 pages=4 config_flags=1 sensor_config_entries_present=1 raw_payload_exported=0\\n'))
    if nvm and path.name == 'result':
        path.write_text(state.get('after', 'status=identified stage=nvm-test errno=0 model=0x0861 cleanup_errno=0 attempts=1 blocked=0 rail_uv=1200000\\n'))
    if triggered or (streaming and path.name in ('result', 'stream_result')) or (trial and path.name in ('result', 'stream_result')):
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
        (node / 'nvm_once').write_text('')
        (node / 'nvm_result').write_text('requested=0 valid=0 errno=0 cleanup_errno=0\n')
        (node / 'stream_once').write_text('')
        (node / 'csi_trial').write_text('')
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
            '/data/local/tmp/cityman-iris-stream-profile.hex', str(self.root / 'profile.hex')).replace(
            '/sys/kernel/debug/clk/camss_mclk1_clk', str(self.root / 'clock')).replace(
            '/data/local/tmp/cityman-iris-mclk.XXXXXX', str(self.root / 'mclk-log.XXXXXX')).replace(
            'receiver_clock_root=/sys/kernel/debug/clk', f'receiver_clock_root={self.root}/rxclocks').replace(
            '/data/local/tmp/cityman-iris-rxclk.XXXXXX', str(self.root / 'rxclk-log.XXXXXX')))

    def run_helper(self, fail_write=False, operation=None, option=None, extra=()):
        (self.root / 'state.json').write_text(json.dumps(self.state))
        command = ['sh', str(self.helper)]
        if fail_write:
            # A sysfs write can return an error after the driver has unwound.
            command = ['sh', '-c',
                       'printf() { command printf "$@"; return 1; }; helper_path=$1; shift; . "$helper_path"',
                       'test-helper', str(self.helper)]
        if operation:
            command.append(operation)
        if option:
            command.append(option)
        command.extend(extra)
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

    def test_nvm_header_mode_restores_services_and_does_not_read_raw_payload(self):
        self.state['after'] = ('status=identified stage=nvm-test errno=0 model=0x0861 '
                               'cleanup_errno=0 attempts=1 blocked=0 rail_uv=1200000\n')
        self.state['nvm_after'] = ('requested=1 valid=1 errno=0 cleanup_errno=0 '
                                   'size_bytes=256 pages=4 config_flags=1 '
                                   'sensor_config_entries_present=1 raw_payload_exported=0\n')
        run = self.run_helper(operation='nvm-once')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('sensor_config_entries_present=1', run.stdout)
        self.assertIn('raw_payload_exported=0', run.stdout)
        self.assertEqual((self.root / 'driver/device/nvm_once').read_text(), 'nvm-once\n')
        events = ([['stop', service] for service in SERVICES] +
                  [['start', service] for service in reversed(SERVICES)])
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
        (node / 'csi_top_result').write_text('camss_top_40=0x00000000 camss_top_44=0x00000000\n')

    def tpg_fixture(self):
        node = self.root / 'driver/device'
        (node / 'csi_tpg_once').write_text('')
        (node / 'csi_tpg_result').write_text('requested=0 stage=idle errno=0 cleanup_errno=0\n')

    def test_tpg_runs_without_sensor_profile_and_restores_services(self):
        self.tpg_fixture()
        run = self.run_helper(operation='tpg-once')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('CSID TPG after:', run.stdout)
        self.assertIn('packets_after=480', run.stdout)
        self.assertEqual((self.root / 'driver/device/csi_tpg_once').read_text(), 'run\n')
        self.assertEqual((self.root / 'driver/device/stream_once').read_text(), '')
        self.assertFalse((self.root / 'driver/device/csi_once').exists())
        self.assertEqual(self.state['events'],
                         [['stop', service] for service in SERVICES] +
                         [['start', service] for service in reversed(SERVICES)])

    def test_tpg_cleanup_failure_leaves_services_stopped(self):
        self.tpg_fixture()
        self.state['tpg_after'] = 'requested=1 stage=csid-release errno=0 cleanup_errno=-5\n'
        self.state['tpg_main_after'] = INITIAL.replace('blocked=0', 'blocked=1') + '\n'
        run = self.run_helper(operation='tpg-once')
        self.assertEqual(run.returncode, 3)
        self.assertIn('REBOOT_REQUIRED', run.stderr)
        self.assertEqual(list(self.state['services'].values()), ['stopped'] * 3)

    def test_tpg_requires_diagnostic_build_before_stopping_services(self):
        run = self.run_helper(operation='tpg-once')
        self.assertEqual(run.returncode, 1)
        self.assertEqual(self.state['events'], [])

    def test_csi_mode_uses_separate_control_and_prints_packet_result(self):
        self.csi_fixture()
        (self.root / 'driver/device/csi_readback').write_text('csid_control1 before=0x0005000f after=0x0005000f\n')
        run = self.run_helper(operation='csi-once')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((self.root / 'driver/device/csi_once').read_text(), 'csi-once\n')
        self.assertEqual((self.root / 'driver/device/stream_once').read_text(), '')
        self.assertIn('CSI after:', run.stdout)
        self.assertIn('CAMSS TOP before receiver test:', run.stdout)
        self.assertIn('CAMSS TOP after receiver test:', run.stdout)
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

    def test_csi_trial_accepts_clean_timeout_and_preserves_settle(self):
        self.csi_fixture()
        node = self.root / 'driver/device'
        (node / 'csi_result').write_text('requested=0 stage=idle errno=0 cleanup_errno=0\n')
        self.state['after'] = ('status=failed stage=stream-test errno=-110 model=0x0861 '
                              'cleanup_errno=0 attempts=1 blocked=0 rail_uv=1200000\n')
        self.state['stream_after'] = ('profile_loaded=1 stage=stream-test samples=16 '
                                      'changes=0 stop_errno=0\n')
        self.state['csi_after'] = 'requested=1 stage=released errno=0 cleanup_errno=0\n'
        run = self.run_helper(operation='csi-trial', option='20')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('one CSI-2 trial at settle=20', run.stdout)
        self.assertEqual((node / 'csi_trial').read_text(), 'settle=20\n')
        self.assertEqual(list(self.state['services'].values()), ['running'] * 3)

    def test_csi_trial_rejects_out_of_range_settle_before_stopping_services(self):
        self.csi_fixture()
        run = self.run_helper(operation='csi-trial', option='64')
        self.assertEqual(run.returncode, 1)
        self.assertEqual(self.state['events'], [])

    def test_csi_trial_passes_byte_override(self):
        self.csi_fixture()
        self.state['after'] = ('status=failed stage=stream-test errno=-110 model=0x0861 '
                               'cleanup_errno=0 attempts=1 blocked=0 rail_uv=1200000\n')
        self.state['stream_after'] = 'profile_loaded=1 stage=frame-counter stop_errno=0\n'
        self.state['csi_after'] = 'requested=1 stage=released errno=0 cleanup_errno=0\n'
        run = self.run_helper(operation='csi-trial', option='22', extra=('0307', '92'))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((self.root / 'driver/device/csi_trial').read_text(),
                         'settle=22 reg=0307 value=92\n')

    def test_csi_trial_retries_after_three_clean_attempts(self):
        self.csi_fixture()
        node = self.root / 'driver/device'
        prior = ('status=failed stage=stream-test errno=-110 model=0x0861 '
                 'cleanup_errno=0 attempts=3 blocked=0 rail_uv=1200000\n')
        (node / 'result').write_text(prior)
        (node / 'stream_result').write_text('profile_loaded=1 stage=frame-counter stop_errno=0\n')
        (node / 'csi_result').write_text('requested=1 stage=released errno=0 cleanup_errno=0 phy=2\n')
        self.state['after'] = prior.replace('attempts=3', 'attempts=4')
        self.state['stream_after'] = 'profile_loaded=1 stage=frame-counter stop_errno=0\n'
        self.state['csi_after'] = 'requested=1 stage=released errno=0 cleanup_errno=0 phy=2\n'
        run = self.run_helper(operation='csi-trial', option='22')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('attempts=4', run.stdout)

    def test_csi_trial_write_error_is_not_masked_by_clean_result(self):
        self.csi_fixture()
        self.state['after'] = ('status=failed stage=stream-test errno=-110 model=0x0861 '
                               'cleanup_errno=0 attempts=1 blocked=0 rail_uv=1200000\n')
        self.state['stream_after'] = 'profile_loaded=1 stage=frame-counter stop_errno=0\n'
        self.state['csi_after'] = 'requested=1 stage=released errno=0 cleanup_errno=0\n'
        run = self.run_helper(fail_write=True, operation='csi-trial', option='22')
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(list(self.state['services'].values()), ['running'] * 3)

    def clock_fixture(self):
        self.csi_fixture()
        clock = self.root / 'clock'
        clock.mkdir()
        for name, value in [('rate', '9600000'), ('enable', '1'), ('measure', '9599999')]:
            (clock / name).write_text(value + '\n')

    def test_clock_observation_is_bounded_saved_and_joined_before_restoration(self):
        self.clock_fixture()
        run = self.run_helper(operation='csi-once', option='--observe-mclk')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(run.stdout.count('MCLK sample='), 12)
        self.assertIn('measured_hz=9599999', run.stdout)
        self.assertIn('rate_before_hz=9600000 enable_before=1', run.stdout)
        self.assertLess(run.stdout.index('MCLK sample=12 '), run.stdout.index('Restored:'))
        self.assertEqual(list(self.state['services'].values()), ['running'] * 3)
        logs = list(self.root.glob('mclk-log.*'))
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].read_text().count('MCLK sample='), 12)
        self.assertEqual((self.root / 'clock/rate').read_text(), '9600000\n')
        self.assertEqual((self.root / 'clock/enable').read_text(), '1\n')

    def test_missing_clock_measurement_refuses_before_services_or_sensor(self):
        self.csi_fixture()
        run = self.run_helper(operation='csi-once', option='--observe-mclk')
        self.assertEqual(run.returncode, 1)
        self.assertIn('MCLK observation unavailable', run.stderr)
        self.assertEqual(self.state['events'], [])

    def test_clock_read_failure_reports_incomplete_but_restores_clean_camera_services(self):
        self.clock_fixture()
        self.state['measure_fails'] = True
        run = self.run_helper(operation='csi-once', option='--observe-mclk')
        self.assertEqual(run.returncode, 5, run.stdout + run.stderr)
        self.assertIn('MCLK_OBSERVATION_INCOMPLETE', run.stderr)
        self.assertIn('measurement read failed', run.stdout)
        self.assertEqual(list(self.state['services'].values()), ['running'] * 3)

    def test_unknown_clock_option_and_identify_clock_mode_refuse_without_stopping_services(self):
        for operation, option in [('csi-once', '--unknown'), ('identify', '--observe-mclk')]:
            run = self.run_helper(operation=operation, option=option)
            self.assertEqual(run.returncode, 1)
            self.assertEqual(self.state['events'], [])

    def receiver_clock_fixture(self):
        self.csi_fixture()
        (self.root / 'driver/device/csi2_once').write_text('')
        for name, rate, measure in [('camss_csi3_clk', 240000000, 239999000),
                                    ('camss_phy2_csi2phytimer_clk', 200000000, 199999000)]:
            clock = self.root / 'rxclocks' / name
            clock.mkdir(parents=True)
            for key, value in [('rate', rate), ('enable', 1), ('measure', measure)]:
                (clock / key).write_text(str(value) + '\n')

    def test_receiver_clocks_are_interleaved_in_one_saved_log_before_restoration(self):
        self.receiver_clock_fixture()
        run = self.run_helper(operation='csi2-once', option='--observe-receiver-clocks')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        lines = [line for line in run.stdout.splitlines() if line.startswith('RXCLK sample=')]
        self.assertEqual(len(lines), 12)
        for index, line in enumerate(lines):
            name = ('camss_csi3_clk', 'camss_phy2_csi2phytimer_clk')[index % 2]
            self.assertIn(f'sample={index // 2 + 1} clock={name} ', line)
        self.assertIn('measured_hz=239999000', run.stdout)
        self.assertIn('measured_hz=199999000', run.stdout)
        self.assertLess(run.stdout.index(lines[-1]), run.stdout.index('Restored:'))
        self.assertEqual(list(self.state['services'].values()), ['running'] * 3)
        self.assertEqual(len(list(self.root.glob('rxclk-log.*'))), 1)

    def test_missing_second_receiver_clock_refuses_before_stopping_services(self):
        self.receiver_clock_fixture()
        (self.root / 'rxclocks/camss_phy2_csi2phytimer_clk/measure').unlink()
        run = self.run_helper(operation='csi-once', option='--observe-receiver-clocks')
        self.assertEqual(run.returncode, 1)
        self.assertIn('RXCLK observation unavailable', run.stderr)
        self.assertEqual(self.state['events'], [])

    def test_receiver_clock_samples_do_not_override_failed_cleanup(self):
        self.receiver_clock_fixture()
        self.state['csi_after'] = 'requested=1 stage=released errno=0 cleanup_errno=-5\n'
        run = self.run_helper(operation='csi-once', option='--observe-receiver-clocks')
        self.assertEqual(run.returncode, 3, run.stdout + run.stderr)
        self.assertEqual(run.stdout.count('RXCLK sample='), 12)
        self.assertIn('REBOOT_REQUIRED', run.stderr)
        self.assertNotIn('Restored:', run.stdout)
        self.assertEqual(list(self.state['services'].values()), ['stopped'] * 3)

    def test_receiver_clock_option_rejects_sensor_only_mode(self):
        run = self.run_helper(operation='stream-once', option='--observe-receiver-clocks')
        self.assertEqual(run.returncode, 1)
        self.assertIn('requires csi-once or csi2-once', run.stderr)
        self.assertEqual(self.state['events'], [])


if __name__ == '__main__':
    unittest.main()
