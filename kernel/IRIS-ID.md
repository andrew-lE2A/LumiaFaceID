# Iris-ID diagnostic: binding and one model read

The owner confirmed `prep-01` reached the home screen with rear/front camera
behavior unchanged. `iris-id-02` adds a separate `microsoft,cityman-iris-id`
platform device under CCI. It is not a camera HAL sensor slot or Android
biometric implementation. The first test boots it and **reads status only**.
The owner has now confirmed build #3 binds with `stage=ready errno=0` and
`status=ready stage=idle errno=0 model=0x0000 cleanup_errno=0 attempts=0 blocked=0 rail_uv=0`.
That zero model was the initial value. The owner subsequently ran the helper
once and obtained model `0x0861`, `errno=0`, `cleanup_errno=0`, `attempts=1` and
`blocked=0`. All three services restarted, and the owner confirmed unchanged
normal rear/front camera behavior. This validates one ID cycle, not streaming.

## Prepare and temporarily boot

From the updated project folder on the Mac, with the original uncompressed
backup in Documents:

```sh
shasum -a256 -c kernel/builds/iris-id-02/SHA256SUMS &&
python3 tools/validate_iris_dtbs.py kernel/builds/iris-id-02/boards.dtb &&
python3 tools/repack_boot.py "$HOME/Documents/cityman-current-boot.img" \
  --kernel kernel/builds/iris-id-02/Image.gz \
  --dtbs kernel/builds/iris-id-02/boards.dtb \
  --output "$HOME/Documents/cityman-iris-id-02.img"
```

The explicit DTB update adds the dormant diagnostic and pinctrl resources.
The packer verifies matching board identities, count and order, preserves the
ramdisk and boot settings, and refuses an existing output file. Identity checks
do not validate arbitrary wiring changes; use the reviewed, checksummed DTBs.

```sh
adb reboot bootloader
fastboot boot "$HOME/Documents/cityman-iris-id-02.img"
adb wait-for-device
adb shell 'cat /proc/version; cat /sys/module/cityman_iris_id/parameters/probe_status; cat /sys/bus/platform/drivers/cityman-iris-id/*/result'
```

Expected: `status=ready stage=idle`, `attempts=0`, `blocked=0`. This means the
driver resolved its resources; it has not powered or identified the sensor.
Report missing files or boot failures rather than substituting a flash command.
Temporary boot does not write the installed boot partition; reboot returns to
the installed image.

## Implementation

Source: [driver/cityman_iris_id.c](driver/cityman_iris_id.c). Apply integration
[patch 0002](patches/0002-cityman-iris-id-integration.patch) after patch 0001,
then copy the C file to `drivers/media/platform/msm/camera_v2/sensor/` in the
kernel checkout. `CONFIG_CITYMAN_IRIS_ID` defaults off and is explicitly enabled
in this diagnostic build. Probe, boot and resume never call identification.

The later hardware action requires root, `CAP_SYS_RAWIO` and the exact command
`identify`. It is restricted to `mmo,cityman`. It uses CCI master 0, SID `0x36`
(the original eight-bit `0x6c`) and reads the two-byte model at register zero.
Reset GPIO102, MCLK1/GPIO14 at 9.6 MHz, and L17/LVS1/S3/L3 supplies follow the
original CAMT description. L17/S3/L3 must report the expected fixed board
voltages. The driver changes no voltage values and balances its enable votes;
shared/always-on supplies may remain physically powered afterward.

Reset is held low during startup and asserted during unwind, following the
original driver's XSHUTDOWN low/reset and high/release semantics. There is no
boost supply, GPIO106, flash/torch call, initialization-register write, stream-on
or CSI setup. The driver does not command illumination.

Failures unwind acquired resources. Cleanup errors are reported separately and
block retries; do not repeatedly write after an unsafe cleanup. These are
source-derived parameters, not validated electrical behavior. A NACK does not
prove absence, especially with illumination/boost left untouched. An
`identified` result means model `0x0861` matched, not that manufacturer,
streaming, iris matching or authentication strength were measured.

## One controlled identification attempt

With build #3 still temporarily booted, close camera apps and keep the phone
awake. From the updated checkout, run:

```sh
adb root &&
adb wait-for-device &&
adb shell sh < tools/identify_cityman.sh
```

