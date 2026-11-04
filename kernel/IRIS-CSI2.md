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

## Phone result

The owner completed this comparison on kernel #8. `0x0111` read back 2 both
before and after stream-on. All other sensor readback pairs and all 22 receiver
pairs matched kernel #7. CSID3 again recorded zero packets/ECC/CRC; the sensor
counter remained zero, giving the diagnostic's `-110`. PHY status words 3/4
changed to `0x4` and word 6 to `0x10`, just as before. Their meanings remain
unresolved. Selecting CSI-2 alone did not resolve reception in this setup.

Sensor stop, receiver release and overall cleanup returned zero. All three
camera services restarted, and the owner confirmed both normal cameras still
work as before. The selected values are saved in
[phone-result.json](builds/iris-csi-03/phone-result.json).

### Follow-up comparison on kernel #13

The later [CAMSS TOP observer build](builds/iris-csi-top-02/manifest.json)
repeated both `csi-once` and `csi2-once` with active-only mux snapshots. The
explicit CSI-2 run again read `0x0111=2` before and after stream-on, but the
frame counter and CSID packet count remained zero. At the same time the
Windows-noted CAMSS TOP fields were present: `0xfda00040=0x30` while PHY2 was
powered and `0xfda00044=0x03` before and during the run. Thus neither the
missing interface selection nor the missing TOP select bit explains the
current no-packet result. The detailed
[csi2-once record](builds/iris-csi-top-02/csi2-phone-result.json) includes the
PHY status words, which still need a hardware-version-specific decode.

The next [MCLK observation](IRIS-MCLK.md) reuses this kernel and profile with
an updated helper. The reproduction instructions below document the completed
interface comparison; another identical run without added observation would
not answer the unresolved clock question.

## Runtime settle comparison: iris-csi-trials-01

Kernel #19 adds a temporary-boot-only `csi_trial` control. It accepts only
settle values 20, 22, and 24, fixes CSI-2 and VC0, requires a loaded private
stream profile, and allows at most three attempts after clean teardown. It
does not expose arbitrary register writes. This allowed all three settle
points to be tested in one fastboot boot.

All three requested values read back in both the CSIPHY configuration and
captured receiver registers. Each attempt identified model `0x0861`, completed
117 profile writes, and sampled the sensor frame counter 16 times. The counter
stayed at `0x00`; CSID packet, ECC, and CRC counts stayed at zero. Sensor stop,
PHY/CSID release, and overall cleanup returned zero on every attempt. The
same raw PHY IRQ bits (`status3=0x4`, `status4=0x4`, `status6=0x10`) appeared
at all three values. Their meaning remains undecoded, so this comparison does
not establish that MIPI HS signaling reached the receiver.

Kernel #21 extended the sweep to the accepted edge values 1 and 63. Both trials
still returned zero packets and zero sensor-counter changes. At both edges
`status4` became `0x14`, while status3 stayed `0x4` and status6 stayed `0x10`.
The receiver registers read back the requested settle value. This shows a
repeatable change in a raw PHY status word at the extremes, but it does not
identify the bit or establish valid MIPI reception. Full outputs are preserved
in [the edge trial evidence](builds/iris-csi-settle-edges-01/phone-result.json).

Kernel #19 was loaded with `fastboot boot`; no partition was flashed. The
phone was rebooted to installed kernel #29 afterward, with all three camera
services running. Detailed results are in
[phone-result.json](builds/iris-csi-trials-01/phone-result.json), and build
hashes and boot validation are in
[manifest.json](builds/iris-csi-trials-01/manifest.json). The original boot
backup and private profile were preserved. Publication remains local only.

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
establish on-phone reception. The phone comparison above did not establish
reception either.

All 99 host tests pass, including 21 receiver lifecycle scenarios and nine
sensor/receiver integration scenarios. The complete ARM64 kernel #8 build
passed. A private repack preserved the original ramdisk, boot settings and
partition size. The uploaded profile and compiled DTBs are unchanged.

### Follow-up: Windows-derived PHY settle on kernel #17

The matched mode calculation yields a 350.4 MHz DDR clock (70.08 MHz pixel
rate, RAW10, one lane). With the measured/requested 200 MHz PHY timer, the
Windows settle equation gives 22 ticks. Kernel #17 applied this as `0x16`;
the PHY clock and data settle registers both read back `0x16`. The sensor
counter remained unchanged and CSID3 packet/ECC/CRC counts stayed zero, with
clean teardown and camera service restoration. See the [saved result](builds/iris-csi-settle-01/phone-result.json).
This closes only the settle-count comparison; startup and physical link
activity remain unresolved.

Kernel #18 added the sensor VC field write that Windows performs dynamically.
The register already read `0x00` after reset and mode setup; the explicit VC0
write and both snapshots confirmed `0x00`. With CSID3 configured for CID0,
this closes the VC mismatch lead for the tested configuration. The sensor
counter and CSID3 packet/ECC/CRC counts still remained zero, with clean cleanup
and restored services. See the [VC test result](builds/iris-csi-vc-01/phone-result.json).
