# Iris image delivery path on Android

## Current verified boundary

Kernel #15 receives CSID3 packets from the iris when PHY2 combo-lane MISC1 is
set to the Windows values: lane 3 `0x06`, lane 4 `0x0A`. The same variant
repeated with 12,677 and 12,720 packets, zero ECC/CRC, and clean receiver
release. See [the phone result](builds/iris-csi-combo-misc-01/phone-result.json).

The result is a receiver/link milestone, not an image. The sensor counter still
reads `0x00` in all 16 samples. The iris diagnostic directly owns CCI, CSID3,
and PHY2, but it does not configure ISPIF/VFE output or provide Android image
buffers. It also is not one of the registered Android camera devices.

The diagnostic's CCI client is on master 0 at 7-bit SID `0x36` (the driver
stores the 8-bit wire address `0x6c` shifted right once). The saved mode
readback is 1920 x 1088, with format register `0x0a0a`; the current CSID setup
accepts VC0 / CSI data type `0x2b` (RAW10). These are concrete starting values
for a sensor descriptor, not proof Android has received a frame. The CSID
statistics counter proves packet activity only; this path has no DMA buffer or
frame callback.

## Existing Android camera route

The pinned cityman camera DTS has two camera slots: rear `qcom,camera@0` routes
to CSID0; front `qcom,camera@1` routes to CSID2. Android CameraService
enumerates two devices (IDs 0 and 1). The front preview test opened ID 1; its
screen capture was black, so visible image quality was not confirmed.

The phone has 32-bit legacy Qualcomm camera sensor plugins for its supported
visible cameras (`libmmcamera_vs6955.so`, `libmmcamera_imx230.so`,
`libmmcamera_imx179_*`, and `libmmcamera_imx377.so`). They export the common
`sensor_open_lib` entry point. No iris sensor plugin is installed.

The pinned kernel's `msm_sensor` path obtains its mode, CSI, power, and sensor
metadata through the legacy userspace sensor-library probe. The sensor library
returns a `sensor_lib_ptr` descriptor; `msm_sensor_init` then issues
`CFG_SINIT_PROBE`. The required `sensor_lib.h` is not in the pinned kernel tree
or this repository, although the related kernel ABI definitions are present in
`include/media/msm_camsensor_sdk.h`. Qualcomm's MSM8994 bring-up guide describes
the userspace `sensor_lib`/`sensor_open_lib` pieces and the matching camera-slot
device-tree entry: [Multimedia Driver Development and Bringup Guide – Camera](https://usermanual.wiki/Document/00bringUp80nu3232hmultimediadriverdevelopmentandbringupguidecamera.1677897646.pdf).

The kernel SDK enum includes `CAMERA_2` (and `MAX_CAMERAS` is 4), so the
kernel side has a camera-ID slot available. This does not establish that this
Android vendor HAL will enumerate a third device; that must be checked after a
matching sensor library and DT node are available. The two existing camera
slots must remain unchanged during that bring-up.

## Next engineering step

Do not spend another test boot on PHY or regulator variants: the MISC1
correction already produces repeatable, clean CSID3 packets. The next
implementation task is to obtain the exact legacy MSM8994 `sensor_lib.h` ABI
used by this vendor HAL, then write a descriptor-only sensor plugin and add an
opt-in third camera slot (`camera@2`, CSID3/PHY2, MCLK1, iris rails and reset
GPIO102). Use the verified address, dimensions, RAW10 VC0 format and existing
stream profile as inputs, while leaving both working camera slots untouched.
First test Camera2 enumeration and sensor probe for camera ID 2. Then exercise
the standard ISPIF/VFE path until camera buffers produce a frame callback and
a dumped RAW10 image. Only after image delivery is verified should
authentication integration begin.

Keep this work separate from the two working camera slots and preserve the
existing `fastboot boot` plus full-teardown procedure for phone tests.
