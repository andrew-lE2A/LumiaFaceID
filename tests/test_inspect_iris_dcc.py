"""Synthetic DCC records only; original calibration bytes are not fixtures."""
import contextlib
import importlib.util
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / 'tools/inspect_iris_dcc.py'
SPEC = importlib.util.spec_from_file_location('inspect_iris_dcc', SCRIPT)
inspector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inspector)


def container(blocks):
    data = bytearray(0x38)
    struct.pack_into('>I', data, 0, 31)
    data[0x34] = len(blocks)
    data.extend(b''.join(struct.pack('>HI', tag, len(payload)) for tag, payload in blocks))
    data.extend(b''.join(payload for _, payload in blocks))
    data.extend(b'END!')  # Opaque trailer; no checksum algorithm is asserted.
    struct.pack_into('>I', data, 4, len(data))
    return bytes(data)


class DccDirectoryTests(unittest.TestCase):
    def test_sequential_offsets_unknown_blocks_and_trailer_are_preserved(self):
        blocks = [(0x20, b'opaque'), (5, b'\x00\x40\x01\0\0\0'),
                  (0xFF00, b'\x03\x4c\x05\0\0\0')]
        data = container(blocks)
        result = inspector.parse_directory(data)
        self.assertEqual([tag for tag, _, _ in result], [tag for tag, _ in blocks])
        self.assertEqual([payload for _, _, payload in result], [p for _, p in blocks])
        self.assertEqual([off for _, off, _ in result], [0x4A, 0x50, 0x56])

    def test_truncated_header_wrong_format_and_size_are_rejected(self):
        original = container([(0, b'\0\0\0')])
        variants = [b'', original[:0x37], original[:-1]]
        for offset, value in [(0, 30), (4, len(original) + 1)]:
            changed = bytearray(original)
            struct.pack_into('>I', changed, offset, value)
            variants.append(changed)
        for data in variants:
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                inspector.parse_directory(data)

    def test_zero_count_and_truncated_directory_are_rejected(self):
        for count in [0, 255]:
            data = bytearray(container([(0, b'\0\0\0')]))
            data[0x34] = count
            with self.subTest(count=count), self.assertRaises(ValueError):
                inspector.parse_directory(data)

    def test_duplicate_id_empty_block_and_out_of_bounds_length_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            inspector.parse_directory(container([(0, b'x'), (0, b'y')]))
        for size in [0, 100, 0xFFFFFFFF]:
            data = bytearray(container([(0, b'abc')]))
            struct.pack_into('>I', data, 0x3A, size)
            with self.subTest(size=size), self.assertRaises(ValueError):
                inspector.parse_directory(data)

    def test_unaccounted_payload_is_not_silently_discarded(self):
        data = bytearray(container([(0, b'abc')]))
        struct.pack_into('>I', data, 0x3A, 2)
        with self.assertRaisesRegex(ValueError, 'Unaccounted'):
            inspector.parse_directory(data)


class DccRecordTests(unittest.TestCase):
    def test_big_endian_register_records_preserve_commands_without_execution(self):
        self.assertEqual(inspector.register_records(b'\x03\x4c\x05\xff\xf9\x07\0\0\0'),
                         [(0x034C, 5), (0xFFF9, 7)])

    def test_misaligned_missing_and_early_terminator_are_rejected(self):
        for payload in [b'', b'\0', b'\0\0\0x', b'\x03\x4c\x05',
                        b'\0\0\0\x03\x4c\x05\0\0\0']:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                inspector.register_records(payload)

    def test_summary_uses_present_byte_pairs_and_keeps_missing_fields_unknown(self):
        summary = inspector.mode_summary([(0x034C, 5), (0x034D, 0),
                                          (0x034E, 2), (0x034F, 0xD0),
                                          (0x0112, 0xA), (0x0113, 0xA),
                                          (0x0114, 0), (0xFFF9, 7)])
        self.assertEqual(summary['output_width'], 1280)
        self.assertEqual(summary['output_height'], 720)
        self.assertEqual(summary['csi_data_format_register'], 0x0A0A)
        self.assertEqual(summary['csi_lane_mode_register'], 0)
        self.assertIsNone(summary['frame_length_register'])
        self.assertFalse(summary['mode_select_present'])
        self.assertEqual(summary['special_command_addresses'], ['0xfff9'])
        self.assertIsNone(inspector.mode_summary([(0x034C, 5)])['output_width'])

    def test_clock_summary_keeps_partial_words_unknown_and_decodes_msb_first(self):
        words = inspector.mode_summary([(0x0130, 0x12), (0x0131, 0x34),
                                        (0x0300, 0x56), (0x0301, 0x78),
                                        (0x0302, 0x9a)])['programmed_clock_words']
        self.assertEqual(words['0x0130'], 0x1234)
        self.assertEqual(words['0x0300'], 0x5678)
        self.assertIsNone(words['0x0302'])
        self.assertIsNone(words['0x0308'])
        self.assertEqual(len(words), 7)

    def test_duplicate_mode_register_is_not_summarized_as_last_write_wins(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate register'):
            inspector.mode_summary([(0x034C, 5), (0x034C, 7)])


class DccPinnedInputTests(unittest.TestCase):
    def test_synthetic_input_cannot_pass_genuine_identity_check(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported DCC size/SHA-256'):
            inspector.inspect_dcc(container([(0, b'\0\0\0')]))

    def test_cli_rejects_wrong_size_and_changed_input_without_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.dcc'
            output = Path(directory) / 'output.json'
            for data in [b'bad', bytes(inspector.DCC_SIZE)]:
                source.write_bytes(data)
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(inspector.main([str(source), '--output', str(output)]), 1)
                self.assertFalse(output.exists())

    def test_cli_preserves_existing_output(self):
        # Mock the inspection boundary only to check exclusive file creation.
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.dcc'
            output = Path(directory) / 'output.json'
            source.write_bytes(bytes(inspector.DCC_SIZE))
            output.write_text('existing evidence\n')
            with mock.patch.object(inspector, 'inspect_dcc', return_value={'fixture': True}):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(inspector.main([str(source), '--output', str(output)]), 1)
            self.assertEqual(output.read_text(), 'existing evidence\n')


if __name__ == '__main__':
    unittest.main()
