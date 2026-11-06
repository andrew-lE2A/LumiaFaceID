#!/usr/bin/env python3
"""Convert an iris RAW frame into a diagnostic approximation of Windows input.

Recovered Windows steps: take the top eight bits of RAW10, crop the leftmost
300 columns, then split into two overlapping eye images. The actual Windows
RAW unpacking/tone curve and rotation value for Cityman remain unknown; this
tool makes those assumptions explicit and is for inspection only.
"""

import argparse
import statistics
from pathlib import Path


def unpack_pixels(data: bytes, fmt: str, width: int, height: int, stride: int):
    """Yield one row-major image from packed MIPI RAW10 or little-endian RAW16."""
    row_bytes = ((width + 3) // 4) * 5 if fmt == "raw10" else width * 2
    required = stride * (height - 1) + row_bytes
    if stride < row_bytes:
        raise ValueError(f"stride {stride} is shorter than required row bytes {row_bytes}")
    if len(data) < required:
        raise ValueError(f"input is {len(data)} bytes; dimensions require at least {required}")

    for y in range(height):
        row = data[y * stride:y * stride + row_bytes]
        if fmt == "raw10":
            pixels = []
            for group_start in range(0, row_bytes, 5):
                group = row[group_start:group_start + 5]
                for i in range(min(4, width - len(pixels))):
                    raw10 = (group[i] << 2) | ((group[4] >> (2 * i)) & 0x03)
                    pixels.append(raw10 >> 2)
            yield pixels[:width]
        else:
            yield [(row[2 * x] | (row[2 * x + 1] << 8)) >> 8 for x in range(width)]


def image_stats(rows):
    values = sorted(v for row in rows for v in row)
    n = len(values)
    if not n:
        raise ValueError("cannot calculate statistics for an empty image")

    def percentile(p):
        return values[min(n - 1, (p * n) // 100)]

    return {
        "mean": round(statistics.fmean(values), 1),
        "median": percentile(50),
        "p90": percentile(90),
        "p95": percentile(95),
        "p99": percentile(99),
    }


def write_pgm(path: Path, rows):
    height = len(rows)
    width = len(rows[0])
    payload = bytes(value for row in rows for value in row)
    path.write_bytes(f"P5\n{width} {height}\n255\n".encode("ascii") + payload)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output_prefix", type=Path)
    parser.add_argument("--format", choices=("raw10", "raw16"), default="raw10")
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--stride", type=int, required=True, help="bytes per source row")
    parser.add_argument("--crop-left", type=int, default=300)
    parser.add_argument("--crop-right", type=int, default=0)
    parser.add_argument("--rotation", type=int, choices=(0, 90, 180, 270), required=True,
                        help="Windows rotation input; Cityman's value is not yet known")
    args = parser.parse_args()
    if min(args.width, args.height, args.stride) <= 0:
        parser.error("width, height and stride must be positive")
    if args.crop_left < 0 or args.crop_right < 0:
        parser.error("crop values must be non-negative")
    return args


def main():
    args = parse_args()
    try:
        source = list(unpack_pixels(args.input.read_bytes(), args.format,
                                    args.width, args.height, args.stride))
        end = args.width - args.crop_right
        if not 0 <= args.crop_left < end <= args.width:
            raise ValueError("left/right crop leaves no image")
        frame = [row[args.crop_left:end] for row in source]
        width, height = len(frame[0]), len(frame)

        if args.rotation in (0, 180):
            overlap = min(300, width // 2)
            half = (width + overlap) // 2
            first = [row[:half] for row in frame]
            second = [row[width - half:] for row in frame]
            split_axis = "width"
        else:
            overlap = min(300, height // 2)
            half = (height + overlap) // 2
            first, second = frame[:half], frame[height - half:]
            split_axis = "height"

        eyes = (second, first) if args.rotation in (180, 270) else (first, second)
        prefix = args.output_prefix
        write_pgm(prefix.with_name(prefix.name + "-frame.pgm"), frame)
        for index, eye in enumerate(eyes):
            write_pgm(prefix.with_name(prefix.name + f"-eye{index}.pgm"), eye)

        print(f"frame {width}x{height}; engine size floor 640x480: "
              f"{'met' if width >= 640 and height >= 480 else 'not met'}")
        print(f"rotation {args.rotation}; split axis {split_axis}; overlap {overlap}px")
        print(f"frame stats {image_stats(frame)}")
        for index, eye in enumerate(eyes):
            print(f"eye{index} {len(eye[0])}x{len(eye)} stats {image_stats(eye)}")
    except (OSError, ValueError) as exc:
        raise SystemExit(f"windows_frame: {exc}")


if __name__ == "__main__":
    main()
