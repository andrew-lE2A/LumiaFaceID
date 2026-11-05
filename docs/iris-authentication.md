# Iris illumination, enrollment and Android unlock path

This document separates the working camera path from the work required for an
enrollment UI and lock-screen authentication. The installed phone still has
the experimental IR camera slot and probe APK; this document does not claim
that iris matching or Android authentication works.

## Windows driver findings

The Windows iris sensor driver is the same SMIA++ implementation used by the
front camera; its differences are sensor data and the allowed CSI receiver
range. `CameraAuthentication.dll` is a capture/frame provider. Its static
analysis records eye-ROI exposure control and per-frame illumination requests
through `FlashCtrlPulseUs`, `IS.HE.FlashPulseLenghtUs`, and
`UseFlashOutOfFrame`. Separate components in the Windows Mobile FFU now
identify the actual Windows Biometric Framework iris engine:
`DeltaIrisEngineAdapter.dll` imports enrollment, identification, template,
eye-info and liveness APIs from `iris_mobile_v2.WindowsPhone.dll`. This
establishes the algorithm interface, but not its exact runtime sequence or
security properties; see [windows-iris-stack-map.md](windows-iris-stack-map.md).

The sensor's strobe capability is zero (`0x1a02` reads zero and DCC block 5 has
no override). Windows therefore does not program the sensor STROBE registers
for this sensor. Per-frame illumination is a host-side flash-driver request.
Static analysis of the exact Windows Mobile FFU now confirms that
`CameraAuthentication.dll` carries its per-frame pulse flag and IR-current
byte in the video-result record and submits that record to the camera KMD via
IOCTL `0x0023432A`. The matching `qccamavs8994.sys` contains a camera-owned
flash/preflash scheduling and frame-gating surface, and the FFU's
`qccamflashtertiary8994.sys` is byte-identical to the previously analyzed
flash driver. The specific consumer of the iris result record, the mapping to
flash selector `0x26`, current units and optical pulse edge remain unresolved;
see
[`windows-flash-driver-analysis-2026-11-05.json`](../docs/windows-flash-driver-analysis-2026-11-05.json).
The sensor-strobe-to-PMIC wiring hypothesis is withdrawn. Do not set the PMIC
LED to hardware-strobe mode for the iris.

The Windows flash driver's current and cooldown checks are undocumented in
units and have not been validated as eye-safety limits. Linux `torch_0`
brightness 14 (hardware current code 1) was observed as a faint red glow, but
that observation does not establish an eye-safe exposure.

### Recovered Windows illumination states and bounds (static analysis)

The latest `leojukic03/lumia-iris-notes` findings (checkout
`e6a3b02`, `FINDINGS.md` sections 5 and 24) distinguish **three illumination
modes**—`None`, `Pulsing`, and `ContinuousLED`—from the driver's **four accepted
assist-power settings**: 13%, 20%, 30%, and 100%. The decompiled LED-7 mapping
is respectively current codes 10, 15, 23, and 22. The notes do not establish
the units of those codes. The mode-number-to-name mapping is also unresolved.
So “three power states” is not quite what the binary evidence says: it is
three named modes plus four accepted power values.

The same analysis reports pulse-length caps of 80,000 for modes 1/2 and 40,000
for mode 3, likely microseconds, and a lower validation branch at 1,000. It
also finds per-LED request `<25`, aggregate request `<49` (units unknown), and
a heat-load cooldown above 2,000 ms accumulated on-time. These are Windows
driver guard rails, not validated optical or eye-safety limits.

**Port boundary:** do not translate Windows current codes 10/15/23/22 into
Linux LED brightness values. Linux `torch_0` brightness 14 maps to hardware
code 1 on this build; the two scales have no established conversion. Nor can
the 13/20/30/100 values be copied into Android's current field until the
Windows LED-7 code units and result-record-to-PMIC consumer are resolved. The
duration caps are useful source-derived ceilings for a future iris-specific
pulse controller, but modes 1/2/3 are not yet mapped to the Android operation.
Keep the existing one-shot control disabled until a bounded, iris-only path
enforces a hard off timeout and its actual current is known. The Windows
thermal thresholds do not fill that safety gap.

A follow-up read of the Windows disassembly confirms the LED-7 mapping function
returns those codes to a PMIC configuration helper, but does not expose a unit
conversion in the caller. In this Linux tree the user brightness for `torch_0`
is requested milliamps: nonzero values below 13 are clamped to 13, and the
current register is programmed as `requested_mA * 15 / configured_max_mA`.
Thus brightness 14 requests 14 mA and quantizes to register code 1 with the
current 200 mA maximum. This makes the Linux scale explicit, but still does
not establish whether Windows codes 10/15/23/22 are milliamps or how those
values relate to Linux's 0–15 register code. No conversion is safe to port yet.

