# Bounded CSI packet test: iris-csi-02

This test adds PHY2 combo reception through CSID3 around the existing sensor
program/start/stop cycle. It records receiver packet, ECC and CRC counters.
It does not configure ISPIF/VFE or image DMA, return an image, enable IR, or
implement authentication. Boot/probe remain idle; only `csi-once` requests the
receiver. Ordinary `identify` and `stream-once` retain their previous scope.

## Version 01 result and version 02 changes

The owner booted version 01, kernel #6. PHY2/CSID3 setup and release returned
zero, receiver version was `0x30010003`, and all reported packet/ECC/CRC counters
remained zero. The sensor counter stayed zero. Sensor stop and overall cleanup
returned zero, all services restarted, and both normal cameras still worked.
The [sanitized evidence](builds/iris-csi-01/phone-result.json) preserves the result.
Zero counters alone do not prove physical absence of packets.

The original driver constructs `CORE_CTRL_1` with bit 16 set; the Linux setup
used by version 01 omitted it. Version 02 matches that original flag with a
read/modify/write in the owning CSID driver and refuses to start the sensor if
the flag does not read back. Its exact statistics semantics remain unverified;
this is a source-backed comparison, not a proven root cause. The sensor program,
exposure, clock requests, lane route and settle count remain the same.

Version 02 saves five CSID and 17 PHY configuration/status registers before
start and after the sensor test, before its stop writes. A sensor timeout
still preserves the snapshots. Reading the saved sysfs files afterward does
not access powered hardware. ECC counts use the low 16 bits, matching the
original driver's statistics reader.

The routing is recovered from the original driver's hardware preparation and
one-lane combo path; see [the source trace](../docs/iris-csi.md). Hardware
reception on this route has not yet been measured. The initial PHY settle
count is 20 at a requested 200 MHz timer clock. That is a bring-up setting,
not a measured timing window. Receiver routing, packet validity and eventual
frame delivery remain separate hardware checks.

## Prepare on the Mac

Open Terminal in the updated project directory from GitHub.
Keep the existing original boot backup and prepared profile. Run:

```sh
shasum -a256 -c kernel/builds/iris-csi-02/SHA256SUMS &&
python3 tools/validate_iris_dtbs.py kernel/builds/iris-csi-02/boards.dtb &&
python3 tools/repack_boot.py "$HOME/Documents/cityman-current-boot.img" \
  --kernel kernel/builds/iris-csi-02/Image.gz \
  --dtbs kernel/builds/iris-csi-02/boards.dtb \
  --output "$HOME/Documents/cityman-iris-csi-02.img"
```

The output path must be new. The tool preserves the original ramdisk, boot
settings and partition size. The DTBs match iris-csi-01 and iris-stream-02.
No Windows binary or calibration table is embedded in the new kernel. Reuse
`~/Documents/cityman-iris-stream-profile.hex`; its hash and contents are unchanged.

## Temporarily boot

```sh
adb reboot bootloader &&
fastboot boot "$HOME/Documents/cityman-iris-csi-02.img" &&
adb wait-for-device &&
adb root &&
adb wait-for-device &&
adb shell 'cat /proc/version; cat /sys/module/cityman_iris_id/parameters/probe_status; cat /sys/bus/platform/drivers/cityman-iris-id/*/result; cat /sys/bus/platform/drivers/cityman-iris-id/*/csi_result'
```

Expected: kernel **#7**, probe `stage=ready errno=0`, ordinary result
`status=ready stage=idle` with `attempts=0`, and CSI result beginning
`requested=0 stage=idle errno=0 cleanup_errno=0`. Do not run the old ID or
stream helper first: the test requires an untouched diagnostic boot.
Stop if Android does not reach its normal home screen or these checks differ.
This RAM boot does not flash the installed boot partition.

## Run once

Close camera apps and keep the phone awake:

```sh
adb push "$HOME/Documents/cityman-iris-stream-profile.hex" \
  /data/local/tmp/cityman-iris-stream-profile.hex &&
adb shell sh -s -- csi-once < tools/identify_cityman.sh
adb shell 'dmesg | grep -iE "cityman-iris|msm_csid|msm_csiphy|msm_cci" | tail -n 80'
```

Paste the full helper output and filtered log. The helper stops the same three
camera services before the test, then prints sensor status, saved register
readbacks and a new `CSI after:` line. The latter includes:

```text
requested=1 stage=released errno=0 cleanup_errno=0 phy=2 csid=3 combo=1 lane_mask=0x18 lane_assign=0x0004 settle=20 before_valid=1 after_valid=1 packets_before=... packets_after=... ecc_before=... ecc_after=... crc_before=... crc_after=... version=...
```

