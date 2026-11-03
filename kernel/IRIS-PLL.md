# Complete programmed clock readback: iris-csi-04

Kernel #8 measured internal MCLK1 near 9.6 MHz, CSID3 near 240 MHz and PHY2
timer near 200 MHz, yet its sensor counter and receiver packet counts stayed
zero. The original post-start callback is logging only; the conditional
mechanical-shutter delay supplies no established missing iris-start operation.
See [the startup audit](../docs/iris-startup-audit.md).

Kernel #9 adds five two-byte sensor readbacks to the end of the existing
snapshot. All ten added transactions are reads of addresses already written
by the hash-pinned mode program. Sensor reset, EXTCLK write, program bursts,
frame/exposure/gain settings, CSI-2 selection, stream-on/off and cleanup writes
are unchanged. PHY route, clock requests and settle count are unchanged.

| Saved field | Address | Mode-program value expected |
| --- | --- | --- |
| `clk0130` | `0x0130` | `0x099a` |
| `vt_pix` | `0x0300` | `0x0002` |
| `vt_sys` | `0x0302` | `0x000a` |
| `op_pix` | `0x0308` | `0x0008` |
| `op_sys` | `0x030a` | `0x0001` |

The original 20 fields already include pre-divider `0x0304` and multiplier
`0x0306`, expected `0x0001` and `0x0092`. The added fields close the remaining
programmed-clock snapshot gap. Their conventional VT/OP labels are not a PLL
lock indication or a measurement of physical pixel/MIPI clocks. `0x0130` is
kept distinct from EXTCLK `0x0136`; similar numbers do not establish identical
register semantics.

Each word is read in one MSB-first CCI transaction. The first 20 snapshot
indices are preserved, including the CSI-2 latch check at index 7. A new-field
read error follows the existing fail/cleanup rules; failure before start
prevents receiver setup and sensor stream-on. A completed but unchanged frame
counter still saves all available after-start fields before sensor stop.
The strict unchanged-counter timeout remains separate from packet evidence.

The expected values above are also reproduced by
`tools/inspect_iris_dcc.py` as mode 0's `programmed_clock_words`, using the
existing exact-file hash gate. Incomplete byte pairs remain unknown; duplicate
addresses are rejected rather than silently selecting a value.

The expected values above are source-derived, not phone results. Kernel #9
build/boot results and any recovered on-phone readbacks must be recorded
separately. No iris image, illumination or Android authenticator is added.

## Local build and temporary test

This development remains local; no GitHub push or PR is required. The original
boot backup and private profile must be preserved. The local test boot image
must use a new output path and the original ramdisk/settings. Use only
`fastboot boot`, never flash an experimental image.

Before a test, verify the running kernel says #9, ready/idle, attempts=0 and
blocked=0. Close camera apps. Run the existing `csi2-once` helper exactly once
on that fresh temporary boot. Save all 25 sensor and 22 receiver pairs, final
result, cleanup, camera-service restoration and relevant kernel messages.
There is no need to repeat debug-clock measurements for this comparison.
After clean recovery, verify both ordinary cameras and return to the installed
kernel. A cleanup error requires reboot before camera use; do not retry the
one-shot on the same boot.

## Phone result, 2026-11-03

Kernel #9 was built locally on a case-sensitive Linux Docker volume and
booted with `fastboot boot`. Configuration and device trees match kernel #8
byte for byte. The original ramdisk and installed boot partition are unchanged.
See [the manifest](builds/iris-csi-04/manifest.json) and
[the complete phone result](builds/iris-csi-04/phone-result.json).

All 25 sensor pairs and 22 receiver pairs were valid. The added values before
and after start were `0130=099a`, `0300=0002`, `0302=000a`, `0308=0000`,
`030a=0001`. Thus four added words match the program; `0308` reads zero despite
the program containing `0008`. This discrepancy alone does not establish a
fault: the original driver's model-specific 0x0c/0x0861 clock calculation
bypasses the generic OP pixel divider. No divider rewrite is justified from
this observation. The original 20 sensor and all 22 receiver pairs match #8.

Mode select changes from 0 to 1, but all 16 counter reads remain zero. CSID3
packet, ECC and CRC counts remain zero. The one-shot returns `-110` at
`stream-test`; sensor stop, receiver release and overall cleanup return zero.
All three camera services restore. Aperture subsequently delivered frame
metadata from both ordinary cameras, with positive CSID2/CSID0 packet counts
and zero ECC/CRC errors. No iris image or Android authentication is delivered;
IR remains disabled.
