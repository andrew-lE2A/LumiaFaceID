"""Synthetic Thumb snippets; no original driver bytes are distributed."""
import sys
from pathlib import Path
import struct
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import inspect_iris_startup as startup


def fixture():
    data = bytearray(128)
    sections = [{'rva': 0x1000, 'raw_size': len(data), 'raw_offset': 0}]
    return data, sections


class StartupLinksTests(unittest.TestCase):
    def test_literal_load_aligns_pc_before_adding_scaled_offset(self):
        data, sections = fixture()
        struct.pack_into('<H', data, 2, 0x4B03)  # r3; Align(0x1006,4) + 12
        struct.pack_into('<I', data, 16, 0x401031)
        row = startup.literal16(data, sections, 0x1002)
        self.assertEqual(row['literal_va'], '0x401010')
        self.assertEqual(row['destination_register'], 'r3')
        self.assertEqual(row['value'], '0x401031')

    def test_literal_rejects_wrong_opcode_alignment_and_unbacked_pool(self):
        data, sections = fixture()
        for rva, opcode in ((0x1000, 0x2000), (0x1001, 0x4800), (0x1000, 0x48FF)):
            struct.pack_into('<H', data, rva - 0x1000, opcode)
            with self.assertRaises(ValueError):
                startup.literal16(data, sections, rva)

    def test_tbb_target_uses_pc_plus_twice_the_unsigned_byte(self):
        data, sections = fixture()
        data[:4] = bytes.fromhex('dfe802f0')
        data[4:7] = bytes([2, 5, 7])
        result = startup.table_branch(data, sections, 0x1000, 1, 3)
        self.assertEqual(result['target_va'], '0x40100e')

    def test_tbb_rejects_bad_bounds_opcode_or_unbacked_target(self):
        data, sections = fixture()
        data[:4] = bytes.fromhex('dfe802f0')
        data[4] = 255
        for index, count in ((-1, 3), (3, 3), (0, 257), (0, 3)):
            with self.assertRaises(ValueError):
                startup.table_branch(data, sections, 0x1000, index, count)
        data[:4] = b'\0' * 4
        with self.assertRaises(ValueError):
            startup.table_branch(data, sections, 0x1000, 0, 1)

    def test_unpinned_input_rejected_before_interpreting_code(self):
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            startup.inspect(bytes(410112))


if __name__ == '__main__':
    unittest.main()
