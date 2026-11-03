#!/usr/bin/env python3
"""Inspect the pinned original 0C086101.dcc offline; never access hardware.

Directory layout and block roles are derived from the matching ARM driver's
consumers, documented in docs/iris-capture.md. This emits research metadata,
not a sensor write program. Proprietary inputs remain outside the repository.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys


DCC_SIZE = 496797
DCC_SHA256 = '656c1dd9c1d5a818a232319ef16b8ea7fa1936ce9ea40ed9c241ddbcaee86a85'
SOURCE_COMMIT = 'b5af93f99ea800c28551727df55e57a07ba61a82'
SOURCE_PATH = ('components/QC899X/Hardware/HARDWARE.CAMERA.MMO_8994/Drivers/Camera/'
               'Sensors/Calibration/0C086101.dcc')
BLOCK_ROLES = {0: 'idle_configuration', 5: 'read_overrides',
               12: 'software_configuration'}


def parse_directory(data):
    """Bounded format-31 directory; public inspection also requires exact SHA."""
    if len(data) < 0x38 or struct.unpack_from('>I', data)[0] != 31:
        raise ValueError('Expected a complete format-31 header')
    if struct.unpack_from('>I', data, 4)[0] != len(data):
        raise ValueError('Declared file size differs from actual size')
    count = data[0x34]
    offset = 0x38 + count * 6
    if not count or offset > len(data) - 4:
        raise ValueError('Invalid or truncated block directory')
    blocks = []
    seen = set()
    for index in range(count):
        tag, size = struct.unpack_from('>HI', data, 0x38 + index * 6)
        if tag in seen:
            raise ValueError('Duplicate block ID')
        seen.add(tag)
        if not size or size > len(data) - 4 - offset:
            raise ValueError('Block extends beyond the payload')
        blocks.append((tag, offset, data[offset:offset + size]))
        offset += size
    # Four trailing bytes exist in the pinned input; their algorithm is unknown.
    # Exact SHA verification establishes input identity, not this trailer's meaning.
    if offset != len(data) - 4:
        raise ValueError('Unaccounted payload bytes')
    return blocks


def register_records(payload):
    """Decode bounded >HB records; stop marker must occupy the final record.

    These are data records, not instructions to write. In particular block 5
    overrides read results. Special command addresses are retained as data.
    """
    if not payload or len(payload) % 3:
        raise ValueError('Register record block is not a multiple of three bytes')
    records = list(struct.iter_unpack('>HB', payload))
    if records[-1] != (0, 0) or (0, 0) in records[:-1]:
        raise ValueError('Missing final terminator or records after terminator')
    return records[:-1]


def mode_summary(records):
    # An ambiguous register must not silently become a last-write-wins claim.
    registers = {}
    for address, value in records:
        if address in registers:
            raise ValueError('Duplicate register in static mode summary')
        registers[address] = value

    def value(address, width=1):
        if not all(address + index in registers for index in range(width)):
            return None
        return int.from_bytes(bytes(registers[address + index] for index in range(width)), 'big')

    return {'output_width': value(0x034C, 2), 'output_height': value(0x034E, 2),
            'csi_data_format_register': value(0x0112, 2),
            'csi_lane_mode_register': value(0x0114),
            'line_length_register': value(0x0342, 2),
            'frame_length_register': value(0x0340, 2),
            'extclk_register_0136': value(0x0136, 2),
            'mode_select_present': 0x0100 in registers,
            'special_command_addresses': [f'0x{a:04x}' for a in registers if a >= 0xFFF9]}


def inspect_dcc(data):
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != DCC_SIZE or digest != DCC_SHA256:
        raise ValueError('Unsupported DCC size/SHA-256; the pinned 0C086101.dcc is required')
    blocks = []
    for tag, offset, payload in parse_directory(data):
        block = {'id': f'0x{tag:04x}', 'file_offset': offset, 'bytes': len(payload),
                 'sha256': hashlib.sha256(payload).hexdigest(),
                 'role': BLOCK_ROLES.get(tag, 'mode' if tag >= 0xFF00 else 'opaque')}
        if tag in (0, 5) or tag >= 0xFF00:
            records = register_records(payload)
            block['record_count_without_terminator'] = len(records)
            if tag >= 0xFF00:
                block['mode_index'] = tag - 0xFF00
                block['static_register_summary'] = mode_summary(records)
        blocks.append(block)
    return {'schema_version': 1, 'sha256': digest, 'source_commit': SOURCE_COMMIT,
            'source_path': SOURCE_PATH, 'format': 31,
            'camera_id_label': data[8:40].rstrip(b'\0').decode('ascii'),
            'blocks': blocks, 'opaque_trailer_hex': data[-4:].hex(),
            'limitations': [
                'Static calibration metadata, not a measurement of delivered frames.',
                'Read overrides must not be replayed as sensor writes.',
                'Mode records alone do not establish initialization, CSI routing, or frame timing.',
                'Special commands, dynamic register updates and illumination remain unimplemented.',
                'The trailer algorithm is unknown; input identity is checked by the full-file SHA-256.',
            ]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dcc', type=Path, help='local original pinned 0C086101.dcc')
    parser.add_argument('--output', type=Path, help='new JSON file; default is standard output')
    args = parser.parse_args(argv)
    try:
        if args.dcc.stat().st_size != DCC_SIZE:
            raise ValueError('Unsupported DCC size; expected 496797 bytes')
        payload = json.dumps(inspect_dcc(args.dcc.read_bytes()), indent=2) + '\n'
        if args.output:
            with args.output.open('x', encoding='utf-8') as output:
                output.write(payload)
        else:
            sys.stdout.write(payload)
    except (OSError, ValueError) as exc:
        print(f'Inspection failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
