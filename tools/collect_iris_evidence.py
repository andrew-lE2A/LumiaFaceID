#!/usr/bin/env python3
"""Collect saved iris diagnostic evidence only; never start/reset/boot the phone."""
import argparse
import datetime
import json
from pathlib import Path
import re
import sys

from collect_cityman import Adb

DRIVER = '/sys/bus/platform/drivers/cityman-iris-id'
CLOCK_SETS = (
    ('camss_csi3_clk', 'camss_phy2_csi2phytimer_clk'),
    ('camss_csi3phy_clk', 'camss_csi3_clk', 'camss_phy2_csi2phytimer_clk'),
    ('camss_csi3phy_clk', 'camss_csi2_clk', 'camss_csi0_clk',
     'camss_csi3_clk', 'camss_phy2_csi2phytimer_clk'),
)
STATUS_COMMAND = f'''set -- {DRIVER}/*/result
[ "$#" = 1 ] && [ -r "$1" ] || exit 66
cat "$1"'''
FILES = ('result', 'stream_result', 'stream_readback', 'csi_result', 'csi_readback')
SNAPSHOT_COMMAND = f'''set -- {DRIVER}/*/result
[ "$#" = 1 ] && [ -r "$1" ] || exit 66
device=${{1%/result}}
for name in {' '.join(FILES)}; do
    printf 'FILE %s\\n' "$name"
    cat "$device/$name" || exit $?
    printf 'END\\n'
done'''
LOG_LIST_COMMAND = '''for file in /data/local/tmp/cityman-iris-rxclk.*; do
    [ -f "$file" ] || continue
    printf '%s\\n' "$file"
done'''
SERVICES_COMMAND = '''for service in cameraserver vendor.camera-provider-2-4 qcamerasvr; do
    printf '%s=' "$service"
    getprop "init.svc.$service"
done'''


def parse_snapshot(text):
    files = {}
    lines = iter(text.splitlines())
    for line in lines:
        if not line.startswith('FILE ') or line[5:] not in FILES or line[5:] in files:
            raise ValueError('Unexpected diagnostic file marker')
        name = line[5:]
        body = []
        for line in lines:
            if line == 'END':
                break
            body.append(line)
        else:
            raise ValueError('Unterminated diagnostic file')
        if not body:
            raise ValueError('Empty diagnostic file')
        files[name] = '\n'.join(body) + '\n'
    if set(files) != set(FILES):
        raise ValueError('Incomplete diagnostic snapshot')
    return files


def parse_rxclk(text):
    samples = []
    keys = ('sample', 'clock', 'rate_before_hz', 'enable_before', 'measured_hz',
            'rate_after_hz', 'enable_after')
    for line in text.splitlines():
        if not line.startswith('RXCLK '):
            raise ValueError('Unexpected receiver-clock log line')
        fields = line.split()[1:]
        if len(fields) != len(keys) or any('=' not in field for field in fields):
            raise ValueError('Malformed receiver-clock sample')
        pairs = [field.split('=', 1) for field in fields]
        if [pair[0] for pair in pairs] != list(keys):
            raise ValueError('Unexpected receiver-clock sample fields')
        row = dict(pairs)
        if row['clock'] not in {clock for clock_set in CLOCK_SETS for clock in clock_set}:
            raise ValueError('Unexpected clock target')
        for key in keys:
            if key != 'clock':
                if not re.fullmatch(r'[0-9]+', row[key]):
                    raise ValueError('Non-numeric receiver-clock value')
                row[key] = int(row[key])
        row['stable_enabled'] = (row['enable_before'] > 0 and row['enable_after'] > 0
                                 and row['rate_before_hz'] == row['rate_after_hz'])
        samples.append(row)
    supported = any(
        len(samples) == 6 * len(candidate)
        and all(row['clock'] == candidate[i % len(candidate)]
                and row['sample'] == i // len(candidate) + 1
                for i, row in enumerate(samples))
        for candidate in CLOCK_SETS)
    if not supported:
        raise ValueError('Expected six interleaved rounds from a supported receiver-clock set')
    return samples


def checked_shell(adb, command):
    result = adb.shell(command)
    if result['status'] != 'ok':
        raise ValueError('ADB evidence read failed: ' + result.get('stderr', '').strip())
    return result['stdout']


def collect(adb, include_clock_logs=True):
    before = checked_shell(adb, STATUS_COMMAND)
    files = parse_snapshot(checked_shell(adb, SNAPSHOT_COMMAND))
    logs = []
    paths = checked_shell(adb, LOG_LIST_COMMAND).splitlines() if include_clock_logs else []
    if len(paths) > 16:
        raise ValueError('Too many saved clock logs; select evidence manually')
    for path in paths:
        # Device output is untrusted; never interpolate an arbitrary shell path.
        if not re.fullmatch(r'/data/local/tmp/cityman-iris-rxclk\.[A-Za-z0-9]{6}', path):
            raise ValueError('Unexpected saved clock-log path')
        raw = checked_shell(adb, 'cat ' + path)
        logs.append({'device_path': path, 'raw': raw, 'samples': parse_rxclk(raw)})
    services = checked_shell(adb, SERVICES_COMMAND)
    version = checked_shell(adb, 'cat /proc/version')
    after = checked_shell(adb, STATUS_COMMAND)
    if before != after or files['result'] != before:
        raise ValueError('Diagnostic state changed during evidence collection; report not saved')
    return {'schema_version': 1,
            'collected_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'provenance': 'Direct read-only ADB collection of saved kernel diagnostic state and clock logs.',
            'kernel_version': version.strip(), 'diagnostic_files': files,
            'saved_receiver_clock_logs': logs, 'clock_logs_requested': include_clock_logs,
            'camera_service_states': services,
            'limits': ['No hardware diagnostic was triggered.',
                       'Existing clock logs may belong to an earlier attempt or boot; collection does not associate them with the current kernel.',
                       'Saved register snapshots precede cleanup; these are not live sensor reads.',
                       'Service states were observed now; restoration and camera behavior remain owner evidence.',
                       'Matching result reads detect a changed diagnostic result, not concurrent identical clock-log rewrites.',
                       'Internal clock samples do not measure sensor pins or recovered MIPI clocks.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', help='ADB device selector (not written to report)')
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--skip-clock-logs', action='store_true',
                        help='Do not read earlier saved clock logs for a run without clock sampling')
    parser.add_argument('--output', type=Path, required=True, help='New local JSON file; never overwritten')
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise ValueError('Output already exists; refusing to overwrite evidence')
        report = collect(Adb(args.adb, args.serial), not args.skip_clock_logs)
        with args.output.open('x') as output:
            json.dump(report, output, indent=2)
            output.write('\n')
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print('Saved read-only iris evidence:', args.output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
