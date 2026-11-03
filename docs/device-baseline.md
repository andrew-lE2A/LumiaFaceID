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
This does not establish whether another resource will still defer; the retry
is a status-only check, with identification not yet invoked.
