#!/usr/bin/env python3
"""Extract probe descriptors from the exact, pinned original ARM iris driver.

Offline inspection only: this program never loads or executes the Windows
driver and contains no device, ADB, I2C, or illumination commands.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys


DRIVER_SHA256 = "0ea99897a1623afd7f165aa2943f2f69687c31dc42a123d6d21c2339ca8e78e5"
SOURCE_COMMIT = "b5af93f99ea800c28551727df55e57a07ba61a82"
SOURCE_PATH = ("components/QC899X/Hardware/HARDWARE.CAMERA.MMO_8994/Drivers/Camera/"
               "Sensors/Iris/arm/qccamsensor_tertiarySMIApp8994.sys")
TABLE_RVAS = {"primary": 0x3A058, "secondary": 0x3A518, "tertiary": 0x3A168}
BRANCH_LABELS = {0x20: "generic SMIA++", 0x6C: "Siiri", 0x78: "Vespa"}


def unpack(data, offset, fmt):
    size = struct.calcsize(fmt)
    if offset < 0 or offset + size > len(data):
        raise ValueError("Truncated PE data")
    return struct.unpack_from(fmt, data, offset)


def pe_sections(data):
    """Read the ARM PE32 section map; no native Windows loading occurs."""
    if data[:2] != b"MZ":
        raise ValueError("Not a DOS/PE image")
    pe_offset, = unpack(data, 0x3C, "<I")
    if data[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise ValueError("Missing PE signature")
    machine, count = unpack(data, pe_offset + 4, "<HH")
    optional_size, = unpack(data, pe_offset + 20, "<H")
    magic, = unpack(data, pe_offset + 24, "<H")
    if machine != 0x1C4 or magic != 0x10B or optional_size < 96:
        raise ValueError("Expected an ARMNT PE32 driver")
    if not 0 < count <= 96:
        raise ValueError("Invalid PE section count")
    start = pe_offset + 24 + optional_size
    sections = []
    for i in range(count):
        record = start + i * 40
        name, virtual_size, rva, raw_size, raw_offset = unpack(data, record, "<8sIIII")
        if raw_offset + raw_size > len(data):
            raise ValueError("PE section extends beyond file")
        sections.append({"name": name.rstrip(b"\0").decode("ascii", errors="replace"),
                         "rva": rva, "raw_size": raw_size, "raw_offset": raw_offset,
                         "virtual_size": virtual_size})
    return sections


def rva_offset(sections, rva, size):
    matches = [s for s in sections if s["rva"] <= rva and
               rva + size <= s["rva"] + s["raw_size"]]
    if len(matches) != 1:
        raise ValueError("RVA is not in exactly one file-backed PE section")
    section = matches[0]
    return section["raw_offset"] + rva - section["rva"]


def probe_table(data, sections, rva):
    entries = []
    for index in range(16):
        offset = rva_offset(sections, rva + index * 8, 8)
        register, address, reserved, width = unpack(data, offset, "<HBBI")
        if (register, address, reserved, width) == (0, 0, 0, 0):
            return entries
        if reserved or width not in (1, 2) or address not in BRANCH_LABELS:
            raise ValueError("Unexpected probe descriptor")
        entries.append({"file_offset": f"0x{offset:x}",
                        "register": f"0x{register:04x}",
                        "slave_address_field": f"0x{address:02x}",
                        "register_address_bytes": width,
                        "branch_label": BRANCH_LABELS[address]})
    raise ValueError("Probe table has no bounded terminator")


def inspect_driver(data):
    digest = hashlib.sha256(data).hexdigest()
    if digest != DRIVER_SHA256:
        raise ValueError("Unsupported driver SHA-256; this inspector requires the pinned ARM binary")
    sections = pe_sections(data)
    tables = {name: probe_table(data, sections, rva) for name, rva in TABLE_RVAS.items()}
    return {"schema_version": 1, "source_commit": SOURCE_COMMIT,
            "source_path": SOURCE_PATH, "sha256": digest,
            "scope": "Static probe descriptors only; no hardware access or sensor identification",
            "tables": tables,
            "limitations": [
                "Table entries are driver-supported candidates, not confirmed physical sensor addresses.",
                "Selection control flow and transfer semantics require separate disassembly; this tool only extracts tables.",
                "The slave-address field is retained in its original convention; no Linux I2C address is asserted.",
                "These descriptors do not establish CCI master, sensor power sequencing, initialization, or IR exposure limits.",
            ]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("driver", type=Path, help="local original ARM qccamsensor_tertiarySMIApp8994.sys")
    parser.add_argument("--output", type=Path, help="new JSON file; defaults to standard output")
    args = parser.parse_args(argv)
    try:
        if args.driver.stat().st_size != 410112:
            raise ValueError("Unsupported driver size; expected the pinned 410112-byte ARM binary")
        report = inspect_driver(args.driver.read_bytes())
        payload = json.dumps(report, indent=2) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as output:
                output.write(payload)
        else:
            sys.stdout.write(payload)
    except (OSError, ValueError) as exc:
        print(f"Inspection failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
