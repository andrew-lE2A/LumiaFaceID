# Explicit CSI-2 selection comparison: iris-csi-03

This is a one-cycle comparison after kernel #7 confirmed the target receiver
configuration but recorded zero iris packets. Normal front/rear previews on
that same boot produced positive packet counts with zero ECC/CRC errors.
Three iris PHY status words changed, but their exact bit meanings remain
unresolved. See the [recorded results](IRIS-CSI.md#phone-results).

The iris mode program writes `0x0111=0`. The original driver's generic
`cam_drv_SMIApp_sensor_config` path explicitly writes `0x0111=2` to select CSI-2
at VA `0x4165f2`–`0x4165fa`. Its complete final ordering relative to the matched
mode program has not been established. That makes explicit selection a
source-backed comparison to test, not a confirmed fix or a reconstruction of
the full original runtime sequence.

Kernel **#8** adds a separate root control, `csi2-once`. It adds exactly one
fixed byte write, `0x0111=2`, after the mode/frame settings and before the saved
configuration snapshot. The snapshot must read back 2 before the receiver or
sensor stream starts. The existing `identify`, `stream-once` and `csi-once`
commands retain their previous scope and settings.

The exact uploaded profile remains hash-pinned and unchanged. Its 117 program
bytes/50 transactions are still counted separately from the extra interface
write. Receiver routing, clock requests, exposure, gain and settle count remain
the same. No IR, test generator or image DMA is added. This test does not return
an image or implement authentication.

## Prepare on the Mac

Use the latest project files from GitHub and open Terminal in that directory.
Keep the original boot backup and already-prepared profile. Run:

```sh
shasum -a256 -c kernel/builds/iris-csi-03/SHA256SUMS &&
python3 tools/validate_iris_dtbs.py kernel/builds/iris-csi-03/boards.dtb &&
python3 tools/repack_boot.py "$HOME/Documents/cityman-current-boot.img" \
  --kernel kernel/builds/iris-csi-03/Image.gz \
  --dtbs kernel/builds/iris-csi-03/boards.dtb \
  --output "$HOME/Documents/cityman-iris-csi-03.img"
```

The output path must be new. The DTBs are unchanged from iris-csi-02. The tool
preserves the original ramdisk, boot settings and partition size.

## Temporarily boot

```sh
adb reboot bootloader &&
fastboot boot "$HOME/Documents/cityman-iris-csi-03.img" &&
adb wait-for-device &&
adb root &&
adb wait-for-device &&
adb shell 'cat /proc/version; cat /sys/module/cityman_iris_id/parameters/probe_status; cat /sys/bus/platform/drivers/cityman-iris-id/*/result'
```

Expected: kernel #8, probe `stage=ready errno=0`, and ordinary result
`status=ready stage=idle` with `attempts=0`. Wait for the normal home screen.
Do not run an ID/stream test first; this requires an untouched diagnostic boot.
The installed boot partition is preserved.

## Run the comparison once

Close camera apps and keep the phone awake. Use the **updated helper** and
`csi2-once` command:

```sh
adb push "$HOME/Documents/cityman-iris-stream-profile.hex" \
  /data/local/tmp/cityman-iris-stream-profile.hex &&
adb shell sh -s -- csi2-once < tools/identify_cityman.sh
adb shell 'dmesg | grep -iE "cityman-iris|msm_csid|msm_csiphy|msm_cci" | tail -n 80'
```

Paste the entire output. `Stream after:` should include
`interface_csi2_requested=1`. If configuration succeeds, the sensor `signal`
row should show before/after `0x0002`, with validity 1. A write/readback failure
aborts before receiver initialization and sensor stream-on. The normal
best-effort sensor stop/reset/power unwind still runs.

The strict sensor-counter criterion can still return `-110`; the receiver
counters and readbacks remain independently useful. Look for changes in packet
counts, ECC/CRC counts, and the saved PHY status words relative to the recorded
kernel #7 test. Positive packet counts alone are not a delivered image. No
change does not identify a unique root cause.

After clean cleanup, the helper restores the previously running camera services.
Report whether both normal cameras still behave as before, then `adb reboot`
to return to the installed kernel. If it prints `REBOOT_REQUIRED`, reboot
before using cameras. Do not repeat this one-shot test on the same boot.

## Validation scope

The same four integration patches and five canonical source files described in
[IRIS-CSI.md](IRIS-CSI.md#integration-and-validation) are used. No new Kconfig
option or DT change is needed; the additional control is gated by the existing
`CONFIG_CITYMAN_IRIS_CSI` and `CAP_SYS_RAWIO` checks. The build manifest records
the exact compiled source hashes.

Host tests compare the complete write trace with the baseline: one extra
interface write, with every other sensor write unchanged. They also cover
write failure, an unlatched selection, the sensor-counter timeout, receiver
sampling before stop, and service restoration. The previous stream and power
regressions remain in the suite. These simulations and compilation do not
establish on-phone reception; the comparison result is pending.

All 99 host tests pass, including 21 receiver lifecycle scenarios and nine
sensor/receiver integration scenarios. The complete ARM64 kernel #8 build
passed. A private repack preserved the original ramdisk, boot settings and
partition size. The uploaded profile and compiled DTBs are unchanged.
