#!/usr/bin/env python3
"""Prepare a private, pinned sensor-stream profile; no phone or hardware access."""
import argparse
import hashlib
import http.client
from pathlib import Path
import sys
import urllib.request

from inspect_iris_dcc import (DCC_SIZE, SOURCE_COMMIT, SOURCE_PATH,
                              inspect_dcc, parse_directory, register_records)

PROGRAM_SHA256 = '75478697398abf8b21796d408844249af54e05ae7a399afffc33d51dd83e8eb5'


def prepare(data):
    inspect_dcc(data)  # Exact original file, not a structurally similar input.
    blocks = {tag: payload for tag, _, payload in parse_directory(data)}
    if len(register_records(blocks[0])) != 87 or len(register_records(blocks[0xFF00])) != 30:
        raise ValueError('Unexpected sensor program record counts')
    program = blocks[0][:-3] + blocks[0xFF00][:-3]
    if len(program) != 351 or hashlib.sha256(program).hexdigest() != PROGRAM_SHA256:
        raise ValueError('Unexpected sensor program digest')
    return program.hex() + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dcc', type=Path, nargs='?', help='local pinned 0C086101.dcc')
    parser.add_argument('--download', action='store_true', help='fetch the pinned public input over HTTPS')
    parser.add_argument('--output', type=Path, required=True, help='new private .hex file')
    args = parser.parse_args(argv)
    if bool(args.dcc) == args.download:
        parser.error('Provide either a local DCC or --download')
    try:
        if args.download:
            url = f'https://raw.githubusercontent.com/WOA-Project/Lumia-Drivers/{SOURCE_COMMIT}/{SOURCE_PATH}'
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read(DCC_SIZE + 1)
        else:
            if args.dcc.stat().st_size != DCC_SIZE:
                raise ValueError('Expected the pinned 496797-byte DCC')
            data = args.dcc.read_bytes()
        profile = prepare(data)
        with args.output.open('x', encoding='ascii') as output:
            output.write(profile)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        print(f'Preparation failed: {exc}', file=sys.stderr)
        return 1
    print(f'Private profile saved: {args.output}; program SHA-256 {PROGRAM_SHA256}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