The new one-frame Android YUV capture is **not** the original Windows Hello
enrollment or authentication algorithm. It only checks the camera-to-frame
stage. The Windows Mobile FFU now provides the original algorithm DLL and
adapter interface, including enrollment, identification, template and
liveness operations. Format and lifecycle semantics still need static
call-flow analysis; those Windows ARM binaries are not Android libraries.
Microsoft's general Windows Hello documentation describes an enrollment
profile derived from sensor data and stored as an encrypted, device-local
template; that is architectural context but does not establish how this Lumia
build protects templates or transports trusted results. The [Windows Hello FAQ](https://learn.microsoft.com/en-us/windows/security/identity-protection/hello-for-business/hello-faq)
and [Windows Biometric Framework driver guide](https://learn.microsoft.com/en-us/windows-hardware/drivers/biometric/)
cover that general model.

## Current illumination implementation

The development probe's one-shot **IR + capture** path asks the
root-localhost helper to set `torch_0` to brightness 14. After `ON`, it requests
one YUV still, analyzes the pixels in memory, and discards them; it does not
persist the illuminated frame. Once the `ImageReader` receives the image (or
the request fails), the app sends `STOP` and waits for the helper's `OFF`
confirmation. Client disconnect, helper exit and its one-second timed read
force the LED off. This couples the pulse to one completed buffer
rather than a UI timer, but optical timing and exposure overlap remain
unmeasured. Host tests use a temporary fake LED file to check `STOP`,
disconnect, signal and watchdog cleanup. One physical minimum-code pulse has
now delivered a high-signal YUV frame on Camera2 camera 2; it ran with the
phone in an owner-reported white thin box, whose material reflectance was not
measured. The frame had no face-derived eye ROI and the whole-frame contrast
proposal was display-only. This is not an eye-safety validation or proof of
usable iris detail; see the
[`phone result`](../android/iris-camera-probe/phone-min-current-ir-analysis-2026-11-05.json).
Never use IR while the phone is under a metal can or reflective enclosure, or
point it at people/eyes. Any further emitter test needs a confirmed diffuse
target, no person in the reflected path, and a readback confirming the channel
is zero.

Before considering per-frame synchronization established or using it beyond a
bounded diagnostic:

1. Recover the Windows flash request path and pulse scheduling semantics from
   the camera KMD in the same Mobile FFU: identify the receiver for IOCTL
   `0x0023432A`, trace the result fields into `SetFlashPulses_Flash` or another
   consumer, and relate that schedule to frame/exposure progression. Static
   analysis has confirmed the host-to-KMD handoff and the separate flash
   driver's callback route, but not the connection between them.
2. Trace the Android camera/PMIC flash path for `torch_0`. Linux's LED class
   brightness write is not a hardware exposure-synchronized interface. A
   production route should be driven by sensor/camera frame timing, not a UI
   timer.
3. With a confirmed diffuse target and the phone uncovered, correlate the
   request and image timestamps with sensor exposure metadata. Confirm the
   optical pulse falls inside that frame's exposure and is off on cancellation,
   timeout, camera close, service death, suspend and error. The recorded single
   pulse used an owner-reported white thin box with unmeasured reflectance; it
   does not establish this gate.
4. Validate thermal limits and eye-safety independently before enabling
   repeated pulses or use near a face.

The sensor strobe path is not an alternative: it is unsupported by the
measured sensor capability. The new still-capture sequence requests the frame
after `ON` and holds the pulse until frame delivery. The app now logs
elapsed-realtime bounds around helper request/ack events and logs each
one-frame request submission, YUV buffer timestamp and callback, sensor
timestamp, exposure and timestamp source. A read-only Camera2 metadata dump
reports timestamp source `UNKNOWN` for all three cameras, including iris ID 2;
the sensor timestamp therefore cannot be subtracted from app elapsed-realtime.
The timing analyzer instead matches the YUV timestamp to its capture-result
timestamp and checks request/image callback ordering between helper ON and
STOP. One minimum-code emitter run confirmed that the frame request and
matching YUV buffer were bracketed by the helper transaction. The sensor clock
source is UNKNOWN, so cross-clock exposure overlap cannot be calculated, and
the helper timestamps do not measure LED optical latency. Production-grade
synchronization remains unproven.

### Windows CCI pulse route versus Linux CCI support (static source audit)

The Windows notes trace the IR pulse to a hardware-timed CCI GPIO queue
sequence: wait, drive one CCI output high, wait, then drive it low. The Cityman
Linux kernel snapshot used for these experiments declares `MSM_CCI_GPIO_WRITE`
and GPIO command enum values in `msm_cci.h`, but `msm_cci_config()` handles
`MSM_CCI_GPIO_WRITE` with an empty case. No CCI GPIO command encoder or GPIO
queue register definitions appear in that CCI implementation; the exposed
queue registers and writer cover I2C only. The enum is therefore not a usable
GPIO sequencer.

This is not just a peculiarity of the local snapshot. The public Qualcomm
`android-7.1.0_r0.2` `msm_cci.c` has the same empty `MSM_CCI_GPIO_WRITE` case
([source](https://android.googlesource.com/kernel/msm/%2B/android-7.1.0_r0.2/drivers/media/platform/msm/camera_v2/sensor/cci/msm_cci.c#1613)).
A later Qualcomm camera-stack `cam_cci_core.c` also retains an empty handler
([source](https://android.googlesource.com/kernel/msm/%2B/472258941e6fd2e3f66febfe1753280ef8ba9761/drivers/media/platform/msm/camera/cam_sensor_module/cam_cci/cam_cci_core.c));
its queue writer still emits I2C commands. These comparisons show that the
header declarations alone are not evidence of a working timed GPIO path, and
that copying a newer CCI driver is not a ready-made solution for this pulse.

This narrows a Linux port: matching the Windows timing requires adding and
validating CCI GPIO-queue support in the kernel, then establishing which
physical output the iris uses and whether it reaches the PMIC IR input. The
MSM8994 pinctrl function table lists `cci_timer0` on GPIO21
([source](https://cos.googlesource.com/third_party/kernel/%2B/40e7f406117dc701508205d0ebb98b0b9dbf897f/drivers/pinctrl/qcom/pinctrl-msm8994.c));
that confirms the SoC mux option, but not that Windows output index 0 selects
timer 0 or that the board routes it to the PMIC IR input. A read-only decode
of `cityman-current-boot.img` (SHA-256
`8fbebc5265dd33cdad419f8f34dfc2d5bbde4eb4d71842a2fa81d5714567f38e`, Cityman
DTB SHA-256
`aade67dbfc09f4c44fa2bd484bdb94c94459ea58a5d4e6f08489467ac86caebb`) found
the CCI0/CCI1 bus pin states on GPIOs 17–20 and a `tpiu-setb-8` *definition*
for GPIO21 with mux function 6. The DTB contains no `cci_timer0` pin state or
reference selecting that TPIU definition, so it does not establish GPIO21's
active runtime mux. Do not drive GPIO21 or write guessed CCI registers. No
queue was started and no pin or LED was touched.

The MSM8994 camera CCI device tree configures four CCI bus pads: GPIOs 17/18
for CCI0 clock/data and GPIOs 19/20 for CCI1 clock/data. Their labels are
`CCI_I2C_DATA0`, `CCI_I2C_CLK0`, `CCI_I2C_DATA1`, and `CCI_I2C_CLK1`. It does
not map Windows output indexes 0–4 to TLMM pins or the PMIC input.

The Windows CCI HAL disassembly also clarifies the driver's third argument:
its GPIO-output encoder accepts an output index 0–4 and a level 0/1, then packs
those into the GPIO command word. The iris sequence uses the configured
selector as that output index and requests high then low. This confirms the
logical CCI output number; it still does not map that number to a TLMM pin or
the PMI8994 input.

The reverse-engineered Windows queue encoder provides an implementation
reference without providing a safe Linux register map. WAIT is encoded as
`(scale * value) << 4 | 2`; GPIO output `n` at level `l` is encoded as
`((1 << (n + 4)) | (l << (n + 12))) & ~9 | 6`. For output 0 this gives
`0x1016` (high) and `0x0016` (low). Windows scales the wait value by a
per-device clock factor; the pulse delay/duration unit and factor are still
unverified. These queue words cannot be submitted until the GPIO queue's
register offsets, queue selection, and completion/error handling are
established for this CCI revision.

**Additional audit of the complete local kernel snapshot (2026-11-05).** The
snapshot's `MSM_CCI_GPIO_WRITE` ioctl cannot carry a sequence: its payload has
only `gpio_queue` and `i2c_queue` 16-bit fields, with no command array, count,
timing request, or user buffer. Its handler also returns the initial `rc = 0`
without doing work, so a caller receives a false success. A future
implementation should make that legacy handler return `-EOPNOTSUPP` until
real support exists; it should not reinterpret those two queue fields as
command data. Prefer a new iris-private, bounded request/API that lets the
kernel construct the fixed four-command sequence itself.

The existing I2C path supplies design constraints, not a GPIO register map. It
serializes queue access with a per-master mutex, starts a selected I2C queue
through `CCI_QUEUE_START`, waits on the master completion, and propagates
timeout and I2C error status. The IRQ handler only recognizes reset and I2C
read/report/halt/error bits. The register header defines I2C queue windows and
I2C IRQ masks only; `NUM_QUEUES` is two per I2C master, and the device struct
has no GPIO queue state. Therefore GPIO queue offsets, GPIO completion IRQs,
reset/flush behavior, and safe coexistence with that shared completion and IRQ
path remain unknown. GPIO support cannot safely be added by cloning I2C offset
arithmetic or merely increasing `NUM_QUEUES`.

The kernel's I2C WAIT encoder computes a fixed-point cycle scale from the CCI
clock (`((clk / 1000) * 256) / 1000`) and emits
`((delay_us * cycles_per_us) / 256) << 4 | CCI_I2C_WAIT_CMD`. With a 19.2 MHz
source this corresponds to about 19.2 clock cycles per microsecond after the
fixed-point division. This documents Linux I2C timing only; it does not prove
that the Windows GPIO WAIT scale uses the same clock, source, or unit. The GPIO
implementation still needs binary-level recovery of its scale initialization
and selector setup before timing can be ported.

**Windows WAIT scale dataflow (static disassembly, 2026-11-05).** In the
available `qccamplatform8994-mobile.sys` image (SHA-256
`6ae3eb8078998b3d4e75200c671b90c5e5f385168014c70465941bfad4e90aa2`), function
`0x407914` multiplies the WAIT argument by a 32-bit value at command-context
offset `+0x18`, then shifts it into the WAIT word. The command-context setup at
`0x407750` copies a byte from a nested platform context (`[context + 0x10]`,
then byte offset `+0x0c`) into that scale field. This establishes that Windows
uses a per-platform configured multiplier; the analyzed path does not derive
it directly from a visible clock-rate calculation. The iris driver divides its
delay and duration arguments by ten before submitting them, but their physical
unit and the configured scale's relationship to the CCI clock are still
unknown. The platform-context pointer and byte have not yet been traced back
through driver initialization to their producer; do not assume they come from
ACPI or the registry, and do not substitute Linux's I2C formula.

**GPIO queue and IRQ leads from the same binary.** The queue-object initializer
at `0x4076b0` constructs a pointer from a base pointer at context offset `+4`
plus `0xBC + 0x10 * queue_index`; the submit routine at `0x407d88` later
performs indirect writes through queue-object pointers. This is a concrete
candidate for the HAL's per-queue register window, but the context base and
queue-index mapping have not yet been traced to the CCI MMIO resource. Do not
treat `0xBC` as a verified absolute CCI register offset. The image also embeds
IRQ labels for `GPIO_Q0`, `GPIO_Q1` and `GPIO_Q2` report, underflow, overflow
and command-error causes. Those names confirm distinct GPIO-queue interrupt
classes exist. The ISR at `0x406b14` snapshots and acknowledges two interrupt
status words, then decodes seven indexed masks from the table at `0x416304`;
the table entries, in index order 0–6, are `0x0b0000f7`, `0x13000f07`,
`0x250f1006`, `0x45f01006`, `0x0000000f`, `0x000000f0`, and `0x00000f00`.
It stores each masked result in a per-index state slot at offset `+0xAC`.
The queue initializer uses the mapped index both in its `+0x10` pointer stride
and in a queue-state table, while a helper maps command/master selectors to
indices 0–6. This establishes the decode values and the existence of
per-queue state, but does not yet name each index as GPIO Q0–Q2 or I²C; the
absolute CCI MMIO base and completion semantics also remain unverified. Next,
trace the Windows controller resource into that context and correlate command
selector values with the embedded IRQ names and queue execution path. The
source and physical unit of the WAIT-scale byte remain unresolved.

The current app-level workaround is already available: it requests
`torch_0` at brightness 14, queues one iris capture while the light is on, and
requests OFF on the capture-result callback. One phone run delivered a
high-signal frame (luma p95 212) with matching result/YUV timestamps, but no
face-derived eye ROI; the sensor clock and optical LED edges were not
measured. This is a frame-bracketed illumination check, not the Windows
hardware-timed pulse or usable iris imaging.

### Porting the Windows driver behavior

Port the behavior into the Android camera stack; do not try to load the ARM32
Windows `.sys` binaries. The Windows sensor driver uses Windows CCI and power
interfaces, and the camera/authentication stack uses Windows-specific driver
and WinBio contracts. The existing Android sensor plugin already provides a
separate IR0861 camera slot and returns image frames, so replacing it wholesale
with a monolithic kernel sensor driver would duplicate a working layer.

The matching driver should be split at these boundaries:

1. **Sensor and stream control:** keep the existing IR0861 camera slot for
   probe, mode tables, exposure and frame delivery. Port only any verified
   missing sensor behavior from the Windows SMIA++ path.
2. **Timed illumination request:** add an iris-only kernel CCI GPIO sequencer
   that accepts bounded delay/duration requests and queues Windows-compatible
   WAIT/GPIO words. Before writing it, recover the CCI GPIO queue register
   offsets, queue index/selector meaning, Windows wait-scale initialization,
   GPIO IRQ bits and completion/error behavior from `qccamplatform8994.sys`.
   The Linux CCI WAIT encoder is known for I2C only; do not assume the GPIO
   queue shares its register layout or clock scale.
3. **Physical output and LED:** establish whether output 0 is CCI_TIMER0/GPIO21
   and whether the board connects it to the PMI8994 IR input. Until verified,
   do not treat sensor STROBE or a generic camera flash endpoint as equivalent.
   Keep the tested minimum-current `torch_0` app path as a separate diagnostic.
4. **Android authentication:** implement enrollment, matching, lockout and
   framework integration as a separate Android biometric authenticator. The
   Windows WinBio engine and result protocol are not part of the sensor driver
   and are not binary-compatible with Android.

For a faithful pulse, the kernel interface should be iris-only, reject
out-of-range requests, serialize with CCI/I2C traffic, clear any queued work on
cancel/release, report queue errors, and guarantee a low output on teardown.
The existing no-op ioctl is not a usable implementation contract: it falsely
reports success and has no sequence payload.
Only after a register-map review should an opt-in, temporary-boot test verify
queue acceptance and completion without issuing a GPIO output command. A
single output pulse should wait until its pin mux and route are established and
the emitter channel has a verified disabled state. This keeps the Windows queue
implementation independent of the PMIC current-control path and avoids
mistaking a successful CCI command for a successful optical pulse.

### Camera flash plumbing audit (2026-11-05)

Static review of the pinned Cityman camera sources found that the iris plugin
sets `is_flash_supported = 0`, and the opt-in `camera@2` device-tree node has
no `qcom,led-flash-src`. During sensor probe, the kernel uses that flag to set
the iris sensor's `SUB_MODULE_LED_FLASH` subdevice ID to `-1`. Consequently,
the Camera2 flash controls cannot currently target the iris slot; the app's
sysfs helper is a separate LED-class path and does not synchronize the torch
with sensor exposure.

PMI8994 exposes `led:torch_0` through the `torch0_trigger`, with DT operational
current 120 mA and maximum 200 mA. Those values describe the existing LED
configuration, not validated eye-safety limits. The iris slot currently has
no camera-flash subdevice. The separate local kernel checkout contains an
experimental `msm_flash` SOF hook, but it is behind a module parameter and
depends on a configured flash subdevice and LED trigger source. The iris DT
slot does not connect it to `torch0_trigger`, and its sensor plugin disables
flash support. Therefore that hook is not evidence of synchronized iris
illumination and must not be enabled as-is.

The PMIC backend makes the mismatch more specific: `CFG_FLASH_LOW` writes the
configured torch trigger, while `CFG_FLASH_HIGH` first turns torch triggers
off and then writes configured flash triggers. The experimental SOF hook only
arms `CFG_FLASH_HIGH`. Thus wiring `torch0_trigger` as a torch source would
make the torch available through the camera flash subdevice, but would not
make that hook synchronize it. Wiring `flash0_trigger` instead is not
justified: current evidence identifies only `torch_0` as the visible IR
emitter, and the flash-channel mapping has not been physically verified.
Before choosing either route, the kernel path needs to establish which IR
channel can be driven at its lowest stable current and whether the selected
capture request reaches `CFG_FLASH_LOW` or `CFG_FLASH_HIGH`.

The generic camera torch route is not a safe shortcut to test. In the pinned
Cityman HAL, `QCameraFlash::setFlashMode(true)` requests `CFG_FLASH_LOW` with
`QCAMERA_TORCH_CURRENT_VALUE = 200`. The PMI8994 torch node has
`qcom,max-current = <200>` and `qcom,current = <120>`. The kernel accepts a
requested current only when it is strictly less than the configured maximum,
so a request of 200 falls back to the DT operating current of 120 mA. That is
far above the observed 14 mA sysfs setting and has no validated eye-safety
limit. Do not expose the iris through this generic route until a separately
bounded current limit is implemented and verified. This is a source-level
conclusion; it has not been exercised on the phone.

The camera flash parser reads both `qcom,current` and `qcom,max-current` from
the PMIC LED node referenced by `qcom,torch-source`; the camera node itself
does not provide a per-camera torch-current override in this tree. Reusing
`pmi8994_torch0` therefore inherits the global 120 mA operating current. A
software limit would need an explicit kernel change that caps the iris flash
controller's torch request before `led_trigger_event()`, with an iris-only DT
opt-in and a hard OFF watchdog. Changing the shared PMIC node would also
affect other consumers and is not an iris-only limit.

The currently inspected `msm_flash` watchdog does not cover `CFG_FLASH_LOW`:
that command cancels the delayed main-flash timeout and then enables the torch
without arming a replacement timer. `CFG_FLASH_RELEASE` does call the common
OFF handler, but that depends on teardown reaching release. A camera-owned
iris torch therefore needs a LOW-specific bounded timeout as well as the
current cap; camera close/release alone is not a sufficient fail-safe if the
HAL or process stops responding.

Android's Camera2 `FLASH_MODE_TORCH` is mapped by the HAL to
`CAM_FLASH_MODE_TORCH`, but `ANDROID_FLASH_INFO_AVAILABLE` and flash-state
metadata are gated by the sensor capability's `flash_available` flag. The
iris plugin currently reports no flash support, and its DT node does not bind
a flash subdevice. Correctly isolating a camera-owned torch therefore needs
all of these changes together: make the iris capability advertise flash,
attach a dedicated flash endpoint to camera slot 2, constrain its configured
torch operating current, and add an iris-specific bounded shutoff path. Merely
adding the `torch0_trigger` phandle would route the existing 120 mA fallback
into the iris session. The existing Windows-derived per-frame pulse
requirements still need a frame-timing implementation; Camera2's continuous
torch mode is not exposure synchronization.

The concrete software investigation is to trace the flash subdevice's probe,
configuration and release lifecycle, then determine whether a dedicated
PMIC-backed flash endpoint can safely expose only `torch0_trigger` to the
iris sensor while preserving the existing camera slots. That route needs a
bounded off path; if per-frame timing is required, the kernel also needs a
SOF path that controls the verified IR channel instead of blindly reusing the
flash-only high path. Verify the lowest-current mapping before any additional
phone test. One bounded Android pulse has already been tested and logged; no
kernel or camera-HAL illumination synchronization change has been made by this
source audit. The current physical setup is not independently verified by the
software; do not repeat an emitter test until the target is confirmed diffuse
and the phone is uncovered.

## Enrollment and lock-screen authentication

The current Android 16 system exposes the framework `IBiometricService`, but
read-only service and VINTF inspection found no biometric HAL service. The
probe app is not enrolled with Android and cannot unlock the device.

Microsoft's WinBio workflow confirms that enrollment is driven by biometric
samples accepted by an engine adapter, then incrementally updates and commits a
template. The recovered Lumia binaries expose analogous interfaces, but the
Windows documentation's strong secure-sensor path requires isolated matching,
secure sample input, presentation-attack detection and a protected credential
release (WinBio 4.0 `CreateKey` / `IdentifyFeatureSetSecure`). Static analysis
has not shown that the Lumia's iris unit implements that v4 secure path. On
Android, Camera2 frames are visible to the normal OS; therefore this project
must not claim strong biometric unlock based only on an app-side matcher or
template encryption. See Microsoft's [WinBio adapter workflow](https://learn.microsoft.com/en-us/windows/win32/secbiomet/adapter-workflow)
and [secure-sensor requirements](https://learn.microsoft.com/en-us/windows/win32/secbiomet/sensor-requirements-for-secure-biometrics),
and the [local Windows stack map](windows-iris-stack-map.md).

The recovered Windows Mobile evidence is stronger than an unknown-version
assessment: the WinBio registry entry sets `Capabilities=0x80` (virtual
sensor) and omits `0x100` (secure sensor), while static analysis of
`DeltaIrisEngineAdapter.dll` shows its exported WBF engine interface is v3.0.
Microsoft's documented TPM secure-match methods are v4.0, so the recovered
WinBio iris path does not expose that protocol. A separate Lumia trusted path
is not ruled out, but current `Origa2Auth.sys` evidence does not support one:
its WDF GUIDs match values under Qualcomm's `qcbifbattdrv\\AuthLibrary`
configuration, associated in the SYSTEM hive with a BIF battery driver. The
interface consumers remain unresolved, so Origa2Auth should not be treated as
evidence of trusted iris matching. The Android port still has no iris
biometric service or trusted matcher, so an app-side matcher cannot be
promoted to lock-screen authentication based on this Windows configuration.

The next gates are:

1. Complete stable RAW/YUV frame delivery, correct orientation/geometry,
   controlled exposure and synchronized IR. Add iris/eye localization and
   quality feedback for a diagnostic enrollment screen.
2. Trace the recovered Windows adapter-to-engine contract, then decide whether
   to implement a native Android engine or use a separately selected matcher.
   Evaluate repeatability, false-match rates, presentation attacks and
   liveness. Store enrollment templates per Android user; do not put raw frames
   or templates in a normal app's shared storage.
3. Choose and implement the framework route only after the capture/matcher
   evidence exists. The Android 16 AOSP `hardware/interfaces/biometrics` tree
   has Face and Fingerprint AIDL HALs, but no Iris AIDL HAL. AOSP's Android 16
   `AuthService` still parses configured legacy `TYPE_IRIS` sensors and sends
   their properties to `IIrisService`; `BiometricService` registers
   `IBiometricAuthenticator` implementations generically. This is a possible
   compatibility path, not a ready camera-backed implementation: at the
   port's inspected framework commit, `IrisAuthenticator` is only a stub, and
   the phone does not currently publish `iris` or register biometric sensors.
   Face AIDL is another available interface, but its IR sensor type describes
   infrared face hardware and does not make an iris matcher or make iris data
   semantically equivalent to face recognition. Any route needs enrollment,
   authentication, removal, active-user handling, cancellation, lockout,
   authenticator ID and hardware-authentication-token handling.
4. Determine whether MSM8994 can provide a protected camera-to-matcher path
   and trusted match result. Until secure processing, liveness and Android's
   biometric requirements are met, do not advertise this as a strong
   biometric or use it to authorize apps, payments or authentication-bound
   keys. A camera-only app can be a diagnostic, not a secure unlock service.

The current port has neither a biometric HAL nor verified secure iris
processing. See the [Android 16 biometric HAL tree](https://android.googlesource.com/platform/hardware/interfaces/+/android16-release/biometrics/),
[Android 16 AuthService iris registration path](https://android.googlesource.com/platform/frameworks/base/+/android16-release/services/core/java/com/android/server/biometrics/AuthService.java),
[Android 16 BiometricService dispatcher](https://android.googlesource.com/platform/frameworks/base/+/android16-release/services/core/java/com/android/server/biometrics/BiometricService.java),
and [AOSP biometric security requirements](https://source.android.com/docs/security/features/biometric/measure).

### Device trust-state readback (2026-11-05)

Read-only service and property inspection on the connected Lumia found
KeyStore2 (`android.system.keystore2.IKeystoreService/default`) and Gatekeeper
(`android.service.gatekeeper.IGateKeeperService`) registered. The framework
biometric and auth services are also registered, but `dumpsys biometric`
reports no sensors and no active session. The phone reports
`ro.boot.flash.locked=1` and `ro.crypto.state=unsupported`. `lshal` lists a
running legacy Keymaster 3.0 service, but no KeyMint or Weaver service was
found. Keymaster/Gatekeeper availability may support some hardware-backed key
operations, but service registration does not prove key attestation, secure
user-ID binding, or a protected camera-to-matcher/result path. The crypto
property also means we cannot assume user data or an app-private iris template
is encrypted at rest. Do not persist a real enrollment template or claim
strong unlock on this evidence. This readback does not prove the TEE-backed
credential confirmation required before Class 1 enrollment. Class 2/3 would
add isolated matching and protected template/camera paths; Class 3 also needs
the hardware-backed keystore and valid HAT flow. Raw capture remains on-device
and should not be copied off for development.

The latest read-only check (2026-11-05) again found all four LED brightness
values at zero, all three camera IDs closed, and the iris service absent. An
older `dumpsys media.camera` history entry named the temporary frame-check
package, but there was no active camera client during this check. No camera or
emitter operation was performed. The phone remains under the user's reflective
can, so emitter experiments stay deferred until the enclosure is removed and a
diffuse target is arranged. See
[`phone-state-readback-2026-11-05.json`](../android/iris-camera-probe/phone-state-readback-2026-11-05.json).

The exact readback is recorded in
[`android16-device-trust-state-2026-11-05.json`](../android/iris-camera-probe/android16-device-trust-state-2026-11-05.json).

A fresh read-only ADB check on 2026-11-05 found all three camera devices
closed, no active camera clients, and all four LED channels at zero. The iris
service and feature remain absent. No camera or emitter operation was needed;
see [`phone-idle-readback-2026-11-05.json`](../android/iris-camera-probe/phone-idle-readback-2026-11-05.json).

A further read-only check at host UTC 04:26 on 2026-11-05 confirmed the same
idle state: all LEDs at zero, camera IDs 0/1/2 closed, no biometric sensors or
session, and no iris service. The phone's own clock reported 2026-11-04
21:50 UTC, so its clock is about 6 hours 36 minutes behind host UTC. No stream
or IR test was run under the reflective can. See
[`phone-safety-readback-2026-11-05-0426Z.json`](../android/iris-camera-probe/phone-safety-readback-2026-11-05-0426Z.json).

A fresh read-only check at host UTC 2026-11-05 confirmed Android 16 build
`23.2-20261102-UNOFFICIAL-cityman`, three camera devices, no active camera
client or biometric session, no `iris` binder service, no registered
biometric sensors, and all four LED channels at zero. Camera ID 2 was closed;
a historical camera dump entry still mentioned the temporary probe package.
Nothing was opened or written. See
[`android16-current-unlock-state-2026-11-05.json`](../android/iris-camera-probe/android16-current-unlock-state-2026-11-05.json).

### Framework route audit

The LineageOS 23.2 biometric HAL tree has `common`, `face` and `fingerprint`
subtrees, with no iris AIDL HAL interface. The port's inspected framework
commit is `daf2b33fac918a464f6f7193214b27d164d39bea`. It includes
`IrisService` and `IrisAuthenticator`; `SystemServer` starts the service only
when `PackageManager.FEATURE_IRIS` is declared. The service can register
configured legacy `TYPE_IRIS` sensor properties, but its `IrisAuthenticator`
is unimplemented: it returns false for hardware detection and enrollment,
returns null sensor properties, and leaves prepare/start/cancel/invalidation
operations empty. Thus the generic AOSP Android 16 authenticator path does not
make this port's iris usable. The phone currently returns `Service iris: not
found`, advertises no iris feature in `pm list features`, and
`dumpsys biometric` lists no sensors.

The first framework implementation target is therefore the pinned legacy iris
service/authenticator adapter plus product feature/config wiring, after a real
matcher and reliable capture are established. A source review of the current
Cityman `lineage-23-cityman` device tree (revision
`8f14e902f728898c1483c115cfe243ce637aa299`) found that `device.mk` does not
copy `android.hardware.iris.xml`, and no overlay entry exists for
`config_biometric_sensors`. I prepared a local-only experimental patch at
[`0002-cityman-enable-experimental-iris-service.patch`](../android/patches/0002-cityman-enable-experimental-iris-service.patch)
that adds the feature declaration and `2:4:4095` (sensor ID 2, `TYPE_IRIS`,
`BIOMETRIC_CONVENIENCE`). It passes a patch dry-run against a clean copy of the
device tree and the overlay XML parses. It has not been built or installed.

This wiring will make SystemServer publish IrisService and ask AuthService to
register the configured sensor, but the current IrisAuthenticator remains a
stub; this patch alone cannot authenticate or unlock. In the separate pinned
framework checkout, I also changed the registration seam so IrisService passes
the complete configured `SensorPropertiesInternal` to IrisAuthenticator and
`getSensorProperties()` returns it instead of `null`. The local patch is
[`0003-lineage-iris-authenticator-properties.patch`](../android/patches/0003-lineage-iris-authenticator-properties.patch).
It passes `git diff --check` but is not compiled or installed. No camera access,
LED activation, phone modification or GitHub push occurred. The tree is checked
out under `/private/tmp/lumia-cityman-device` and the framework source under
`/private/tmp/lumia-android-frameworks-base`.

The pinned `KeyguardUpdateMonitor` also rejects `BiometricSourceType.IRIS` in
its modality unlock policy and has no iris result state. I added a local
Class 1 result sink in
[`0004-lineage-keyguard-class1-iris-result.patch`](../android/patches/0004-lineage-keyguard-class1-iris-result.patch).
It uses only a non-strong success, honors iris-specific and global biometric
DPM disable flags, rejects wrong-user and going-to-sleep callbacks, clears its
per-user recognized state with other Keyguard biometric state, and adds no
bypass path. Patch 0007 adds an initial lifecycle bridge through Keyguard state updates.
It starts only while the selected user is on an interactive, visible Keyguard,
with strong-auth/policy gates satisfied and no face-auth session, prompt, sleep,
dream, user switch or pending biometric continuation. It stops when any gate
closes and caches the per-user enrollment query until authenticator callbacks
invalidate it. This source patch is not compiled or installed; the camera
provider, matcher, enrollment store and lockout/rate-limiting path are still
missing.

I added a hidden request/cancel contract in
[`0005-lineage-iris-keyguard-request-api.patch`](../android/patches/0005-lineage-iris-keyguard-request-api.patch): `IrisManager.authenticateForKeyguard()` sends an internal Binder request, receives success/failure/error callbacks, and supports cancellation. `IrisService` requires `USE_BIOMETRIC_INTERNAL`, verifies the caller with `Utils.isKeyguard()`, and currently returns `BIOMETRIC_ERROR_HW_UNAVAILABLE` because the camera authenticator is absent. The code has no success shortcut. KeyguardUpdateMonitor provides explicit start/stop methods that route callbacks and cancel when its biometric state is cleared; callbacks are now bound to the exact requested user ID before forwarding success. Patch 0007 now invokes these methods from Keyguard biometric-state updates and
face-auth running-state changes. It also gates on visible/interactive Keyguard
state, current user and policy, and cancels when face-auth activity is reported. It is not a provider-level camera lock; cancellation latency could still overlap camera ownership.

Patch 0006 adds a Keyguard-only `hasEnrolledTemplatesForKeyguard()` query that checks the registered iris authenticators directly. The current `IrisAuthenticator` stub returns false, so Keyguard's start method now fails closed until a real per-user iris store reports an enrollment. This avoids treating another modality's enrollment as an iris enrollment. The query is not an enrollment implementation: there is still no camera provider, matcher, template store, active-user lifecycle, or iris lockout/rate-limit backend. Patches 0003-0007 have not been compiled or installed.

The active device tree and
vendor VINTF manifest have no iris HAL declaration. A camera-backed
framework service can use the already declared camera provider; adding a new
biometric VINTF HAL is not required for that route. Product feature/config,
SystemServer service startup, permissions/SELinux and the modality service
API still need implementation. The service needs full enrollment, per-user
storage, matching, cancellation, lockout and authenticator-ID lifecycle. A
separate Face AIDL prototype would label iris as face and should not disguise
the modality. Do not return a mock-success token. See
[`android16-framework-iris-audit-2026-11-05.json`](../android/iris-camera-probe/android16-framework-iris-audit-2026-11-05.json).

I fetched the five framework files at the pinned Lineage commit into temporary
storage and inspected the exact contract. `SystemServer` starts `IrisService`
only when `FEATURE_IRIS` is declared; `AuthService` forwards configured
`TYPE_IRIS` sensor properties to it; and `IrisService` registers the sensor
through the generic `IBiometricAuthenticator` interface. The pinned
`IrisAuthenticator` is entirely inert: it retains an `IIrisService` reference
but never calls it, reports hardware and enrollment as false, returns null
sensor properties, leaves authentication and cancellation empty, returns
authenticator ID 0, and reports no lockout. The service therefore needs a real
camera-backed authenticator implementation plus matching/enrollment state;
adding only `FEATURE_IRIS` or a config row cannot make it authenticate. The
reviewed source files were kept under `/private/tmp`, not added to the
repository.

An additional cross-check against AOSP's `android16-release` clarifies the
adapter boundary: its biometric HAL interface tree contains common, face and
fingerprint interfaces, while `AuthService` still parses legacy `TYPE_IRIS`
configuration and forwards it to `IIrisService`. `BiometricService` uses the
generic `IBiometricAuthenticator` registration/session path and has no
iris-specific branch. Thus the Lineage `IrisService` is a compatibility shim
into the generic framework service; adding an iris AIDL HAL alone would not
provide the missing sensor implementation. See the [Android 16 HAL tree](https://android.googlesource.com/platform/hardware/interfaces/+/android16-release/biometrics/), [AuthService](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android16-release/services/core/java/com/android/server/biometrics/AuthService.java), and [BiometricService](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android16-release/services/core/java/com/android/server/biometrics/BiometricService.java). The exact [pinned Lineage IrisAuthenticator](https://github.com/LineageOS/android_frameworks_base/blob/daf2b33fac918a464f6f7193214b27d164d39bea/services/core/java/com/android/server/biometrics/sensors/iris/IrisAuthenticator.java), [IrisService](https://github.com/LineageOS/android_frameworks_base/blob/daf2b33fac918a464f6f7193214b27d164d39bea/services/core/java/com/android/server/biometrics/sensors/iris/IrisService.java), and [SystemServer](https://github.com/LineageOS/android_frameworks_base/blob/daf2b33fac918a464f6f7193214b27d164d39bea/services/java/com/android/server/SystemServer.java) confirm the compatibility wiring and feature gate.

## Regular selfie camera order

The phone now reports camera ID 1 as front-facing 2600×1952 VS6955 and ID 2 as
front-facing 1920×1088 IR0861. The locally rebuilt Cityman camera interface
places the regular selfie sensor first when
`persist.camera.cityman.iris_last=1`. Aperture opened camera ID 1 and returned
a live preview. The user's magenta room lighting explains the preview tint; a
green overlay on saved photos is a separate, unresolved capture-pipeline issue.
The implementation and phone result are recorded in
[`android/patches/0001-cityman-camera-hal-put-iris-after-selfie.patch`](../android/patches/0001-cityman-camera-hal-put-iris-after-selfie.patch)
and [`android/camera-order-result-2026-11-04.json`](../android/camera-order-result-2026-11-04.json).

## Android unlock implementation start

The kernel is already running the previously tested #18 image. A fresh read of
the phone's boot partition matches that tested image byte-for-byte (SHA-256
`f0699d7737af61254e531ce2475ba841e50a1cdef2924594f0dab8954d1d8f55`), so no
second write was needed. On this build, the iris produces continuous Camera2
callbacks and clean CSID3 packet/ECC/CRC counts. Its preview is still noisy and
there is no Android biometric enrollment or hardware-evaluated matcher. A
three-sample rotation-aligned consensus helper exists in the experimental Java
matcher and is now wired to an explicit diagnostic UI flow. The app retains
only candidate codes in memory; it persists nothing and has no identity
threshold.

On 2026-11-05, a short IR-off preview check with the older installed probe
selected camera ID 2 from its unique 1920×1088 metadata and logged capture
result callbacks through frame 89 at roughly 13.5 callbacks/second. No still
capture or pixel analysis was requested. After force-stop, CameraService
reported all three devices closed and all four torch/flash channels read 0.
This reconfirms stream startup and cleanup, not usable image content; the
details are in
[`phone-preview-check-2026-11-05.json`](../android/iris-camera-probe/phone-preview-check-2026-11-05.json).

The phone exposes Android's framework `IBiometricService`, but its vendor
VINTF manifests contain no Face or iris HAL. Android 16 has no Iris AIDL HAL.
AOSP retains legacy `IIrisService` registration and generic authenticator
sessions; this port's pinned `IrisAuthenticator` remains a no-op stub and the
product does not declare the iris system feature. A live read confirms
`service check iris` is not found and `dumpsys biometric` reports an empty
sensor list. The Face AIDL interface is available, but `FaceSensorType.IR`
means infrared face sensor, not iris. A camera-backed framework iris service
does not need a new biometric VINTF HAL, but it does need feature/config
wiring, SystemServer startup, SELinux policy, product packaging, enrollment,
authentication, enumeration/removal, active-user switching, cancellation,
lockout, and authenticator-ID lifecycle. Enrollment must validate the framework's
credential-confirmation chain. Class 1 has no Strong-class keystore authority
and must not fabricate or rely on a HAT. In the installed `AuthSession`, a
non-Strong result is sent through the BiometricPrompt dialog flow while any
attached HAT is dropped. This confirms a HAT is not needed for that
non-Strong session, but it does not provide the separate callback that
Keyguard uses to unlock.
The implementation order is:

1. Obtain stable raw captures and determine whether the sensor optics and
   current illumination/exposure can produce a repeatable iris texture. Fix
   the green saved-image overlay independently of the known magenta room light.
2. Implement offline eye/iris localization and matching, measure false accepts
   and rejects across consented multi-session samples, and test presentation
   attacks. Keep the diagnostic matcher outside Android's unlock path until
   results are measured.
3. After offline matching is credible, audit the exact Lineage 23.2 source
   against AOSP Android 16's legacy `TYPE_IRIS` registration and generic
   authenticator session path. If the port retained a supported legacy iris
   route, prototype a real adapter there; otherwise make framework changes
   explicit and reviewable. Treat Face AIDL only as a separate design option,
   because its IR sensor type is defined for face hardware. Do not claim
   `STRONG`, return fabricated HATs, or expose a Class 1 sensor to app
   authentication. Enrollment and authentication must use real framework
   callbacks, not a mock-success path.
4. The viable first Android unlock target, if later evidence supports it, is
   Class 1 (Convenience): it can participate in device lockscreen
   authentication but cannot be exposed through app biometric APIs or
   authorize keystore keys. It does not require a Strong-class HAT; the
   software authenticator must not fabricate one. Android 16 CDD sets Class 1
   FAR below 0.002% and limits spoof/imposter acceptance to 30% for Level A
   and 40% for Level B presentation attack instruments. It requires rate
   limiting, primary-credential fallback after no more than 20 false trials
   with at least a 90-second backoff, and disabling biometrics after primary
   credential backoff begins. It also requires credential-confirmed
   enrollment using a device credential secured by the TEE, deleting all
   identifiable biometric data when the user or primary credential is
   removed, honoring `KEYGUARD_DISABLE_IRIS`, and primary-credential fallback
   at least every 24 hours or after 4 hours idle or 3 failed attempts. The
   current prototype has no measured FAR/SAR, no presentation-attack test
   results, no enrollment/removal path, and no trustworthy persistent template
   storage, so it is not ready to unlock. These requirements are in the
   [Android 16 CDD, section 7.3.10](https://source.android.com/docs/compatibility/16/android-16-cdd#73-biometric-sensors).
   Class 2 and 3 additionally require isolated matching and protected camera
   data/result paths; Class 3 also requires hardware-backed keystore support.
   The Keyguard path must be explicit and system-only. The installed
   `AuthSession.onAuthenticationSucceeded()` belongs to the BiometricPrompt
   dialog flow; its StatusBarService notification is not, by itself, proof of
   a Keyguard unlock callback. An iris implementation must add a similarly
   privileged request/cancel/result path
   and Keyguard state handling, while keeping public BiometricPrompt strength
   filtering unchanged. In the pinned Lineage SystemUI source,
   `KeyguardUpdateMonitor` subscribes to a `FaceAuthenticationListener` and
   routes success, failure, acquired, error and lockout statuses into Keyguard
   state. Iris needs equivalent lifecycle and status integration. The pinned
   `FaceService` provides the closer model: its modality-specific
   `authenticate()` call schedules through a sensor `ServiceProvider`, while
   its separate `prepareForAuthentication()` path serves BiometricPrompt.
   Build an iris service/provider and `IrisManager` API for the Keyguard path,
   gate that request to SystemUI, and deliver statuses into
   `KeyguardUpdateMonitor`. Keep the existing generic
   `IBiometricAuthenticator` registration separate, and keep Convenience
   unavailable through public `PromptInfo` APIs.
5. Only after those gates pass, integrate the adapter with Keyguard/Settings
   and test the real lockout, timeout, user-switch, cancellation and recovery
   paths. Keep diagnostics separate from system authentication until then.

The Windows driver evidence describes capture and per-frame flash requests,
not a recovered iris-matching algorithm. The measured sensor reports no strobe
capability, so its hardware strobe is unavailable. The experimental `torch_0`
still-capture sequence has host-tested cleanup but has not been measured on
the Lumia emitter or against exposure timestamps. Validated synchronization
and an independently verified off path remain prerequisites to
recognition-quality capture.

### First private YUV capture test

On 2026-11-04, a separately signed development build opened only iris camera
ID 2 and configured the normal preview plus one `YUV_420_888` still output.
Capture-result callbacks continued, and one manual 1920×1080 frame was stored
in the app's private directory as I420. No LED channel was enabled. The frame
was summarized on-device; only aggregate plane statistics were recorded:
Y mean 79.79 (standard deviation 24.00), U mean 127.46 (0.96), V mean 124.22
(1.54). Chroma is close to neutral on this IR stream. This does not identify
iris texture or diagnose the green overlay in ordinary-camera saved photos.
The raw frame remains on the phone; no pixel data was copied to the host.

The first app run hit a UI-thread exception in the new button update. That app
bug was fixed; the second run opened the iris, configured both streams, and
captured successfully. The test app was force-stopped afterward, CameraService
reported no active camera clients, all camera services were running, and all
four LED channels read zero.

### Spatial quality probe

On 2026-11-05, a separate local development package added on-device spatial
luma measurements. It opened only iris camera ID 2, captured one 1920×1080
YUV frame with every IR/flash channel off, and summarized the private frame on
the phone. Luma mean was 72.28, standard deviation 22.46, 5th/50th/95th
percentiles 39/73/106, and mean absolute horizontal/vertical gradients 1.74 /
1.74. Across an 8×6 grid, tile standard deviation ranged 6.04–15.60. These
values establish that the stream contains spatial variation, but cannot show
that the iris itself is resolved or suitable for matching. The user reports a
dark room with pink/magenta visible lighting; visible color does not establish
near-IR irradiance. Because the emitter was off and ambient illumination was
uncontrolled, treat this only as a dark-scene baseline, not a Windows Hello
comparison. No image pixels were exported. The app was closed, CameraService
had no active clients, and all four illumination channels read zero. Full result:
[`quality-result-2026-11-05.json`](../android/iris-camera-probe/quality-result-2026-11-05.json).

The probe now also rotates a 320×180 downsampled luma image into portrait and
runs Android's generic `FaceDetector` entirely in memory to estimate a coarse
eye-pair location. Running this on the saved room-only frame produced no
frontal-face candidate at 180×320, as expected for a scene without a face. It
does not localize an iris, and the negative result says nothing about a future
eye capture. The phone remained with no active camera clients and all four
illumination outputs at zero. See
[`eye-region-result-2026-11-05.json`](../android/iris-camera-probe/eye-region-result-2026-11-05.json).

A fresh pass used the existing app-private frame with a temporary, separately
signed analyzer package. The original file stayed in its original private
directory; a same-device temporary copy was removed when the package was
uninstalled. The on-phone result again had no generic face-derived eye-box
proposal. The app displayed aggregate image statistics only, with eye
coordinates withheld. Its display-only whole-frame circle fallback also found
no candidate, even though luma p95 was 106 and passed the provisional signal
gate. No camera or LED was opened, and the original raw frame remains on the
phone. This confirms the room frame cannot exercise ROI or matcher processing;
it does not rule out useful iris capture under a real eye and appropriate IR
setup. See
[`saved-frame-on-device-analysis-2026-11-05.json`](../android/iris-camera-probe/saved-frame-on-device-analysis-2026-11-05.json).

## Windows comparison limits

What we can compare now is static Windows driver/calibration configuration,
not a live Windows Phone frame. The recovered Siiri mode is 1920×1088 RAW10,
one CSI data lane, line length 2100; the DCC-derived metadata uses gain
`code / 56` over codes 56–448, coarse margin 6, pedestal 0 and pixel order 0.
The Windows capture component also requests eye-region exposure control and
per-frame flash assistance. This phone currently boots Android and has no
Windows Phone OS partition listed; the WOA desktop Windows driver release also
lists camera and Hello iris as unavailable, so that is not a substitute for
the original Windows Mobile stack. A genuine Windows runtime comparison would
require restoring/booting a Windows Mobile image and is outside this Android
test. The dark, emitter-off Android capture is not comparable to an illuminated
Windows Hello scan.

### One-frame eye-region diagnostic

The probe now has an **Analyze one live frame (no save)** action. It sends one
still request to the existing YUV reader with IR left off, downsamples only the
Y plane in memory, runs the generic Android face detector, maps the estimated
eye pair and heuristic crop boxes back into sensor coordinates, and discards
the frame. The coordinate transform passes synthetic round-trip checks at 0,
90, 180 and 270 degrees. This is a software path check, not a phone measurement;
the phone was left idle and no camera stream or emitter was started. The boxes
are not iris boundaries, and this action has not yet been exercised on a
person or evaluated on a usable eye capture. See
[`live-eye-region-pipeline-result-2026-11-05.json`](../android/iris-camera-probe/live-eye-region-pipeline-result-2026-11-05.json).

### Circular boundary proposal

The live one-frame diagnostic now runs a bounded circular contrast search in
both heuristic eye boxes, then passes any proposed annulus through the
log-Gabor phase coder and reports only geometry, edge strengths and valid-bit
fraction. It retains neither pixels nor a code. The method is a coarse proposal
based on circular pupil/limbus contrast; literature describes integral-
differential/circular boundary searches as common starting points, while
non-cooperative captures require handling eyelids, occlusion and irregular
contours ([IET Biometrics overview](https://ietresearch.onlinelibrary.wiley.com/doi/full/10.1049/bme2.12074), [IET non-ideal segmentation study](https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/iet-ipr.2012.0084)).
A synthetic concentric pattern recovered pupil center (121, 99), pupil radius
22 px and outer radius 51 px from ground truth center (120, 100), radii 22 / 52;
a flat image was rejected. This does not validate performance on a real eye.
The crop-based proposal and whole-frame fallback have now both been run in the
phone diagnostic, but only with the current can-covered setup; those results
are not valid iris-localization evidence. See
[`circular-proposal-result-2026-11-05.json`](../android/iris-camera-probe/circular-proposal-result-2026-11-05.json).

A second synthetic stress case covered roughly the upper 30% of the eye patch
with a dark lid-like region and offset the pupil center by 2 px relative to the
limbus center. The proposal returned center (121, 99), pupil radius 22 px and
outer radius 53 px. This tests tolerance to one simple occlusion pattern only;
it does not establish robustness to real eyelids or gaze-dependent pupil shape.

If the face detector returns no candidate, the live analyzer now scans the
whole 320×180 luma image. On 2026-11-05, this fallback first reported a weak,
implausible annulus with an iris-to-pupil radius ratio of 13.5 on the
can-covered frame. A generous 8:1 maximum ratio filter now rejects that
candidate. A coarser low-resolution scan reduced the observed one-frame
analysis time from about 4.8 s to 3.1 s (single observations, not a controlled
benchmark). The updated run found no candidate and closed normally after 146
capture callbacks. Its dark-scene metrics do not tell us whether the sensor
resolves an uncovered iris. See
[`fullframe-fallback-result-2026-11-05.json`](../android/iris-camera-probe/fullframe-fallback-result-2026-11-05.json).

The updated UI can start an in-memory three-frame diagnostic enrollment and
compare a later candidate code. On the covered device, one attempted sample
had plausible-looking circles but 0% valid phase bits, so it was rejected and
the count stayed 0/3. The app was force-stopped to clear all transient codes;
no image or template was saved. See
[`diagnostic-enrollment-ui-result-2026-11-05.json`](../android/iris-camera-probe/diagnostic-enrollment-ui-result-2026-11-05.json).

The current source now prevents the coarse whole-frame circle fallback from
feeding diagnostic enrollment or comparison. Those actions require either a
generic face-detected eye-pair ROI with a circular proposal inside one of its
heuristic eye boxes, or an explicitly selected manual ROI. The whole-frame
result remains display-only. This reduces one known false-candidate path but
does not make the face detector or circle proposal reliable eye localizers.
Changing a manual ROI clears prior in-memory enrollment codes so samples from
different crops cannot be combined. The source compiled and its manual-ROI
control appeared in an isolated temporary package on 2026-11-05. A center
preview tap mapped to buffer fraction `(0.499, 0.499)`. One IR-off frame's YUV
timestamp matched its capture-result timestamp, but luma p95 was 1 because the
sensor remained covered by the can. The signal gate rejected it before manual
ROI proposal. In a second IR-off session the touch/buffer/screen round-trip
error measured 0 px; accessibility geometry reported a 421×749 view centered
at (211,374) with radius 105.3 px, matching the actual overlay bounds. This
verifies coordinate math, not visually inspected overlay pixels or matcher
processing. No image pixels were saved. See
[`manual-roi-ui-result-2026-11-05.json`](../android/iris-camera-probe/manual-roi-ui-result-2026-11-05.json) and
[`manual-roi-overlay-geometry-result-2026-11-05.json`](../android/iris-camera-probe/manual-roi-overlay-geometry-result-2026-11-05.json).

The current app source keeps image-derived eye/circle geometry and matcher
distance in the app's transient status view rather than Logcat. It does not
write ROI coordinates, phase codes, consensus templates or comparison scores
to files. Operational camera timing and aggregate frame-quality diagnostics
remain available in Logcat; captured YUV is only written to app-private
storage after the explicit **Save one YUV frame** action.

This privacy routing was compiled and packaged on 2026-11-05, but the APK was
not installed and no candidate-bearing frame was run through it. The manual
ROI Logcat message now reports only the preview-transform round-trip error,
and its accessibility description contains no coordinates or radius. The
local status view still displays image-derived diagnostics when explicitly
requested. Build details are recorded in
[`diagnostic-privacy-build-2026-11-05.json`](../android/iris-camera-probe/diagnostic-privacy-build-2026-11-05.json).
The follow-up phone readback found no active camera clients, no registered
biometric sensors or session, and all four LED channels at zero; see
[`phone-safety-readback-2026-11-05.json`](../android/iris-camera-probe/phone-safety-readback-2026-11-05.json).

This is a fail-closed interim gate, not a suitable final ROI strategy for a
dedicated iris camera. Windows' capture component receives eye coordinates
from the authentication layer; no fixed sensor-centered iris ROI or optical
field-of-view measurement has been established for Android. The available
IR-off room frame produced no generic face detection, but it was not a real eye
sample. Once a usable scene is available, inspect the full sensor frame and
measure whether it contains a face, one eye, or neither. The diagnostic now
has a manual preview-tap ROI control for an eye-only view; it maps through the
displayed preview transform and constrains the circular proposal to a centered
square crop. That selection remains unvalidated until actual captures show it
encloses the iris. Keep enrollment/comparison disabled for frames without a
manually selected or face-derived ROI that passes the current signal and
proposal checks.

The host matcher check now also compares one handcrafted generated texture
against a deliberately different generated pattern. Distances were 0.0116 for
the rotated/aligned same pattern, 0.0018 for its clipped version (78.1% bit
overlap), 0.4857 for the distinct pattern, and 0.5557 for the same pattern
without rotation correction. This confirms only those mechanics on toy data;
it is not a representative genuine/impostor distribution and sets no useful
identity threshold. See
[`synthetic-matcher-evaluation-2026-11-05.json`](../android/iris-camera-probe/synthetic-matcher-evaluation-2026-11-05.json).

### Camera2 exposure timing readback

On 2026-11-05, the probe logged the iris camera's advertised exposure range,
sensitivity range and per-frame exposure metadata. Camera2 reports
`MANUAL_SENSOR`, AE modes OFF/ON, exposure range 29,966 ns–1.9636 s and ISO
100–800. In default AE, repeated converged results reported 75.004 ms, ISO
4859, and 75.184 ms frame duration; the ISO result is 6.07× above the
advertised maximum. The probe then requested manual exposure 30 ms, ISO 100
and 33.5 ms frame duration. Repeated results returned 29.996 ms, ISO 100 and
33.442 ms, then AE was restored and the out-of-range result returned.

The source-derived mode uses 70.08 MHz pixel rate, 2100 pixels per line and
1116 lines per frame. That implies 29.966 µs per line, a 29.966 ms 1000-line
exposure and 33.442 ms frame duration; the manual Camera2 results agree to
rounding. This establishes a useful reversible way to reproduce Windows' low
gain timing through Camera2. The probe now uses this baseline by default when
manual sensor control is advertised; **Use AE auto (restore)** remains
available for comparison. A follow-up run confirmed default manual metadata
and both mode switches. It does not prove the sensor registers received those
values or that image quality improved. The sensor stayed under the can, no
frame was saved and no IR was enabled. See
[`camera2-exposure-result-2026-11-05.json`](../android/iris-camera-probe/camera2-exposure-result-2026-11-05.json) and
[`camera2-manual-default-result-2026-11-05.json`](../android/iris-camera-probe/camera2-manual-default-result-2026-11-05.json).

A bounded no-save manual sensitivity sweep then requested ISO 100, 200, 400
and 800 at the fixed 29.996 ms / 33.442 ms timings. Camera2 returned each
requested sensitivity exactly and reported 100% post-RAW boost throughout;
the AE-only ISO 4860 anomaly therefore does not occur on the manual request
path. At ISO 100 the luma p95 was 3, confirming the available scene remained
near black. No image-response or actual analog-gain conclusion can be drawn
from this sweep. The temporary control was removed from the phone and the
camera/LED state was verified clean. See
[`phone-manual-sensitivity-sweep-2026-11-05.json`](../android/iris-camera-probe/phone-manual-sensitivity-sweep-2026-11-05.json).

The one-shot YUV analyze request now sets the same selected exposure controls
as preview. Phone capture-result metadata confirmed both manual values
(29.996 ms / ISO 100 / 33.442 ms) and the AE values (75.004 ms / ISO 4860 /
75.184 ms) propagate to the still request. No YUV image was saved and IR stayed
off. One can-covered AE frame yielded a plausible-looking circle proposal with
56% valid phase bits; this demonstrates that the current geometry heuristic
can produce a false candidate on an unusable scene. A provisional luma-p95
floor of 32 now prevents such low-signal frames from entering geometry,
comparison or in-memory enrollment. It rejected earlier covered frames at p95
3 and 25 in host boundary checks; a later covered phone frame was p95 85 and
produced no candidate, so the floor has not been validated on useful imagery
and remains explicitly uncalibrated. See
[`camera2-still-exposure-result-2026-11-05.json`](../android/iris-camera-probe/camera2-still-exposure-result-2026-11-05.json).

### Camera2 result/buffer identity check (2026-11-05)

A separately signed temporary package opened only iris camera ID 2 and ran
one **Analyze one live frame (no save)** request. Camera2 reported timestamp
source `UNKNOWN`; the `CaptureResult.SENSOR_TIMESTAMP` and `Image.getTimestamp()`
were exactly equal for frame 492. This verifies that the metadata result is
paired with the returned YUV buffer without comparing the sensor clock to app
elapsed realtime. The image stayed in memory and was discarded. Its luma p95
was 1 (p05/p50 0), so the existing provisional quality floor rejected it; it
contains no useful eye/iris quality evidence because the phone remains covered.
No LED/helper was used. The temporary package was force-stopped and removed;
the original probe package was untouched. After teardown the camera service,
camera provider and `mm-qcamera-daemon` were running, with no active camera
clients and all four LED values at zero. See
[`frame-identity-ir-off-result-2026-11-05.json`](../android/iris-camera-probe/frame-identity-ir-off-result-2026-11-05.json).

### Stale probe camera release (2026-11-05)

A fresh ADB readback found that `com.lumia.irisprobe.manualroi` had left iris
camera ID 2 open, although the IR/flash channels were all zero and no biometric
session was registered. The package was force-stopped. CameraService then
reported no active clients and all three camera devices closed; `cameraserver`,
the provider and `mm-qcamera-daemon` remained running. All four IR/flash
brightness values still read zero. No camera or emitter was activated. The
phone-reported clock differs from host UTC, and both values are preserved in
[`camera-client-teardown-2026-11-05.json`](../android/iris-camera-probe/camera-client-teardown-2026-11-05.json).

### Installed Keyguard iris-routing audit (2026-11-05)

Because the pinned SystemUI source checkout was unavailable, I pulled the
installed `/system/system_ext/priv-app/SystemUI/SystemUI.apk` from the phone
(read-only) and inspected its DEX with Android SDK `dexdump`. The deployed
`KeyguardUpdateMonitor$21.<clinit>` switch map assigns cases only to
`BiometricSourceType.FINGERPRINT` and `FACE`. Its
`isUnlockingWithBiometricAllowed(BiometricSourceType)` method returns false
for any other source type. The installed `framework.jar` does define
`BiometricSourceType.IRIS` (ordinal 2), so the missing mapping is in
SystemUI's Keyguard path rather than the source-type enum. SystemUI has
FaceManager and FingerprintManager paths, with no `IrisManager`, `TYPE_IRIS`
or iris callback symbols. Therefore, even after the inert framework
IrisAuthenticator is implemented, this SystemUI build still needs explicit
iris Keyguard integration before unlock can happen. Exact DEX and APK hashes
and this read-only evidence are in
[`android16-framework-iris-audit-2026-11-05.json`](../android/iris-camera-probe/android16-framework-iris-audit-2026-11-05.json).

The same on-device `framework.jar` inspection found that its legacy
`android.hardware.iris.IrisManager` class has no fields or virtual methods;
its sole constructor only calls `Object.<init>()` and retains neither the
context nor `IIrisService`. The platform does contain an `IRIS` value in
`BiometricSourceType`, but there is no usable framework-side client API. The
unlock path therefore needs both a real framework client/service contract and
Keyguard's iris callback/listening flow; adding only the sensor registration
or an enum branch is insufficient. The framework JAR and DEX hashes are
recorded in the same audit JSON.

The installed `IIrisService` Binder exposes only `registerAuthenticators(List)`;
it has no sensor-authentication or enrollment operations. `services.jar`
contains the no-op `IrisAuthenticator` seen in the pinned source audit:
`isHardwareDetected()` and `hasEnrolledTemplates()` return false,
`prepareForAuthentication()`, `startPreparedClient()` and cancellation are
empty, and the authenticator ID is zero. Thus the working design needs a real
sensor authenticator, a framework-internal way for Keyguard to request and
receive its session, and the SystemUI iris modality route. Binary hashes and
method inspection are recorded in the audit JSON.

### Keyguard session API boundary

The installed `IBiometricService` exposes generic `authenticate(...,
PromptInfo)` and `cancelAuthentication(...)`, plus registration and status
methods; it has no `authenticateForKeyguard` operation. The pinned
`BiometricService` explicitly accepts Convenience sensor registration for
framework lockscreen state while warning that registration does not make that
sensor usable through `android.hardware.biometrics` APIs. The generic
`authenticate(PromptInfo)` path is the ordinary prompt path, so using it as a
Class 1 shortcut is not supported by the reviewed contract. The local patches
now add a privileged Keyguard-only request/cancel/result path that keeps
Convenience unavailable to apps, plus a KeyguardUpdateMonitor result sink and a local lifecycle hook in patch
0007. The request path currently fails closed with hardware unavailable. The
new hook is source-only and has not been exercised on a built framework.
`AuthSession.onAuthenticationSucceeded()`
does call `StatusBarService.onBiometricAuthenticated()`, but this is the
BiometricPrompt callback/UI flow and does not replace Keyguard's modality
callback. In the pinned Lineage source, `KeyguardUpdateMonitor` subscribes to
`FaceAuthenticationListener` status updates and routes success, failure,
acquired, error, lockout and enrollment changes to Keyguard. The pinned
`FaceService` is the closer model: its modality-specific `authenticate()`
method schedules through a sensor provider, while `prepareForAuthentication()`
handles BiometricPrompt. Patch 0007 supplies an initial enrollment-aware lifecycle/listener that
invokes the new methods and cancels when Keyguard state changes. It still needs
build/runtime validation and correct camera serialization with any face-auth
session. Keep the generic
`IBiometricAuthenticator` registration separate and public `PromptInfo`
filtering unchanged. The pinned `IIrisService` was registration-only before
the local extension; the installed phone still exposes only that older
Binder. This boundary and the installed Binder method list are recorded in
the audit JSON.

A source cross-check tightened that conclusion: AOSP defines
`BIOMETRIC_CONVENIENCE` as a DeviceConfig strength-adjustment value and says it
is invalid for public biometric APIs. `BiometricService.Utils` computes the
public requested strength by masking with `BIOMETRIC_WEAK`, so the normal
`PromptInfo`/`PreAuthInfo` path cannot select a Class 1 sensor. Android allows
Class 1 for lockscreen authentication, so the implementation needs a
privileged Keyguard-only iris request while keeping that sensor excluded from
app APIs. The pinned `FaceService` provides the closer integration model: a
direct modality-specific `authenticate()` method schedules through its sensor
provider, while `prepareForAuthentication()` handles BiometricPrompt. The
local IrisService contract enforces Keyguard caller identity but currently
has no provider and always reports unavailable; SystemUI still lacks the
enrollment-aware listener. Keep the generic `IBiometricAuthenticator`
registration separate and public `PromptInfo` strength filtering unchanged.
See AOSP's [BiometricManager](https://android.googlesource.com/platform/frameworks/base/+/master/core/java/android/hardware/biometrics/BiometricManager.java), [biometric Utils](https://android.googlesource.com/platform/frameworks/base/+/8e256e238c02/services/core/java/com/android/server/biometrics/Utils.java), [pinned FaceService](https://github.com/LineageOS/android_frameworks_base/blob/daf2b33fac918a464f6f7193214b27d164d39bea/services/core/java/com/android/server/biometrics/sensors/face/FaceService.java), [pinned FaceManager](https://github.com/LineageOS/android_frameworks_base/blob/daf2b33fac918a464f6f7193214b27d164d39bea/core/java/android/hardware/face/FaceManager.java), [pinned KeyguardUpdateMonitor](https://github.com/LineageOS/android_frameworks_base/blob/daf2b33fac918a464f6f7193214b27d164d39bea/packages/SystemUI/src/com/android/keyguard/KeyguardUpdateMonitor.java), and [biometric class overview](https://source.android.com/docs/security/features/biometric).

### Local framework continuation (2026-11-05)

Android Class 1 is not an unrestricted unlock shortcut. The current AOSP
biometric guidance permits Class 1 on the lockscreen but bars it from
BiometricPrompt and keystore authentication. The Android CDD still requires
FAR below 0.002%, rate limiting after five false trials, TEE-backed credential
confirmation before enrollment, complete per-user data deletion, policy
handling, and periodic primary-credential fallback. See the [AOSP biometric
security guide](https://source.android.com/docs/security/features/biometric)
and the [Android CDD sensor requirements](https://android.googlesource.com/platform/compatibility/cdd/+/8e8a1dc3a488c0fa41471855ad29539856d7bab7/7_hardware-compatibility/7_3_sensors.md).
This phone's crypto state is `unsupported`, and the app's matcher has no
validated error rates or liveness performance. We therefore cannot connect
its current diagnostic comparison to a screen-unlock success callback.

The local patch set now includes a hidden Keyguard-only request/cancel/result
contract (`0005`), the per-user enrollment query (`0006`), and an initial
Keyguard lifecycle bridge (`0007`). The service still intentionally returns
`BIOMETRIC_ERROR_HW_UNAVAILABLE`; there is no working camera authenticator.
Do not mistake the source plumbing for a working or security-qualified
unlock path. Patch 0007 has only been applied in a disposable source check; it
has not been compiled or installed. Its review is recorded in
[`framework-iris-keyguard-lifecycle-check-2026-11-05.json`](../android/patches/framework-iris-keyguard-lifecycle-check-2026-11-05.json).

Source review found that patches 0005 and 0006 described the new `IrisManager`
request, callback and enrollment-query APIs as internal but omitted some
`@hide` annotations; the new AIDL receiver also lacked `@hide`. I added the
missing annotations so the Keyguard-only contract stays out of SDK stubs.
Patches 0003-0006 now apply in order to a disposable worktree at the pinned
Lineage revision `daf2b33fac918a464f6f7193214b27d164d39bea`, and the combined
diff passes `git diff --check`; the check is recorded in
[`framework-iris-patch-sequence-check-2026-11-05.json`](../android/patches/framework-iris-patch-sequence-check-2026-11-05.json).
This validates patch context and ordering, not Java/AIDL compilation. The
framework patches have not been compiled or installed, so API-surface
behavior still needs a source build check.

Reviewing the pinned modern SystemUI source shows that face requests are
started by `SystemUIDeviceEntryFaceAuthInteractor`, a `CoreStartable` whose
wake and bouncer listeners are gated by face enrollment and availability. Its
biometric settings and allowed-modality interactors model face and fingerprint
only. Any iris integration must add an explicit enrollment/enablement state,
serialize camera ownership with face/front-camera use, and cancel on sleep,
user switch, and bouncer transitions. A wake-only unconditional start would
both request an unconfigured sensor and risk competing for the shared CSIPHY2.

The existing `SystemServiceRegistry` already constructs `IrisManager` from the
context and `IIrisService`; no additional registry patch is needed. The phone
itself remains on an older build where that manager has no methods and the
`iris` service is absent. Source patch dry-runs do not build or install the
framework. There is no real enrolled template, matcher, lockout policy, or
trusted camera-to-match path yet, so the work should stay at service and
lifecycle plumbing until those prerequisites exist.

The request authorization check matches the pinned `Utils.isKeyguard()`
contract: the caller must hold `USE_BIOMETRIC_INTERNAL`, and its package must
match the configured Keyguard component. `SystemServiceRegistry` supplies the
outer context to `IrisManager`, so the proposed SystemUI client reports its
own package for that check. The pinned SystemUI manifest already requests
`USE_BIOMETRIC_INTERNAL`, and the patched `KeyguardUpdateMonitor` routes the
generic `TYPE_IRIS` callback to `BiometricSourceType.IRIS`. No extra manifest
permission or result-type mapping is needed. The remaining source integration is the enrolled-template/backend path and
runtime validation that lifecycle cancellation prevents concurrent use of the
shared front-camera/iris CSI receiver.

The pinned `BiometricManager.hasEnrolledBiometrics(userId)` is not suitable as
the iris-enabled gate: AuthService forwards to BiometricService, which returns
true if *any* registered sensor has templates. With a fingerprint or face
enrollment, that would incorrectly permit an iris request. The separate
`BiometricManager.getEnrollmentStatus()` map is also currently limited to
face and fingerprint in `BiometricModality` and AuthService. The iris backend
must expose per-sensor enrollment state from its own per-user template store;
until then Keyguard must not infer iris enrollment from either aggregate API.
