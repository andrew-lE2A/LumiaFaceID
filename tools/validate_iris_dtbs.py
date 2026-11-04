#!/usr/bin/env python3
"""Validate cityman diagnostic bindings against the pinned vendor DT schema.

This checks structure and references, not electrical behavior or sensor safety.
"""
import argparse
import json
from pathlib import Path
import struct
import sys
from repack_boot import check_dtbs, dtb_nodes, read_file


TLMM = '/soc/pinctrl@fd510000'
DEVICE = '/soc/qcom,cci@fda0c000/cityman-iris-id'


def cells(properties, name):
    data = properties.get(name)
    if data is None or not data or len(data) % 4:
        raise ValueError(f'Missing or malformed {name}')
    return struct.unpack('>' + 'I' * (len(data) // 4), data)


def validate_nodes(nodes):
    if b'mmo,cityman' not in nodes.get('/', {}).get('compatible', b'').split(b'\0'):
        raise ValueError('Not the Cityman board')
    device = nodes.get(DEVICE)
    if not device or device.get('compatible') != b'microsoft,cityman-iris-id\0':
        raise ValueError('Missing dedicated iris-ID binding under camera CCI')
    handles = {}
    for path, properties in nodes.items():
        if 'phandle' in properties:
            handle, = cells(properties, 'phandle')
            if handle in handles:
                raise ValueError('Duplicate DT phandle')
            handles[handle] = path
    def target(handle):
        if handle not in handles:
            raise ValueError('Unresolved DT phandle')
        return handles[handle]
    if device.get('pinctrl-names') != b'iris_active\0iris_sleep\0':
        raise ValueError('Diagnostic must have only explicitly named, non-default pin states')
    for state in ('pinctrl-0', 'pinctrl-1'):
        pins = []
        for handle in cells(device, state):
            config = target(handle)
            group = config.rsplit('/', 1)[0]
            # msm_pinctrl_dt_parse_pins() visits only direct controller children.
            if group.rsplit('/', 1)[0] != TLMM:
                raise ValueError('Pinctrl group is not a direct child of the TLMM controller: ' + group)
            properties = nodes[group]
            if not properties.get('label'):
                raise ValueError('Pinctrl group is missing its vendor label')
            gp, pin = cells(properties, 'qcom,pins')
            if target(gp) != TLMM + '/gp' or cells(properties, 'qcom,num-grp-pins') != (1,):
                raise ValueError('Invalid diagnostic pin group')
            pins.append(pin)
        if sorted(pins) != [14, 102]:
            raise ValueError('Diagnostic pin state must cover MCLK1 GPIO14 and reset GPIO102 only')
    gpio, pin, flags = cells(device, 'reset-gpios')
    if target(gpio) != TLMM + '/gp/msm_gpio' or (pin, flags) != (102, 0):
        raise ValueError('Unexpected reset GPIO binding')
    expected = {'vana': 'ldoa17/regulator-l17', 'vio': 'vsa1/regulator-lvs1',
                'core': 'smpa3/regulator-s3', 'vdig': 'ldoa3/regulator-l3'}
    for name, suffix in expected.items():
        handle, = cells(device, name + '-supply')
        if target(handle) != '/soc/qcom,rpm-smd/rpm-regulator-' + suffix:
            raise ValueError('Unexpected diagnostic supply: ' + name)
    if {name for name in device if name.endswith('-supply')} != {x+'-supply' for x in expected}:
        raise ValueError('Unexpected additional power/boost supply')
    if any('flash' in name for name in device):
        raise ValueError('Diagnostic must not bind a flash controller')
    clock_names = device.get('clock-names')
    clock_cells = cells(device, 'clocks')
    legacy_clocks = clock_names == b'cam_src_clk\0cam_clk\0' and len(clock_cells) == 4
    csi3phy_clocks = (clock_names ==
        b'cam_src_clk\0cam_clk\0csi3phy_clk\0csi2-camss-clk\0csi0-camss-clk\0'
        and len(clock_cells) == 10)
    if not (legacy_clocks or csi3phy_clocks):
        raise ValueError('Unexpected MCLK binding')
    return {'device': DEVICE, 'pinctrl_provider': TLMM,
            'pins': [14, 102], 'automatic_identification': False,
            'scope': 'structural binding checks only; hardware is unverified'}


def validate(data):
    results, offset = [], 0
    for info in check_dtbs(data):
        nodes = dtb_nodes(data[offset:offset + info['size']])
        if b'mmo,cityman' in nodes.get('/', {}).get('compatible', b'').split(b'\0'):
            results.append(validate_nodes(nodes))
        offset += info['size']
    if len(results) != 1:
        raise ValueError('Expected exactly one Cityman board')
    return results[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dtbs', type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(validate(read_file(args.dtbs)), indent=2))
    except (OSError, ValueError, struct.error) as exc:
        print(f'DTB validation failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
