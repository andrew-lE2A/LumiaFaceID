"""Synthetic boot containers test preservation and refusal of unsafe formats."""

import contextlib
import gzip
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'repack_boot.py'
SPEC = importlib.util.spec_from_file_location('repack_boot', SCRIPT)
boot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(boot)


def dtb():
    # Minimal FDT: reserve terminator, root begin/end, END, empty strings.
    structure = struct.pack('>I', 1) + b'\0' * 4 + struct.pack('>II', 2, 9)
    return struct.pack('>10I', 0xD00DFEED, 72, 56, 72, 40, 17, 16, 0, 0, 16) + b'\0' * 16 + structure


def kernel(payload=b'kernel fixture'):
    image = bytearray(64)
    image[56:60] = b'ARM\x64'
    return gzip.compress(bytes(image) + payload, mtime=0)


def container(style=2, *, kpad=None):
    page = 4096
    k = kernel() + dtb() + dtb()
    ramdisk = gzip.compress(b'private ramdisk fixture', mtime=0)
    header = bytearray(page)
    header[:8] = b'ANDROID!'
    struct.pack_into('<10I', header, 8, len(k), 32768, len(ramdisk), 33554432,
                     0, 0, 31457280, page, 0, 0x200001AA)
    header[64:64+len(b'fixture cmdline')] = b'fixture cmdline'
    header[608:612] = b'EXT!'
    header[576:608] = boot.boot_id(k, ramdisk, style)
    padding = kpad if kpad is not None else b'\0' * (boot.align(len(k), page) - len(k))
    return bytes(header) + k + padding + ramdisk + b'\0' * (boot.align(len(ramdisk), page) - len(ramdisk)) + b'\0' * (page * 4)


class BootPreservationTests(unittest.TestCase):
    def test_original_kernel_roundtrips_both_checksum_styles_byte_exact(self):
        for style in (1, 2):
            with self.subTest(style=style):
                original = container(style)
                parsed = boot.parse_boot(original)
                rebuilt, info = boot.repack(original, parsed['kernel'])
                self.assertEqual(rebuilt, original)
                self.assertEqual(info['id_style'], 'aosp_v0' if style == 1 else 'legacy_empty_dt')

    def test_unchanged_payload_preserves_nonstandard_padding(self):
        original = container()
        parsed = boot.parse_boot(original)
        padding = b'P' * (parsed['ramdisk_offset'] - parsed['page'] - len(parsed['kernel']))
        original = container(kpad=padding)
        rebuilt, _ = boot.repack(original, boot.parse_boot(original)['kernel'])
        self.assertEqual(rebuilt, original)

    def test_replacement_preserves_private_ramdisk_header_and_board_trees(self):
        original = container()
        before = boot.parse_boot(original)
        replacement = kernel(b'new source-built kernel' * 100)
        result, info = boot.repack(original, replacement)
        after = boot.parse_boot(result)
        self.assertEqual(after['ramdisk'], before['ramdisk'])
        self.assertEqual(after['dtbs'], before['dtbs'])
        self.assertEqual(after['compressed'], replacement)
        self.assertEqual(len(result), len(original))
        self.assertNotEqual(info['boot_sha256'], before['summary']['boot_sha256'])
        changed = set(range(8, 12)) | set(range(576, 608))
        for i in range(before['page']):
            if i not in changed:
                self.assertEqual(result[i], original[i], f'header offset {i}')

    def test_different_device_tree_is_rejected(self):
        changed = bytearray(dtb())
        struct.pack_into('>I', changed, 28, 1)
        with self.assertRaisesRegex(ValueError, 'changes device trees'):
            boot.repack(container(), kernel() + bytes(changed))

    def test_oversized_replacement_does_not_fit(self):
        import random
        payload = random.Random(19).randbytes(50000)
        with self.assertRaisesRegex(ValueError, 'does not fit'):
            boot.repack(container(), kernel(payload))


class InputValidationTests(unittest.TestCase):
    def test_corruption_unknown_id_and_nonzero_signature_are_rejected(self):
        original = container()
        cases = []
        bad_id = bytearray(original); bad_id[576] ^= 1; cases.append(bytes(bad_id))
        bad_crc = bytearray(original); bad_crc[4106] ^= 0xFF; cases.append(bytes(bad_crc))
        signed = bytearray(original); signed[-64:-60] = b'AVBf'; cases.append(bytes(signed))
        cases.extend((original[:100], original[:-1], b'not a boot image'))
        for data in cases:
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                boot.parse_boot(data)

    def test_unsupported_header_second_stage_and_bad_sizes_are_rejected(self):
        for offset, value in ((40, 1), (24, 16), (28, 1024),
                              (36, 3000), (8, 0), (16, 0), (8, 1000000)):
            with self.subTest(offset=offset):
                data = bytearray(container()); struct.pack_into('<I', data, offset, value)
                with self.assertRaises(ValueError):
                    boot.parse_boot(bytes(data))

    def test_gzip_crc_and_arm64_magic_are_required(self):
        for data in (b'not gzip', kernel()[:-3], gzip.compress(b'not ARM64', mtime=0)):
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                boot.kernel_parts(data, require_dtbs=False)

    def test_device_tree_bounds_and_trailing_junk_are_rejected(self):
        variants = [b'', dtb()[:32], dtb() + b'junk']
        for offset, value in ((0, 0), (4, 1000), (8, 1000), (12, 1000), (16, 1000), (20, 16)):
            data = bytearray(dtb()); struct.pack_into('>I', data, offset, value); variants.append(bytes(data))
        for data in variants:
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                boot.check_dtbs(data)


class CliTests(unittest.TestCase):
    def test_inspection_and_repacking_use_only_explicit_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, replacement, output = root/'boot.img', root/'Image.gz', root/'new.img'
            source.write_bytes(container()); replacement.write_bytes(kernel(b'new'))
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(boot.main([str(source), '--inspect']), 0)
            self.assertEqual(json.loads(stdout.getvalue())['header_version'], 0)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(boot.main([str(source), '--kernel', str(replacement), '--output', str(output)]), 0)
            self.assertEqual(source.read_bytes(), container())
            rebuilt = output.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(boot.main([str(source), '--kernel', str(replacement), '--output', str(output)]), 1)
            self.assertEqual(output.read_bytes(), rebuilt)

    def test_failed_validation_leaves_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, replacement, output = root/'boot.img', root/'Image.gz', root/'new.img'
            source.write_bytes(container()); replacement.write_bytes(b'bad kernel')
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(boot.main([str(source), '--kernel', str(replacement), '--output', str(output)]), 1)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
