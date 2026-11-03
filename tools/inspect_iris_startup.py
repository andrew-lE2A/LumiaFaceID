#!/usr/bin/env python3
"""Recover bounded startup links from the exact original ARM iris driver, offline."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

from inspect_iris_driver import DRIVER_SHA256, SOURCE_COMMIT, SOURCE_PATH, pe_sections, rva_offset

IMAGE_BASE = 0x400000


def read_word(data, sections, rva):
    return struct.unpack_from('<I', data, rva_offset(sections, rva, 4))[0]


def literal16(data, sections, rva):
    """Decode only Thumb T1 LDR (literal), with aligned PC and bounded file data."""
    if rva & 1:
        raise ValueError('Thumb instruction must be halfword aligned')
    opcode, = struct.unpack_from('<H', data, rva_offset(sections, rva, 2))
    if opcode & 0xF800 != 0x4800:
        raise ValueError('Expected Thumb T1 LDR literal')
    pool = ((rva + 4) & ~3) + (opcode & 0xFF) * 4
    value = read_word(data, sections, pool)
    return {'instruction_va': hex(IMAGE_BASE + rva),
            'destination_register': 'r' + str((opcode >> 8) & 7),
            'literal_va': hex(IMAGE_BASE + pool), 'value': hex(value)}


def table_branch(data, sections, instruction_rva, index, count):
    """Decode only TBB [PC, r2]; jump-table bounds are supplied by the reviewed code."""
    if instruction_rva & 1 or not 0 <= index < count <= 256:
        raise ValueError('Invalid bounded TBB lookup')
    offset = rva_offset(sections, instruction_rva, 4)
    if data[offset:offset + 4] != bytes.fromhex('dfe802f0'):
        raise ValueError('Expected TBB [PC, r2]')
    table_rva = instruction_rva + 4
    table_offset = rva_offset(sections, table_rva, count)
    target_rva = instruction_rva + 4 + data[table_offset + index] * 2
    rva_offset(sections, target_rva, 2)
    return {'instruction_va': hex(IMAGE_BASE + instruction_rva),
            'index': index, 'table_entries': count,
            'target_va': hex(IMAGE_BASE + target_rva)}


def inspect(data):
    if hashlib.sha256(data).hexdigest() != DRIVER_SHA256:
        raise ValueError('Unsupported driver SHA-256; exact pinned ARM binary required')
    sections = pe_sections(data)
    callback = literal16(data, sections, 0xA698)
    pointer = int(callback['value'], 16)
    if not pointer & 1:
        raise ValueError('Expected a Thumb callback pointer')
    rva_offset(sections, (pointer & ~1) - IMAGE_BASE, 2)
    callback['thumb_target_va'] = hex(pointer & ~1)
    consumer = literal16(data, sections, 0x11E82)
    delay_consumer_base = read_word(data, sections, 0x11F80)
    delay_producer_base = read_word(data, sections, 0x16330)
    return {'schema_version': 1, 'driver_sha256': DRIVER_SHA256,
            'source_commit': SOURCE_COMMIT, 'source_path': SOURCE_PATH,
            'post_unpause_callback_registration': callback,
            'callback_table_consumer': consumer,
            'pre_unpause_directory_dispatch': table_branch(data, sections, 0x14BEC, 0x13, 32),
            'auxiliary_delay_field': {
                'consumer_base': hex(delay_consumer_base), 'consumer_offset': '0x3c',
                'producer_base': hex(delay_producer_base), 'producer_offset': '0x40',
                'consumer_address': hex(delay_consumer_base + 0x3C),
                'producer_address': hex(delay_producer_base + 0x40),
                'same_address': delay_consumer_base + 0x3C == delay_producer_base + 0x40},
            'limits': [
                'Static pointer/branch/address extraction only; no Windows code is executed.',
                'Intermediate stores, function semantics and conditional applicability require the reviewed disassembly in docs/iris-startup-audit.md.',
                'Callback log messages and mechanical-shutter interpretation are not inferred by this extractor.',
                'No hardware activity, sensor transmission, image capture or required new register write is established.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('driver', type=Path)
    parser.add_argument('--output', type=Path, help='New report, never overwritten')
    args = parser.parse_args(argv)
    try:
        if args.driver.stat().st_size != 410112:
            raise ValueError('Expected the pinned 410112-byte ARM driver')
        report = json.dumps(inspect(args.driver.read_bytes()), indent=2) + '\n'
        if args.output:
            with args.output.open('x') as output:
                output.write(report)
        else:
            print(report, end='')
    except (OSError, ValueError) as exc:
        print('Startup inspection failed: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
