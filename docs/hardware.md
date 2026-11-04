# Hardware evidence

Source research began on 2026-11-02. The supplied XDA thread was inaccessible
through the cloud network proxy; matching public maintainer sources were inspected instead.
Confirm the installed ROM's build before applying future patches.

Follow-up work on 2026-11-03 recovered CCI master 0 and narrowed the candidate
to model `0x0861`/eight-bit address `0x6c` from the original firmware and code;
see [the analysis](windows-driver-analysis.md). The owner boot-tested the
prerequisite kernel. The owner has now measured model `0x0861` using
[iris-id-02](../kernel/IRIS-ID.md), with a clean unwind and unchanged normal
cameras. This is phone evidence; the source descriptions below remain distinct
from measurements. Streaming and illumination limits remain unresolved.

## Android port baseline

| Component | Public source | Inspected commit |
| --- | --- | --- |
| Device | [giannoccarol/android_device_msft_cityman, lineage-23-cityman](https://github.com/giannoccarol/android_device_msft_cityman/tree/2b12322a7f01973aa601ffeac4bbe297b3f0676d) | `2b12322a7f01973aa601ffeac4bbe297b3f0676d` |
| Kernel | [giannoccarol/android_kernel_mmo_msm8994, lineage-23-cityman](https://github.com/giannoccarol/android_kernel_mmo_msm8994/tree/cc84cab9900ee4e7a3046b3756858e9832caee72) | `cc84cab9900ee4e7a3046b3756858e9832caee72` |
| Port manifest | [giannoccarol/talkman-manifests, lineage-23-cityman](https://github.com/giannoccarol/talkman-manifests/tree/da5e306055af80fadb023cf29931a8470c1e9822/lineageos-23) | `da5e306055af80fadb023cf29931a8470c1e9822` |

The device's `lineage.dependencies` selects `lineage-23-cityman` kernel and
vendor repositories. `BoardConfig.mk` names `kernel/mmo/msm8994`,
`mmo_defconfig`, ARM64 and `Image.gz-dtb`. The camera uses source QCamera2 plus
the legacy Qualcomm daemon and camera provider 2.4. That determines the first
integration target; a generic modern mainline camera module is not a drop-in.
Some README/comment passages on these branches still describe Android 11/13.
Use actual build settings and pinned code rather than treating old comments as
the current port's runtime results.

The pinned kernel's
[`camera-cityman.dtsi`](https://github.com/giannoccarol/android_kernel_mmo_msm8994/blob/cc84cab9900ee4e7a3046b3756858e9832caee72/arch/arm64/boot/dts/mmo/common/camera-cityman.dtsi)
contains rear Carrera/IMX230 and front Ducati nodes. It contains **no iris
sensor node**. The front camera is separate from the Windows iris camera.

Its flash commentary distinguishes:

- `FLSH`: rear visible flash. The Hill library is for this device.
- `FLHT`: tertiary flash associated with iris camera `CAMT`.

The comment that `led:torch_0/1` **"most likely"** drive the iris illuminator
is an inference. It does not verify IR wiring, current, polarity, or exposure.
Do not reuse Hill's rear-flash current tables for iris illumination.

## Connected-phone flash-channel inventory

On installed kernel #29, a read-only inspection found QPNP LED class nodes
`led:flash_0`, `led:flash_1`, `led:torch_0`, and `led:torch_1`. All four
reported brightness `0`; flash nodes reported `max_brightness=1000` and torch
nodes `max_brightness=200`. The separate `flash-torch` node also reported
brightness `0` and is described by the device tree as the rear Hill flash
path. No persistent LED setting was made.

This confirms the PMIC LED controller registered channels, but does not map a
particular channel to the iris emitters. In the pinned `leds-qpnp-flash`
driver, `max_brightness` is populated from the channel's `qcom,max-current`
property and brightness is treated as programmed current. The current device
tree does not declare those four channel properties, so the live values do not
reveal their actual hardware configuration. The Windows tertiary-flash
driver's decoded current codes have unknown units, and its guard rails are not
validated optical or eye-safety limits.

With the phone reported isolated in another room, each QPNP channel was first
activated once at brightness 13. The driver clamps nonzero requests below
13 mA, but then quantizes torch current to 15 hardware steps; 13 maps to code
zero for a 200 mA channel. Those first torch requests therefore did not
establish that the torch outputs emitted light. Flash channels mapped the same
request to code 1. Each channel read back its requested value during the short
test and zero immediately afterward.

A follow-up set `torch_0` to brightness 14, which maps to code 1 by the pinned
driver's integer scaling (`14 * 15 / 200`). The owner observed a faint red glow
from the front IR emitter. This identifies `torch_0` as the active front IR
channel. Its actual current and optical output were not instrumented. `torch_1`
and both flash channels were off after the checks.

Kernel #8 was then temporarily booted and the existing profile was hash-checked
after decoding (351 bytes, SHA-256
`75478697398abf8b21796d408844249af54e05ae7a399afffc33d51dd83e8eb5`). With
`torch_0` held at brightness 14 from before sensor start through the one-shot,
the sensor still timed out at `stream-test`: all 16 frame-counter reads were
zero. CSID3 packets, ECC and CRC also remained zero. Sensor and receiver cleanup
returned zero, and all camera services restarted. The ordinary front camera
preview was dark and showed no clear change during illumination. This first
illuminated attempt is recorded in
[`phone result`](../kernel/builds/iris-csi-03-ir-on-01/phone-result.json). The phone
was returned to installed kernel #29 and every LED channel read zero.

## Original firmware descriptions

[`WOA-Project/Lumia950XLPkg` DSDT](https://github.com/WOA-Project/Lumia950XLPkg/blob/cfc68a4d19fc7e8645bff6d8fce7308ad8494a76/AcpiTables/8994/src/DSDT.asl)
at `cfc68a4d19fc7e8645bff6d8fce7308ad8494a76` provides leads:

- CAMT power description, around lines 27127–27811: `LDO17_A` 2.8 V,
  `LVS1_A` 1.8 V, `SMPS3_A` 1.3 V, `LDO3_A` 1.2 V and
  `BOOST_BYPASS1_B` 4.0 V. These may include shared camera/illumination
  resources; they are not an instruction to enable them all.
- CAMT clock/pin sequence references MCLK1 at 9.6 MHz, GPIO14 and GPIO102,
  and lists CSI3 clock resources alongside shared CSI0/CSI2 resources.
  ACPI resource numbering must be mapped to the Linux camera controller;
  it must not be copied directly into `qcom,csiphy-sd-index`.
- CAMT device around line 46531: `_HID QCOM2436`, MMIO `0xFDA08C00`,
  interrupt `0x56`. This identifies a Qualcomm controller-facing device,
  **not the image sensor model or its I²C address**.
- FLHT around line 46623 depends on CAMT and references PM02 pins
  `0xE9E/0xE9F`. This is not a validated illuminator operating profile.

The DSDT alone does not identify the sensor model or register program. The
subsequent on-phone diagnostic established the model/address response described
above; it has not established CSI capture routing.

## Public original Windows driver metadata

The relevant public package was found; the user does not need to supply a copy
of the same package. [`WOA-Project/Lumia-Drivers`](https://github.com/WOA-Project/Lumia-Drivers/tree/b5af93f99ea800c28551727df55e57a07ba61a82/components/QC899X/Hardware/HARDWARE.CAMERA.MMO_8994/Drivers/Camera)
at `b5af93f99ea800c28551727df55e57a07ba61a82` includes:

- [`Sensors/Iris/qccamsensor_tertiarySMIApp8994.inf`](https://github.com/WOA-Project/Lumia-Drivers/blob/b5af93f99ea800c28551727df55e57a07ba61a82/components/QC899X/Hardware/HARDWARE.CAMERA.MMO_8994/Drivers/Camera/Sensors/Iris/qccamsensor_tertiarySMIApp8994.inf):
  binds `ACPI\QCOM2436` to service `CameraTertiarySensor`, a generic SMIA++
  driver. INF version is `03/18/2021,11.45.15.875`. It does not name the
  physical sensor. Its ARM64 entries describe a null device; the ARM binary
  is the relevant original implementation.
- `Flash/Tertiary/qccamflashtertiary8994.inf`: binds `ACPI\QCOM244C`.
- `Authentication/arm/CameraAuthentication.dll`: strings describe biometric
  capture, frame buffers, exposure, pulsing, IR current and eye coordinates.
  These strings establish capture/control interfaces, not a working matcher
  or a validated sequence of register writes.

The sensor binary contains runtime manufacturer/model/NVM discovery diagnostic
strings. Initial string inspection did not establish the sensor identity.
The later model read supports the `0C086101.dcc` association through the original
Siiri ID formula; [the capture investigation](iris-capture.md) now recovers its
directory, read overrides and static mode geometry. A complete startup/capture
program and illumination limits remain unresolved.

Provenance hashes of inspected files below the package's `Camera/` directory:

| File | SHA-256 |
| --- | --- |
| `Sensors/Iris/qccamsensor_tertiarySMIApp8994.inf` | `19fb82c520ae7c10837857dda0c71ab2be05d5835377fdcc54671a50114c48e5` |
| `Sensors/Iris/arm/qccamsensor_tertiarySMIApp8994.sys` | `0ea99897a1623afd7f165aa2943f2f69687c31dc42a123d6d21c2339ca8e78e5` |
| `Authentication/CameraAuthDriver_arm.inf` | `31e0cd752f53ebe62a440900f1f023fb42fc662012a4b8fe78d8d4b0af79a7e4` |
| `Authentication/arm/CameraAuthentication.dll` | `5e7be37803a0573727ea309a52d5f5e6569875485951ec56023f5d9175b5cd4e` |
| `Flash/Tertiary/qccamflashtertiary8994.inf` | `42578fa1beb16b69e312063781554542d1a66d3a82ea1214143b07175fa89bf6` |
| `Flash/Tertiary/arm/qccamflashtertiary8994.sys` | `58cf8c49d30756a5ddae896cf51aa1dd1ae2733217ee603aebacb44ce047c1c5` |

These hashes record provenance, not a signature-validation claim. No Windows
binary was executed or copied into this repository.

## Information needed before a sensor driver

1. Sensor model `0x0861` and the two-byte ID read are confirmed for one cycle;
   manufacturer and revision are not measured.
2. Master 0, seven-bit SID `0x36`, 16-bit register addressing, reset and the
   sensor-only power sequence worked for that cycle. Repeatability and power
   recovery across suspend remain to be tested.
3. MIPI/CSI lane mapping, link clocks, pixel format and frame timing.
4. Initialization, stream-on/off and exposure/gain register sequences.
5. Calibration/firmware requirements and redistribution permissions.
6. IR illuminator wiring and verified current, duty-cycle, timeout and optical
   exposure limits, including a way to switch it off on every failure path.

The public Windows package above is a starting point for recovering these facts.
Keep binary inputs outside Git and preserve their provenance and hashes.
The baseline collector can identify existing Linux interfaces, but cannot recover
an absent sensor's register program or prove optical safety.

## Android authentication is a separate implementation

In inspected LineageOS 23.2 sources:

- [`hardware/interfaces/biometrics`](https://github.com/LineageOS/android_hardware_interfaces/tree/13d687a84c834af855bfb314b853b8372a7aa6d9/biometrics)
  provides face/fingerprint interfaces, not a standard iris HAL.
- [`IrisService`](https://github.com/LineageOS/android_frameworks_base/blob/daf2b33fac918a464f6f7193214b27d164d39bea/services/core/java/com/android/server/biometrics/sensors/iris/IrisService.java)
  and [`IrisAuthenticator`](https://github.com/LineageOS/android_frameworks_base/blob/daf2b33fac918a464f6f7193214b27d164d39bea/services/core/java/com/android/server/biometrics/sensors/iris/IrisAuthenticator.java)
  have vendor implementation placeholders. Hardware detection and enrollment
  checks do not provide a working implementation.
- [`FaceSensorType.IR`](https://github.com/LineageOS/android_hardware_interfaces/blob/13d687a84c834af855bfb314b853b8372a7aa6d9/biometrics/face/aidl/android/hardware/biometrics/face/FaceSensorType.aidl)
  describes infrared face hardware; it does not supply an iris matcher.

After capture works, choose iris framework integration or a deliberately
designed face-framework integration. Both require enrollment, per-user template
management, matching, cancellation, lockout and accurate capability reporting.
Windows Hello branding is not evidence of Android biometric strength. See
[`SensorStrength`](https://github.com/LineageOS/android_hardware_interfaces/blob/13d687a84c834af855bfb314b853b8372a7aa6d9/biometrics/common/aidl/android/hardware/biometrics/common/SensorStrength.aidl)
and [`ISession`](https://github.com/LineageOS/android_hardware_interfaces/blob/13d687a84c834af855bfb314b853b8372a7aa6d9/biometrics/face/aidl/android/hardware/biometrics/face/ISession.aidl).
