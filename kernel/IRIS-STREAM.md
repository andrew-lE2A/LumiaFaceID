# Sensor stream diagnostic: iris-stream-01

This build implements the next hardware step after the confirmed `0x0861` ID
read: a brief sensor program/start/counter/stop cycle. It does **not** return an
image, configure a CSI receiver or implement Android authentication. A changing
sensor counter is evidence about the sensor engine only. Actual image delivery
still requires the CSI/ISP path.

Boot and probe remain idle. The original diagnostic is still available, but
the stream test requires an untouched boot with `attempts=0`. Do not run the ID
helper first on this build.

## Prepare on the Mac

Use the new repository ZIP. From its extracted project directory:

```sh
shasum -a256 -c kernel/builds/iris-stream-01/SHA256SUMS &&
python3 tools/validate_iris_dtbs.py kernel/builds/iris-stream-01/boards.dtb &&
python3 tools/repack_boot.py "$HOME/Documents/cityman-current-boot.img" \
  --kernel kernel/builds/iris-stream-01/Image.gz \
  --dtbs kernel/builds/iris-stream-01/boards.dtb \
  --output "$HOME/Documents/cityman-iris-stream-01.img" &&
python3 tools/prepare_iris_stream.py --download \
  --output "$HOME/Documents/cityman-iris-stream-profile.hex"
```

The last command downloads the exact public `0C086101.dcc`, verifies its full
SHA-256, and extracts only idle and mode-0 records. It excludes read overrides,
software configuration, opaque tuning and zero terminators. The resulting
703-byte text file stays local and must not be committed. Both output tools
refuse to overwrite existing files. Alternatively, give the preparation tool a
local original DCC path instead of `--download`.

The public kernel contains no calibration register table. It independently
checks the uploaded 351-byte program against SHA-256
`75478697398abf8b21796d408844249af54e05ae7a399afffc33d51dd83e8eb5`.
This control cannot be used to upload an arbitrary sensor program.

## Temporarily boot and check idle status

```sh
adb reboot bootloader &&
fastboot boot "$HOME/Documents/cityman-iris-stream-01.img" &&
adb wait-for-device &&
adb root &&
adb wait-for-device &&
adb shell 'cat /proc/version; cat /sys/module/cityman_iris_id/parameters/probe_status; cat /sys/bus/platform/drivers/cityman-iris-id/*/result; cat /sys/bus/platform/drivers/cityman-iris-id/*/stream_result'
```

Expected: kernel build #4, probe `stage=ready errno=0`, result `status=ready
stage=idle` with `attempts=0`, and stream status `profile_loaded=0 stage=idle`.
Stop here if the phone does not reach its normal home screen or these files are
missing. The installed boot partition is not changed; `adb reboot` returns to
the installed kernel.

## Run one brief sensor-stream test

Close camera apps and keep the phone awake. Run:

```sh
adb push "$HOME/Documents/cityman-iris-stream-profile.hex" \
  /data/local/tmp/cityman-iris-stream-profile.hex &&
adb shell sh -s -- stream-once < tools/identify_cityman.sh
```

The helper loads the profile into driver memory, stops cameraserver, the camera
provider and qcamerasvr, and rechecks their stopped states before one explicit
`stream-once` write. The driver rechecks the model after the known power
sequence, programs the sensor, polls its frame counter 16 times at 20 ms
intervals, and attempts every stop write before asserting reset and unwinding
its clock/regulator votes. It never requests boost, GPIO106, flash or IR pulses.
The polling delays total 320 ms nominally; CCI timeouts can extend the overall
test and shutdown. This is a fixed-count test, not a hard sub-second deadline.

Paste the full helper output. A successful sensor test should include:

```text
After: status=sensor-streamed stage=stream-test errno=0 model=0x0861 cleanup_errno=0 attempts=1 blocked=0 ...
Stream after: profile_loaded=1 stage=mode-readback first=... last=... changes=... samples=16 program_writes=117 stop_errno=0
```

`changes` must be positive. It counts observed changes, not the number of
delivered frames. `0xff` is the original driver's standby sentinel and is
excluded. The sensor's mode-select register is also checked after polling.

Normal camera services are restored after clean cleanup, including after a
failed sensor test. Any stop/unwind error or an unreadable final status leaves
them stopped and prints `REBOOT_REQUIRED`; run `adb reboot` before using cameras.
Do not repeat a failed test before its output is reviewed. After a clean result,
check whether both ordinary cameras still behave as before and report any
change, then `adb reboot` to finish the temporary boot test.

## Source-derived test settings

Reset and EXTCLK follow the original Siiri startup branch at
`0x40bf70`–`0x40bfd6`: software reset `0x0103=1`, then the rounded 8.8 MHz clock
value at `0x0136`. The test waits 20 ms after reset; the original waits 10 ms.

The mode remains the original 1920×1088 RAW10, one-lane program. The original
driver has an explicit Siiri clock branch at `0x4123d6`–`0x41241e` and
`0x4124a6`–`0x41251e`. With 9.6 MHz MCLK, multiplier 146, pre-divider code 1 and
VT/OP system divisors 10/1, it gives VT and output pixel rates of 70.08 MHz.
The generic SMIA output-clock calculation does not apply to this model.

The DCC override describes minimum line/frame lengths 2100/1116 and minimum
analog gain code 56. The test uses those lengths (nominal 29.9027 fps), gain
code 56 and 12 coarse exposure lines (about 360 µs). These are source-derived
starting settings, not measured timing or optical limits. No gain model or
automatic exposure implementation is claimed.

Start follows the original unpause path: mode select `0x0100=1`, then
`0x0138=1`. Stop attempts group-hold release, `0x0138=0`, fast-standby disable
`0x0106=0`, and mode select `0x0100=0`; reset is asserted afterward on every
path. A stop error blocks further operation even when other cleanup succeeds.

The implementation is gated by `CONFIG_CITYMAN_IRIS_STREAM`, default off and
dependent on the ID driver plus SHA-256 support. Apply patch 0003 after 0001/0002
and copy both canonical driver files into the kernel sensor directory. The
device trees are unchanged from iris-id-02; no PHY or CSID route is introduced.

The production stream and power functions pass 160 integrated simulated stream
scenarios plus the existing 28 power scenarios, covering every startup/program
write failure, read failures, counter stalls, stop failures and blocked retries.
The helper's service restoration and profile preparation are also tested. All
90 host tests pass. The on-phone stream test has not yet been run.