The helper then prints `Saved receiver configuration/status`. Expected
configuration values, with validity 1, include:

| Row | Expected before/after value |
| --- | --- |
| `csid_control0` | `0x00000040` |
| `csid_control1` | `0x0005000f`, including original bit 16 and PHY selector 2 |
| `csid_vc0_lut` | Low byte `0x2b` |
| `csid_cid0_config` | `0x00000023` |
| `phy_clock_mux` | Upper nibble `0x3`; other bits preserved |
| `phy_power` / `phy_mode` | `0x31` / `0x10` |
| Clock/data `cfg2` | `0x10` |
| Clock/data `settle` | `0x14` at the requested 200 MHz timer rate |
| Clock/data `misc` | `0x4` / `0x8` |

Eight PHY IRQ status words and the CSID IRQ status are saved as raw diagnostics.
No extra IRQs are enabled and the sampling code does not clear those words.
Their bit meanings are not decoded into a link verdict. These are snapshots
before cleanup; the original PHY mux is restored afterward.

Compare valid before/after counters. Packet increases show traffic reached
CSID3 during this interval; ECC/CRC changes identify receiver errors. Counts
alone do not establish a valid RAW10 image. Zero packets do not uniquely
identify a sensor, timing or link failure.

The sensor counter may remain zero and the write may still report
`Connection timed out` / `errno=-110`. That strict sensor criterion is retained
from iris-stream-02. Receiver observations are saved independently even on that
path; inspect `CSI after:` instead of interpreting the timeout as a CCI or
receiver transfer error. Its `errno` describes receiver setup, while its
`cleanup_errno` describes receiver teardown. The ordinary result separately
reports the sensor operation and overall cleanup.

After clean cleanup, the helper restores the previously running camera
services. Report whether both normal cameras still work as before, then run
`adb reboot` to return to the installed kernel. A stop/cleanup error, dirty
legacy-init state, or unreadable final status leaves services stopped and
prints `REBOOT_REQUIRED`; reboot before using cameras. Do not repeat this
one-shot test on the same boot.

## Integration and validation

Apply patches 0001–0004 in order to kernel commit
`cc84cab9900ee4e7a3046b3756858e9832caee72`. Copy canonical files:

| Repository file under `kernel/driver/` | Kernel location under `drivers/media/platform/msm/camera_v2/sensor/` |
| --- | --- |
| `cityman_iris_id.c` | `cityman_iris_id.c` |
| `cityman_iris_stream.h` | `cityman_iris_stream.h` |
| `cityman_iris_csi.h` | `cityman_iris_csi.h` |
| `cityman_iris_csid.h` | `csid/cityman_iris_csid.h` |
| `cityman_iris_csiphy.h` | `csiphy/cityman_iris_csiphy.h` |

Enable `CONFIG_CITYMAN_IRIS_ID`, `CONFIG_CITYMAN_IRIS_STREAM` and
`CONFIG_CITYMAN_IRIS_CSI`. All are built-in; CSI defaults off and depends on
the stream option plus the built-in camera stack. No new HAL camera slot or
DT route is added.

The receiver owner helpers acquire PHY2 and CSID3 mutexes with try-locks,
refuse active state/references/lane masks or an incompatible board lane
override, and retain both locks until shutdown. They initialize/configure
through the existing drivers. Setup follows sensor programming and precedes
mode select. Version 02 samples counters and receiver state before the sensor
stop attempt and preserves that snapshot through release. The original PHY mux
is restored while its registers remain accessible. All acquired resources are
released on setup failure as well.

Diagnostic CSID reset waits are limited to 500 ms each. Normal camera sessions
retain their original wait behavior. Clock/regulator release errors are
retained for the diagnostic while every remaining teardown step is attempted.
Detected partial legacy init state is reported as unconfirmed cleanup and
blocks further sensor activity; it is not silently retried.

Host tests execute the production sensor/power code and receiver owner helpers
with simulated kernel APIs. They cover busy/wrong receivers, lifecycle errors,
dirty initialization, mux restoration, counter snapshots, sensor/receiver
ordering and service restoration. They do not emulate the analogue PHY or
prove physical reception. The build manifest records compilation and artifact
validation. All 98 host tests pass, including 21 receiver lifecycle scenarios,
five sensor/receiver ordering scenarios and the earlier 116 stream/28 power
scenarios. The complete ARM64 kernel #7 build passed. A private local repack
preserved the original ramdisk and boot settings and fit the original partition.
The phone boot and receiver result remain pending until the owner runs this test.
