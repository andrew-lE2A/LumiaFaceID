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