This is a hardware action: it powers/reset-cycles the sensor candidate and
reads its model register once through the driver's sequence (which retries
the read once on an I/O error). It does not stream or command illumination.
The helper requires an untouched, ready result with `attempts=0`; it never
automatically repeats the identification write.

It stops `cameraserver`, `vendor.camera-provider-2-4`, then `qcamerasvr`, waits
for each stopped state, and rechecks all three before writing. The names are
from [cityman's pinned init file](https://github.com/giannoccarol/android_device_msft_cityman/blob/2b12322a7f01973aa601ffeac4bbe297b3f0676d/rootdir/etc/init.cityman.rc),
[the provider definition](https://github.com/LineageOS/android_hardware_interfaces/blob/13d687a84c834af855bfb314b853b8372a7aa6d9/camera/provider/2.4/default/android.hardware.camera.provider@2.4-service.rc)
and [LineageOS's cameraserver definition](https://github.com/LineageOS/android_frameworks_av/blob/lineage-23.2/camera/cameraserver/cameraserver.rc).
Previously running services are restored in reverse order after clean cleanup,
including after a failed identification. Previously stopped services stay
stopped. Stop failures abort before the write and restore services already
stopped by the helper. Service changes and the sequence are simulated in host
tests. The owner has also completed one successful on-phone helper run.

Paste the complete output, especially the `After:` line. The expected match is:

```text
status=identified stage=model-read errno=0 model=0x0861 cleanup_errno=0 attempts=1 blocked=0 rail_uv=1200000
```

If cleanup is unconfirmed (`cleanup_errno` is nonzero, `blocked=1`, or the
result cannot be read), the helper leaves camera services stopped and prints
`REBOOT_REQUIRED`. Run `adb reboot` to return to the installed kernel before
using cameras. A failed service restoration also requests a reboot. Do not
repeat a failed identification before its status has been reviewed.

The driver additionally
refuses an already-open CCI controller, but the old CCI lifecycle does not
provide session-ownership isolation. Reading `result` does not power hardware;
writing `identify` is a separate power/reset action.

## Validation

The production startup and cleanup functions are compiled on the host against
simulated kernel APIs in `tests/iris_sequence_host.c`; they are not reimplemented
in the test. The 28 scenarios cover success, incorrect ID, startup failures,
partial regulator acquisition, retries, cleanup failures, busy CCI, suspend and
refusal after unsafe cleanup. Simulation is not a physical timing/power test.

The full ARM64 `Image.gz-dtb` build passed. The effective kernel config differs
from the original only by `CONFIG_CITYMAN_IRIS_ID=y`. All 57 host tests passed,
including the 28 production-sequence scenarios. The integration patch applies
cleanly to its pinned base, and the compiled C source matches the canonical
repository file. The generated DTBs preserve board identities/order and the
exact original Talkman DTB. The Cityman diagnostic's supply phandles, GPIO102
and non-default pinctrl states were checked in the resulting DTB. Private
repacking preserved the owner's ramdisk and boot settings and fit the original
partition. The owner confirmed on-phone binding on build #3, then one successful
model read with clean unwind and unchanged normal cameras.
See [the build manifest](builds/iris-id-02/manifest.json) for source and hashes.

The helper adds ten host fixture tests for init service lifecycle and result
handling, including a failed sysfs write after clean unwind. The current suite,
including the later offline calibration inspector, passes all 79 host tests.
These simulations do not exercise the physical sensor or Android init itself.


## Binding correction after iris-id-01

The owner booted kernel build #2 and its platform device appeared, but it did
not bind and no result file was created. The first DTB put reset pinctrl groups
under the GPIO child instead of directly under the TLMM controller. The vendor
parser scans direct controller children only. The corrected tree moves them
to `&tlmm_pinmux`. Host validation rejects the old artifact and checks the actual
compiled tree hierarchy and resource references. The old artifact remains only
as a regression input; use 02.

This structural defect is established from source and the old DTB. The phone
logs did not establish it as the only deferred resource. The corrected build
also adds stage-specific probe messages and a read-only fallback parameter at
`/sys/module/cityman_iris_id/parameters/probe_status`. It should say
`stage=ready errno=0`; otherwise it reports the last resource and error.
`not-probed` means the driver callback was not entered. This output cannot be
assigned from the boot command line or written through sysfs. The owner has
confirmed ready binding and one successful sensor power/ID cycle on the corrected
build. The [capture investigation](../docs/iris-capture.md) records the next work.
