#!/usr/bin/env python3
"""Pull one confirmed non-person RAW10 capture from a debuggable probe app.

The tool validates the app-private sidecar and RAW10 plane size, stores the
source and sidecar under a new output subdirectory, then renders candidate
Windows eye views at rotations 0 and 90. It never requests a camera capture.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


RAW_NAME = re.compile(r"iris-camera2-raw10-[A-Za-z0-9_-]+\.raw10\Z")


def adb_command(adb, serial, *args):
    serial_args = ["-s", serial] if serial else []
    return [adb, *serial_args, *args]


def run_adb(adb, serial, *args):
    result = subprocess.run(
        adb_command(adb, serial, *args),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ADB command failed ({result.returncode}): {detail}")
    return result.stdout


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, help="debuggable probe package installed on the phone")
    parser.add_argument("--serial", help="ADB serial when more than one device is connected")
    parser.add_argument("--adb", default="adb", help="ADB executable (default: adb on PATH)")
    parser.add_argument("--output-dir", required=True, type=Path,
                        help="new output directory; existing files are never overwritten")
    parser.add_argument("--crop-left", type=int, default=300,
                        help="left crop used by the current Windows-shaped model (default: 300)")
    parser.add_argument("--confirm-non-person-target", action="store_true",
                        help="confirm the captured frame contains only a diffuse non-person target")
    args = parser.parse_args()
    if not args.confirm_non_person_target:
        parser.error("retrieve only a frame captured from a diffuse non-person target; pass --confirm-non-person-target")
    if args.crop_left < 0:
        parser.error("--crop-left must be non-negative")
    return args


def main():
    args = parse_args()
    try:
        listing = run_adb(args.adb, args.serial, "exec-out", "run-as", args.package,
                          "ls", "files").decode("utf-8", errors="strict")
        names = [line.strip() for line in listing.splitlines() if RAW_NAME.fullmatch(line.strip())]
        if len(names) != 1:
            raise ValueError(f"expected exactly one app-private RAW10 file, found {len(names)}: {names}")

        raw_name = names[0]
        sidecar_name = raw_name + ".json"
        raw = run_adb(args.adb, args.serial, "exec-out", "run-as", args.package,
                      "cat", f"files/{raw_name}")
        metadata_bytes = run_adb(args.adb, args.serial, "exec-out", "run-as", args.package,
                                 "cat", f"files/{sidecar_name}")
        metadata = json.loads(metadata_bytes)

        if metadata.get("format") != "MIPI_RAW10" or metadata.get("irEnabled") is not False:
            raise ValueError("sidecar must identify MIPI_RAW10 with irEnabled=false")
        width = int(metadata["width"])
        height = int(metadata["height"])
        stride = int(metadata["rowStrideBytes"])
        byte_count = int(metadata["byteCount"])
        crop = metadata.get("crop")
        if width <= 0 or height <= 0 or stride <= 0 or byte_count != len(raw):
            raise ValueError("invalid dimensions, stride, or byte count in the RAW10 sidecar")
        if crop != [0, 0, width, height]:
            raise ValueError(f"only a full-array RAW10 crop is supported, got {crop}")
        row_bytes = ((width + 3) // 4) * 5
        required = stride * (height - 1) + row_bytes
        if stride < row_bytes or len(raw) < required:
            raise ValueError(f"RAW10 buffer too short: {len(raw)} bytes; requires at least {required}")
        if args.crop_left >= width:
            raise ValueError("left crop would remove the full frame")

        output_dir = args.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        capture_dir = output_dir / f"camera{metadata.get('cameraId', 'unknown')}-t{metadata['timestampNs']}"
        capture_dir.mkdir(exist_ok=False)
        raw_path = capture_dir / raw_name
        sidecar_path = capture_dir / sidecar_name
        raw_path.write_bytes(raw)
        sidecar_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

        converter = Path(__file__).with_name("windows_frame.py")
        for rotation in (0, 90):
            prefix = capture_dir / f"windows-rotation-{rotation}"
            command = [
                sys.executable, str(converter), str(raw_path), str(prefix),
                "--format", "raw10", "--width", str(width), "--height", str(height),
                "--stride", str(stride), "--crop-left", str(args.crop_left),
                "--rotation", str(rotation),
            ]
            subprocess.run(command, check=True)

        print(f"Saved validated RAW10 capture and sidecar under {capture_dir}")
        print("Candidate view images were generated for rotations 0 and 90.")
        print("These files are diagnostic only; they are not enrollment templates or matcher inputs.")
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError,
            subprocess.CalledProcessError) as exc:
        raise SystemExit(f"pull_and_convert_raw10: {exc}")


if __name__ == "__main__":
    main()
