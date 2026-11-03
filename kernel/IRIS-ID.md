# Iris-ID diagnostic: idle binding test

The owner confirmed `prep-01` reached the home screen with rear/front camera
behavior unchanged. `iris-id-01` adds a separate `microsoft,cityman-iris-id`
platform device under CCI. It is not a camera HAL sensor slot or Android
biometric implementation. The first test boots it and **reads status only**.

## Prepare and temporarily boot

From the updated project folder on the Mac, with the original uncompressed
backup in Documents:

```sh
shasum -a256 -c kernel/builds/iris-id-01/SHA256SUMS &&
python3 tools/repack_boot.py "$HOME/Documents/cityman-current-boot.img" \
  --kernel kernel/builds/iris-id-01/Image.gz \
  --dtbs kernel/builds/iris-id-01/boards.dtb \
  --output "$HOME/Documents/cityman-iris-id-01.img"
```

The explicit DTB update adds the dormant diagnostic and pinctrl resources.
The packer verifies matching board identities, count and order, preserves the
ramdisk and boot settings, and refuses an existing output file. Identity checks
do not validate arbitrary wiring changes; use the reviewed, checksummed DTBs.

```sh
adb reboot bootloader
fastboot boot "$HOME/Documents/cityman-iris-id-01.img"
adb wait-for-device
adb shell 'cat /sys/bus/platform/drivers/cityman-iris-id/*/result'
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

## Before any later identification attempt

Stop camera services and quiesce camera use first. The driver additionally
refuses an already-open CCI controller, but the old CCI lifecycle does not
provide session-ownership isolation. Reading `result` does not power hardware;
writing `identify` is a separate power/reset action. The test above only reads.

## Validation

The production startup and cleanup functions are compiled on the host against
simulated kernel APIs in `tests/iris_sequence_host.c`; they are not reimplemented
in the test. The 28 scenarios cover success, incorrect ID, startup failures,
partial regulator acquisition, retries, cleanup failures, busy CCI, suspend and
refusal after unsafe cleanup. Simulation is not a physical timing/power test.

The full ARM64 `Image.gz-dtb` build passed. The effective kernel config differs
from the original only by `CONFIG_CITYMAN_IRIS_ID=y`. All 54 host tests passed,
including the 28 production-sequence scenarios. The integration patch applies
cleanly to its pinned base, and the compiled C source matches the canonical
repository file. The generated DTBs preserve board identities/order and the
exact original Talkman DTB. The Cityman diagnostic's supply phandles, GPIO102
and non-default pinctrl states were checked in the resulting DTB. Private
repacking preserved the owner's ramdisk and boot settings and fit the original
partition. On-phone diagnostic binding and identification have not been tested.
See [the build manifest](builds/iris-id-01/manifest.json) for source and hashes.
