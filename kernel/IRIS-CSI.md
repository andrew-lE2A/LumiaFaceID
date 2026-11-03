# Bounded CSI packet test: iris-csi-01

This test adds PHY2 combo reception through CSID3 around the existing sensor
program/start/stop cycle. It records receiver packet, ECC and CRC counters.
It does not configure ISPIF/VFE or image DMA, return an image, enable IR, or
implement authentication. Boot/probe remain idle; only `csi-once` requests the
receiver. Ordinary `identify` and `stream-once` retain their previous scope.

The routing is recovered from the original driver's hardware preparation and
one-lane combo path; see [the source trace](../docs/iris-csi.md). Hardware
reception on this route has not yet been measured. The initial PHY settle
count is 20 at a requested 200 MHz timer clock. That is a bring-up setting,
not a measured timing window. Receiver routing, packet validity and eventual
frame delivery remain separate hardware checks.

## Prepare on the Mac

Download the new repository ZIP and open Terminal in that extracted folder.
Keep the existing original boot backup and prepared profile. Run:

```sh
shasum -a256 -c kernel/builds/iris-csi-01/SHA256SUMS &&
python3 tools/validate_iris_dtbs.py kernel/builds/iris-csi-01/boards.dtb &&
python3 tools/repack_boot.py "$HOME/Documents/cityman-current-boot.img" \
  --kernel kernel/builds/iris-csi-01/Image.gz \
  --dtbs kernel/builds/iris-csi-01/boards.dtb \
  --output "$HOME/Documents/cityman-iris-csi-01.img"
```

The output path must be new. The tool preserves the original ramdisk, boot
settings and partition size. The DTBs are byte-identical to iris-stream-02.
No Windows binary or calibration table is embedded in the new kernel. Reuse
`~/Documents/cityman-iris-stream-profile.hex`; its hash and contents are unchanged.

## Temporarily boot

```sh
adb reboot bootloader &&
fastboot boot "$HOME/Documents/cityman-iris-csi-01.img" &&
adb wait-for-device &&
adb root &&
adb wait-for-device &&
adb shell 'cat /proc/version; cat /sys/module/cityman_iris_id/parameters/probe_status; cat /sys/bus/platform/drivers/cityman-iris-id/*/result; cat /sys/bus/platform/drivers/cityman-iris-id/*/csi_result'
```

Expected: kernel **#6**, probe `stage=ready errno=0`, ordinary result
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

Compare valid before/after counters. Packet increases show traffic reached
CSID3 during this interval; ECC/CRC changes identify receiver errors. Counts
alone do not establish a valid RAW10 image. Zero packets do not uniquely
identify a sensor, timing or link failure.

The sensor counter may remain zero and the write may still report
`Connection timed out` / `errno=-110`. That strict sensor criterion is retained
from version 02. Receiver observations are saved independently even on that
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
mode select. Counters are saved after the sensor stop attempt, before receiver
release. The original PHY mux value is restored while its registers remain
accessible. All acquired resources are released on setup failure as well.

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
validation. All 98 host tests pass, including 20 receiver lifecycle scenarios,
five sensor/receiver ordering scenarios and the earlier 116 stream/28 power
scenarios. The complete ARM64 kernel #6 build passed. A private local repack
preserved the original ramdisk and boot settings and fit the original partition.
The phone boot and receiver result remain pending until the owner runs this test.
