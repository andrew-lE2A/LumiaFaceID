# First phone baseline

The first user-supplied collector report was received on 2026-11-02. It is a
partial metadata capture, not an image acquisition or biometric test. The raw
report remains outside the source tree.

Verified observations from that report:

- ADB state: `device`; every selected property read succeeded.
- Product device: `cityman`.
- Android release/API: `16` / `36`.
- Lineage build: `23.2-20261102-UNOFFICIAL-cityman`.
- Kernel release: `3.10.108-perf-gcc84cab9`. Its abbreviated commit matches the
  pinned kernel source in hardware.md.
- Video4Linux enumeration includes `imx230` and `vs6955`, plus Qualcomm CSIPHY,
  CSID, ISP, actuator and flash subdevices. These names do not demonstrate
  successful image capture and do not identify an iris sensor.
- The build reports board platform `msm8992` and a bullhead Android 8.1 build
  fingerprint, while the product/API identify cityman Android 16. These are
  recorded build-property values, not evidence that this is the wrong phone.

The collector returned `incomplete` because neither live device-tree directory
was visible: `/sys/firmware/devicetree/base` and `/proc/device-tree`. Its discovery
step exited 66 with `No readable live device-tree directory`. That observation
alone does not distinguish missing exports from access restrictions. Source
inspection resolves the expected configuration here: the matching
[`mmo_defconfig`](https://github.com/giannoccarol/android_kernel_mmo_msm8994/blob/cc84cab9900ee4e7a3046b3756858e9832caee72/arch/arm64/configs/mmo_defconfig)
disables `CONFIG_PROC_DEVICETREE`, and its Linux 3.10 OF implementation lacks the
modern sysfs tree export. It does not mean ADB failed or the hardware is defective.

Collector 0.2.0 adds a supported passive fallback: selected
`/sys/bus/platform/devices/*/uevent` files. `drivers/base/core.c` calls
`of_device_uevent()` in `drivers/of/device.c`, which exposes `OF_NAME`,
`OF_FULLNAME` and `OF_COMPATIBLE_n`. CCI populates camera child platform devices
in `drivers/media/platform/msm/camera_v2/sensor/cci/msm_cci.c`. These registered
node identities do not contain arbitrary device-tree properties.

Download the updated collector on the attached host and run:

```sh
python3 collect_cityman.py --output cityman-report-v2.json
```

Preserve missing-path and permission-denied messages. The report retains its
incomplete status when full properties are unavailable and adds the useful
`platform_devices` evidence. Do not change device-tree status to successful
simply to suppress the collector's incomplete result.
The source-pinned camera layout remains available for offline investigation.

## Second phone baseline

The user's collector 0.2.0 report returned `platform_devices.status=ok`, with
exit code 0 and no truncation. It showed bound `qcom,camera` nodes at:

- `/soc/qcom,cci@fda0c000/qcom,camera@0`
- `/soc/qcom,cci@fda0c000/qcom,camera@1`

It also showed camera CCI bound to `msm_cci`, CSIPHY/CSID, ISPIF/VFE,
actuator, Hill flash and camera-flash bindings. The generic name filter also
matched ARM CCI-400 and a devfreq CCI device; those are not camera sensor buses.
No separate iris sensor node appeared in this metadata, consistent with the
pinned source. This observation does not establish the absence or identity of
physical iris hardware, and none of these bindings proves frame delivery.

The missing full device-tree export remains recorded as a limitation. The
registered-node baseline is sufficient for the current offline investigation;
repeating the same collector does not recover the absent sensor program.

## Debugging access confirmed

The user's subsequent command output reported `ro.debuggable=1` and SELinux
`Permissive`. After enabling the ROM's Rooted debugging setting, `adb root`
succeeded and `adb shell id` reported `uid=0(root)`. This confirms debugging
access, not sensor identification or image capture. The old kernel ioctl still
needs the prerequisite described in [kernel/README.md](../kernel/README.md).

## Prerequisite kernel boot result

The owner temporarily booted `prep-01`. `/proc/version` reported
`3.10.108-perf-gcc84cab9 (lumiafaceid@cloud) ... #1 ... Nov 3 00:05:22 UTC 2026`.
The owner confirmed the normal home screen and unchanged rear/front camera
behavior. No iris acquisition or authentication test was performed.


## Iris-ID binding failure and correction

The owner booted build #2 (iris-id-01). Its repacked boot SHA-256 matched the
locally validated image, and /proc/version confirmed the expected build. The
platform driver directory and microsoft,cityman-iris-id device existed,
but the device was unbound and no result file appeared. The supplied filtered
logs did not name a diagnostic probe resource or definitive failure code.

Source/DTB review found the reset pinctrl groups beneath the GPIO child rather
than directly beneath the TLMM pinctrl controller, outside the vendor parser's
group scan. iris-id-02 corrects that structure, validates it against the real
compiled DTB, and exposes the last driver probe stage even without binding.
The owner then temporarily booted build #3 and confirmed:

```text
stage=ready errno=0
status=ready stage=idle errno=0 model=0x0000 cleanup_errno=0 attempts=0 blocked=0 rail_uv=0
```

This established successful dormant binding on iris-id-02. At that point no
identification or power sequence had run, so the model was still unknown.

## Iris sensor model confirmed

The owner then ran `tools/identify_cityman.sh` from repository commit
`9175c862e013831f37e82f37150aab1799454dca`, with build #3 still temporarily booted.
The helper stopped cameraserver, vendor.camera-provider-2-4 and qcamerasvr, and
issued one explicit identify write. The reported result was:

```text
status=identified stage=model-read errno=0 model=0x0861 cleanup_errno=0 attempts=1 blocked=0 rail_uv=1200000
```

All three camera services were restored. The owner subsequently confirmed both
normal rear and front cameras work as before. This verifies the first complete
sensor power/reset/CCI-model-read/unwind cycle through master 0, SID `0x36` and
the two-byte model register zero. The driver did not request illumination or
streaming. `rail_uv` is the final checked rail reading, not a simultaneous
measurement of every supply.

The model matches the original driver's Siiri/`0x0861` condition. Manufacturer
and module revision remain source-derived constants rather than measurements.
Repeated cycles, suspend/resume, capture and authentication remain untested.
See [the first-frame investigation](iris-capture.md) for the remaining work.

## First sensor-stream diagnostic: counter unchanged

The owner booted `iris-stream-01`, kernel #4, and the local repack SHA-256
matched `94a893ab95aa1965af5a68a4313e8763176a4ffd53c9caa4572259bdef41dfbc`.
The exact stream profile was accepted. The helper reported:

```text
status=failed stage=stream-test errno=-110 model=0x0861 cleanup_errno=0 attempts=1 blocked=0 rail_uv=1200000
profile_loaded=1 stage=frame-counter first=0x00 last=0x00 changes=0 samples=16 program_writes=117 stop_errno=0
```

All 16 counter reads succeeded; `-110` was generated by the diagnostic's
unchanged-counter check, not a CCI read timeout. All three services restarted.
Normal camera behavior after this particular test has not yet been reported.
Version 01 did not take mode/configuration readbacks on this timeout path, so
the result does not establish whether mode select latched or packets were sent.

The supplied filtered kernel log shows a CCI release warning before the
diagnostic initializes the controller. The pinned enum defines its state 1 as
disabled, and the guard rejects release with zero references. That earlier
warning does not establish a transfer failure during this test.

The [version 02 test](../kernel/IRIS-STREAM.md) corrects the transfer-shape
discrepancy against the original driver and preserves pre/post-start readbacks.
The register payload, power sequence, timing and IR-control scope are unchanged.

## Second sensor-stream diagnostic: configuration latched, counter unchanged

The owner booted `iris-stream-02`, kernel #5, using repository commit
`cd3717815bd14754fa4b12cfdc1dd4cd49e5bce3`. Its 117 program bytes completed
in 50 transactions. All 20 pre/post-start register pairs were valid, with
`readback_errno=0`. Mode select changed from 0 to 1; reset and group hold read
zero. The timing, geometry, exposure and gain settings read back as programmed.

All 16 counter reads returned zero again. The result was `errno=-110`,
`cleanup_errno=0`, `stop_errno=0`, `attempts=1` and `blocked=0`. The helper
restored all three camera services, and the owner confirmed both ordinary
cameras work as before. This establishes recovery for this particular test.

EXTCLK/control readback semantics remain unresolved: registers `0x0136` and
`0x0138` returned zero. No physical clock measurement, receiver configuration
or image capture was performed. The full selected readbacks are preserved in
[phone-result.json](../kernel/builds/iris-stream-02/phone-result.json).

## First CSI receiver test: setup/release pass, recorded counters zero

The owner temporarily booted iris-csi-01, kernel #6. The repacked boot SHA-256
matched the locally validated image. The diagnostic reported receiver version
`0x30010003`, PHY2 combo / CSID3 configuration, successful setup and release,
and valid before/after packet/ECC/CRC reads, all zero. The sensor again accepted
the program and mode select but its 16 counter reads stayed zero, returning
the diagnostic's `-110`. Sensor stop and overall cleanup returned zero.

All three camera services restarted, and the owner confirmed both normal
cameras work as before. Release warnings in the supplied log precede the
diagnostic's own initialization and refer to already-idle receivers/CCI.
They do not establish a transfer or release failure during this cycle.

Receiver configuration/status was not captured in this build. Source review
also found an original `CORE_CTRL_1` bit-16 setting omitted by the Linux path.
Its effect on observations is untested. The zero counters therefore do not
establish physical absence of packets. The full selected result is saved in
[iris-csi-01/phone-result.json](../kernel/builds/iris-csi-01/phone-result.json).
