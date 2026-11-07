#!/usr/bin/env python3
"""Summarize packed MIPI RAW10 without discarding its two low bits.

This is a capture diagnostic, not a Windows iris-input conversion. It reports
raw code distribution, low-bit usage, row/column variation and coarse spatial
means. It does not subtract a black level, rotate pixels, or infer scene
content.
"""

import argparse
import json
import math
from pathlib import Path


def percentile(histogram, count, percent):
    target = max(1, math.ceil(count * percent / 100))
    cumulative = 0
    for value, frequency in enumerate(histogram):
        cumulative += frequency
        if cumulative >= target:
            return value
    return len(histogram) - 1


def distribution(histogram, count, total):
    return {
        "count": count,
        "mean": round(total / count, 3) if count else None,
        "p0": percentile(histogram, count, 0) if count else None,
        "p1": percentile(histogram, count, 1) if count else None,
        "p5": percentile(histogram, count, 5) if count else None,
        "p50": percentile(histogram, count, 50) if count else None,
        "p90": percentile(histogram, count, 90) if count else None,
        "p95": percentile(histogram, count, 95) if count else None,
        "p99": percentile(histogram, count, 99) if count else None,
        "p100": percentile(histogram, count, 100) if count else None,
        "uniqueCodes": sum(1 for frequency in histogram if frequency),
    }


def analyze(data, width, height, stride, crop_left, grid_rows, grid_columns):
    packed_row_bytes = ((width + 3) // 4) * 5
    required = stride * (height - 1) + packed_row_bytes
    if stride < packed_row_bytes:
        raise ValueError(f"stride {stride} is shorter than packed row {packed_row_bytes}")
    if len(data) < required:
        raise ValueError(f"input has {len(data)} bytes; dimensions require {required}")
    if not 0 <= crop_left < width:
        raise ValueError("crop-left must leave at least one column")

    full_hist = [0] * 1024
    crop_hist = [0] * 1024
    low_bits = [0] * 4
    full_total = crop_total = 0
    crop_width = width - crop_left
    row_means = []
    column_sums = [0] * crop_width
    grid_sums = [[0] * grid_columns for _ in range(grid_rows)]
    grid_counts = [[0] * grid_columns for _ in range(grid_rows)]

    for y in range(height):
        row_start = y * stride
        packed = data[row_start:row_start + packed_row_bytes]
        row_total = 0
        crop_row_total = 0
        x = 0
        for offset in range(0, packed_row_bytes, 5):
            group = packed[offset:offset + 5]
            for i in range(min(4, width - x)):
                low = (group[4] >> (2 * i)) & 0x03
                code = (group[i] << 2) | low
                low_bits[low] += 1
                full_hist[code] += 1
                full_total += code
                row_total += code
                if x >= crop_left:
                    cx = x - crop_left
                    crop_hist[code] += 1
                    crop_total += code
                    crop_row_total += code
                    column_sums[cx] += code
                    gy = min(grid_rows - 1, y * grid_rows // height)
                    gx = min(grid_columns - 1, cx * grid_columns // crop_width)
                    grid_sums[gy][gx] += code
                    grid_counts[gy][gx] += 1
                x += 1
        row_means.append(row_total / width)

    crop_count = height * crop_width
    row_mean = full_total / (height * width)
    column_means = [value / height for value in column_sums]

    def population_std(values, mean):
        return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))

    return {
        "dimensions": {"width": width, "height": height, "rowStrideBytes": stride,
                       "packedRowBytes": packed_row_bytes, "cropLeft": crop_left},
        "interpretation": {
            "packing": "MIPI RAW10: four high bytes plus one byte containing four 2-bit low fields",
            "blackLevelSubtracted": False,
            "pixelRotationApplied": False,
            "sceneContentInferred": False,
        },
        "fullFrame10Bit": distribution(full_hist, width * height, full_total),
        "leftCropped10Bit": distribution(crop_hist, crop_count, crop_total),
        "lowTwoBitFieldHistogram": low_bits,
        "spatialVariation": {
            "fullRowMeanMin": round(min(row_means), 3),
            "fullRowMeanMax": round(max(row_means), 3),
            "fullRowMeanStd": round(population_std(row_means, row_mean), 3),
            "croppedColumnMeanMin": round(min(column_means), 3),
            "croppedColumnMeanMax": round(max(column_means), 3),
            "croppedColumnMeanStd": round(population_std(column_means, crop_total / crop_count), 3),
            "croppedGridMeans": [
                [round(grid_sums[gy][gx] / grid_counts[gy][gx], 3)
                 for gx in range(grid_columns)]
                for gy in range(grid_rows)
            ],
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--stride", type=int, required=True, help="bytes per source row")
    parser.add_argument("--crop-left", type=int, default=300)
    parser.add_argument("--grid", nargs=2, type=int, metavar=("ROWS", "COLUMNS"), default=(4, 6))
    parser.add_argument("--output", type=Path, help="write JSON to this path instead of stdout")
    args = parser.parse_args()
    if min(args.width, args.height, args.stride, *args.grid) <= 0:
        parser.error("dimensions, stride, and grid sizes must be positive")
    try:
        result = analyze(args.input.read_bytes(), args.width, args.height,
                         args.stride, args.crop_left, *args.grid)
        encoded = json.dumps(result, indent=2) + "\n"
        if args.output:
            args.output.write_text(encoded, encoding="utf-8")
        else:
            print(encoded, end="")
    except (OSError, ValueError) as exc:
        raise SystemExit(f"raw10_diagnostics: {exc}")


if __name__ == "__main__":
    main()
