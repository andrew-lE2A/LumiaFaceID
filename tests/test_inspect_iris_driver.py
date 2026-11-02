"""Offline parser tests use synthetic PE data, never redistributed driver bytes."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "inspect_iris_driver.py"
SPEC = importlib.util.spec_from_file_location("inspect_iris_driver", SCRIPT)
inspector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inspector)


def synthetic_pe(entries=(), *, terminate=True):
    """A deliberately synthetic ARM PE32 with a small file-backed .rdata."""
    data = bytearray(0x300)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", data, 0x84, 0x1C4, 1)
    struct.pack_into("<H", data, 0x94, 96)
    struct.pack_into("<H", data, 0x98, 0x10B)
    struct.pack_into("<8sIIII", data, 0xF8, b".rdata\0\0", 0x200, 0x1000, 0x100, 0x200)
    for index, entry in enumerate(entries):
        struct.pack_into("<HBBI", data, 0x200 + index * 8, *entry)
    if terminate:
        struct.pack_into("<HBBI", data, 0x200 + len(entries) * 8, 0, 0, 0, 0)
    return bytes(data)


class PeMappingTests(unittest.TestCase):
    def test_synthetic_section_mapping_and_file_offsets(self):
        data = synthetic_pe()
        sections = inspector.pe_sections(data)
        self.assertEqual(sections, [{"name": ".rdata", "rva": 0x1000,
                                    "raw_size": 0x100, "raw_offset": 0x200,
                                    "virtual_size": 0x200}])
        self.assertEqual(inspector.rva_offset(sections, 0x1020, 8), 0x220)
        self.assertEqual(inspector.rva_offset(sections, 0x10F8, 8), 0x2F8)

    def test_unbacked_virtual_tail_and_boundary_crossing_are_rejected(self):
        sections = inspector.pe_sections(synthetic_pe())
        for rva, size in ((0x0FFF, 8), (0x10FC, 8), (0x1100, 1), (0x11F0, 8)):
            with self.subTest(rva=rva, size=size), self.assertRaises(ValueError):
                inspector.rva_offset(sections, rva, size)
        with self.assertRaises(ValueError):
            inspector.rva_offset(sections + sections, 0x1000, 8)

    def test_bad_headers_architecture_and_truncation_are_rejected(self):
        original = synthetic_pe()
        variants = [b"", b"MZ", original[:0x3F], original[:0x98], original[:0x105]]
        for offset, fmt, value in ((0x3C, "<I", 0x10000),
                                   (0x84, "<H", 0x8664),
                                   (0x86, "<H", 0),
                                   (0x86, "<H", 97),
                                   (0x94, "<H", 95),
                                   (0x98, "<H", 0x20B),
                                   (0x108, "<I", 0x10000)):
            changed = bytearray(original)
            struct.pack_into(fmt, changed, offset, value)
            variants.append(bytes(changed))
        for data in variants:
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                inspector.pe_sections(data)


class ProbeDescriptorTests(unittest.TestCase):
    def test_descriptor_order_original_convention_and_offsets_are_preserved(self):
        data = synthetic_pe(((0, 0x6C, 0, 2), (0xF0, 0x78, 0, 1), (3, 0x20, 0, 2)))
        result = inspector.probe_table(data, inspector.pe_sections(data), 0x1000)
        self.assertEqual([x["slave_address_field"] for x in result], ["0x6c", "0x78", "0x20"])
        self.assertEqual([x["register"] for x in result], ["0x0000", "0x00f0", "0x0003"])
        self.assertEqual([x["register_address_bytes"] for x in result], [2, 1, 2])
        self.assertEqual([x["file_offset"] for x in result], ["0x200", "0x208", "0x210"])
        self.assertEqual([x["branch_label"] for x in result], ["Siiri", "Vespa", "generic SMIA++"])
        self.assertFalse(any("sensor_model" in x or "linux_i2c_address" in x for x in result))

    def test_zero_terminator_stops_before_unrelated_following_bytes(self):
        data = bytearray(synthetic_pe(((3, 0x20, 0, 2),)))
        data[0x210:0x218] = b"\xff" * 8
        result = inspector.probe_table(bytes(data), inspector.pe_sections(data), 0x1000)
        self.assertEqual(len(result), 1)

    def test_invalid_slave_reserved_and_width_are_rejected(self):
        for entry in ((0, 0x6D, 0, 2), (0, 0x6C, 1, 2),
                      (0, 0x6C, 0, 0), (0, 0x6C, 0, 3)):
            with self.subTest(entry=entry):
                data = synthetic_pe((entry,))
                with self.assertRaisesRegex(ValueError, "Unexpected probe descriptor"):
                    inspector.probe_table(data, inspector.pe_sections(data), 0x1000)

    def test_missing_terminator_is_bounded_and_does_not_scan_other_data(self):
        data = synthetic_pe(((3, 0x20, 0, 2),) * 16, terminate=False)
        with self.assertRaisesRegex(ValueError, "bounded terminator"):
            inspector.probe_table(data, inspector.pe_sections(data), 0x1000)

    def test_descriptor_cannot_cross_end_of_file_backed_section(self):
        data = synthetic_pe()
        with self.assertRaises(ValueError):
            inspector.probe_table(data, inspector.pe_sections(data), 0x10FC)


class PinnedInputAndCliTests(unittest.TestCase):
    def test_synthetic_pe_is_not_accepted_as_a_genuine_pinned_driver(self):
        # Do not patch DRIVER_SHA256 to manufacture successful inspection.
        with self.assertRaisesRegex(ValueError, "Unsupported driver SHA-256"):
            inspector.inspect_driver(synthetic_pe(((0, 0x6C, 0, 2),)))

    def test_cli_rejects_wrong_size_and_same_size_changed_content_without_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.sys"
            output = Path(directory) / "report.json"
            for data, message in ((b"MZ", "Unsupported driver size"),
                                  (b"\0" * 410112, "Unsupported driver SHA-256")):
                with self.subTest(length=len(data)):
                    source.write_bytes(data)
                    stderr = io.StringIO()
                    with contextlib.redirect_stderr(stderr):
                        code = inspector.main([str(source), "--output", str(output)])
                    self.assertEqual(code, 1)
                    self.assertIn(message, stderr.getvalue())
                    self.assertFalse(output.exists())

    def test_cli_never_overwrites_existing_output_after_inspection(self):
        # Mock the inspection boundary only to reach exclusive-file creation;
        # this does not test or claim genuine input verification success.
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.sys"
            output = Path(directory) / "report.json"
            source.write_bytes(b"\0" * 410112)
            output.write_text("existing evidence\n")
            with mock.patch.object(inspector, "inspect_driver", return_value={"fixture": True}) as inspect:
                with contextlib.redirect_stderr(io.StringIO()):
                    code = inspector.main([str(source), "--output", str(output)])
            self.assertEqual(code, 1)
            self.assertEqual(output.read_text(), "existing evidence\n")
            inspect.assert_called_once_with(source.read_bytes())

    def test_cli_serializes_inspection_result_to_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.sys"
            source.write_bytes(b"\0" * 410112)
            stdout = io.StringIO()
            with mock.patch.object(inspector, "inspect_driver", return_value={"fixture": "serialization-only"}):
                with contextlib.redirect_stdout(stdout):
                    code = inspector.main([str(source)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout.getvalue()), {"fixture": "serialization-only"})


if __name__ == "__main__":
    unittest.main()
