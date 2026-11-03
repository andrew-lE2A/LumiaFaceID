#!/usr/bin/env python3
"""Inspect/repack the legacy cityman boot format, retaining ramdisk and DTBs.

Only unsigned header-v0 images with a verified SHA-1 ID, no second-stage
payload and zero partition padding are supported. This tool never flashes.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib


MAX_SIZE = 128 * 1024 * 1024


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def align(value, page):
    return (value + page - 1) // page * page


def gzip_member(data):
    try:
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        image = decoder.decompress(data, MAX_SIZE + 1)
    except zlib.error as exc:
        raise ValueError(f"Invalid gzip stream: {exc}") from exc
    if len(image) > MAX_SIZE or not decoder.eof:
        raise ValueError("Truncated or oversized gzip stream")
    used = len(data) - len(decoder.unused_data)
    return image, data[:used], decoder.unused_data


def check_dtbs(data):
    if not data:
        raise ValueError("Expected appended device trees")
    result = []
    offset = 0
    while offset < len(data):
        if len(data) - offset < 40:
            raise ValueError("Truncated device-tree header")
        fields = struct.unpack_from('>10I', data, offset)
        magic, size, dtstruct, strings, reserve, version, compatible, _, nstrings, nstruct = fields
        if (magic != 0xD00DFEED or size < 40 or offset + size > len(data)
                or version != 17 or compatible > version
                or dtstruct < 40 or dtstruct + nstruct > size
                or strings < 40 or strings + nstrings > size
                or reserve < 40 or reserve + 16 > size):
            raise ValueError("Invalid appended device tree")
        blob = data[offset:offset + size]
        result.append({"size": size, "sha256": sha256(blob)})
        offset += size
    return result


def kernel_parts(data, require_dtbs=True):
    image, compressed, dtbs = gzip_member(data)
    if len(image) < 64 or image[56:60] != b'ARM\x64':
        raise ValueError("Expected an ARM64 Image inside the gzip stream")
    if dtbs or require_dtbs:
        check_dtbs(dtbs)
    return compressed, dtbs


def boot_id(kernel, ramdisk, zero_terms):
    digest = hashlib.sha1()
    for part in (kernel, ramdisk):
        digest.update(part)
        digest.update(struct.pack('<I', len(part)))
    digest.update(b'\0' * (4 * zero_terms))
    return digest.digest() + b'\0' * 12


def parse_boot(data):
    if len(data) > MAX_SIZE or len(data) < 1632 or data[:8] != b'ANDROID!':
        raise ValueError("Expected a bounded legacy Android boot image")
    ks, ka, rs, ra, ss, sa, tags, page, version, osv = struct.unpack_from('<10I', data, 8)
    if version != 0 or ss != 0 or sa != 0:
        raise ValueError("Only header-v0 images without a second stage are supported")
    if page not in (2048, 4096, 8192, 16384) or len(data) % page:
        raise ValueError("Invalid page/partition size")
    ro = page + align(ks, page)
    end = ro + align(rs, page)
    if not ks or not rs or end > len(data):
        raise ValueError("Truncated or empty boot payload")
    if any(data[end:]):
        raise ValueError("Nonzero trailing data/signature: refusing to strip or invalidate it")
    kernel, ramdisk = data[page:page + ks], data[ro:ro + rs]
    compressed, dtbs = kernel_parts(kernel)
    styles = [count for count in (1, 2) if data[576:608] == boot_id(kernel, ramdisk, count)]
    if len(styles) != 1:
        raise ValueError("Unrecognized boot ID; refusing to guess its checksum convention")
    return {"data": data, "kernel": kernel, "compressed": compressed, "dtbs": dtbs,
            "ramdisk": ramdisk, "page": page, "ramdisk_offset": ro, "payload_end": end,
            "zero_terms": styles[0],
            "summary": {"header_version": version, "page_size": page,
                        "partition_size": len(data), "kernel_size": ks, "ramdisk_size": rs,
                        "kernel_address": ka, "ramdisk_address": ra, "tags_address": tags,
                        "os_version_word": osv, "boot_sha256": sha256(data),
                        "ramdisk_sha256": sha256(ramdisk), "dtbs": check_dtbs(dtbs),
                        "id_style": "aosp_v0" if styles[0] == 1 else "legacy_empty_dt"}}


def repack(original, replacement):
    boot = parse_boot(original)
    compressed, replacement_dtbs = kernel_parts(replacement, require_dtbs=False)
    if replacement_dtbs and replacement_dtbs != boot['dtbs']:
        raise ValueError("Replacement changes device trees; this tool preserves the original board layout")
    kernel = compressed + boot['dtbs']
    page = boot['page']
    header = bytearray(original[:page])
    struct.pack_into('<I', header, 8, len(kernel))
    header[576:608] = boot_id(kernel, boot['ramdisk'], boot['zero_terms'])
    # Preserve component padding when its length remains valid, so an unchanged
    # input round-trips byte for byte, including nonstandard header padding.
    old_kpad = original[page + len(boot['kernel']):boot['ramdisk_offset']]
    kpad_size = align(len(kernel), page) - len(kernel)
    kpad = old_kpad if len(old_kpad) == kpad_size else b'\0' * kpad_size
    rpad = original[boot['ramdisk_offset'] + len(boot['ramdisk']):boot['payload_end']]
    result = bytes(header) + kernel + kpad + boot['ramdisk'] + rpad
    if len(result) > len(original):
        raise ValueError("Replacement does not fit the original boot partition")
    result += b'\0' * (len(original) - len(result))
    verified = parse_boot(result)
    if verified['ramdisk'] != boot['ramdisk'] or verified['dtbs'] != boot['dtbs']:
        raise ValueError("Repack preservation check failed")
    return result, verified['summary']


def read_file(path):
    if path.stat().st_size > MAX_SIZE:
        raise ValueError("Input file is too large")
    return path.read_bytes()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('boot', type=Path, help='uncompressed current boot-partition backup')
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--inspect', action='store_true')
    modes.add_argument('--kernel', type=Path, help='replacement ARM64 Image.gz')
    parser.add_argument('--output', type=Path, help='new image file; never overwritten')
    args = parser.parse_args(argv)
    if bool(args.output) != bool(args.kernel):
        parser.error('--output is required only with --kernel')
    try:
        original = read_file(args.boot)
        if args.inspect:
            summary = parse_boot(original)['summary']
        else:
            data, summary = repack(original, read_file(args.kernel))
            with args.output.open('xb') as output:
                output.write(data)
        print(json.dumps(summary, indent=2))
    except (OSError, ValueError) as exc:
        print(f'Boot operation failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
