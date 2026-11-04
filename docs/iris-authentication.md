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
`UseFlashOutOfFrame`. It is not the iris matcher.

The sensor's strobe capability is zero (`0x1a02` reads zero and DCC block 5 has
no override). Windows therefore does not program the sensor STROBE registers
for this sensor. Per-frame illumination is a host-side flash-driver request;
the exact Windows call timing and ioctl sequence have not yet been recovered.
The sensor-strobe-to-PMIC wiring hypothesis is withdrawn. Do not set the PMIC
LED to hardware-strobe mode for the iris.

The Windows flash driver's current and cooldown checks are undocumented in
units and have not been validated as eye-safety limits. Linux `torch_0`
brightness 14 (hardware current code 1) was observed as a faint red glow, but
that observation does not establish an eye-safe exposure.

The new one-frame Android YUV capture is **not** the original Windows Hello
enrollment or authentication algorithm. It only checks the camera-to-frame
stage. The Lumia-specific static analysis recovered capture controls and
per-frame flash requests from `CameraAuthentication.dll`, but no iris matcher,
template format, or enrollment call sequence. Microsoft's general Windows
Hello documentation describes an enrollment profile derived from sensor data
and stored as an encrypted, device-local template; that is useful architectural
context, but it does not prove the exact Lumia Windows 10 Mobile implementation
or reveal its matcher. The [Windows Hello FAQ](https://learn.microsoft.com/en-us/windows/security/identity-protection/hello-for-business/hello-faq)
and [Windows Biometric Framework driver guide](https://learn.microsoft.com/en-us/windows-hardware/drivers/biometric/)
cover that general model.

## Current illumination implementation

The probe's IR button sends one root-localhost request after the first camera
result. The helper turns `torch_0` on at brightness 14 for one second, then
forces it off. This confirms control and visible output only; the pulse is not
synchronized to the exposure that produced a frame. Keep this button out of
normal capture/authentication and do not repeat pulses while a person is
looking into the emitter.

Before per-frame synchronization:

1. Recover the Windows flash request path and pulse scheduling semantics from
   `CameraAuthentication.dll` and `qccamflashtertiary8994.sys`, including the
   relationship between a frame timestamp, exposure duration, and LED request.
2. Trace the Android camera/PMIC flash path for `torch_0`. Linux's LED class
   brightness write is not a frame-synchronized interface. Check whether the
   camera HAL can issue an IR-only flash request with a bounded timeout and an
   unconditional off path; otherwise add a dedicated kernel/HAL interface
   driven by camera frame timing, not by a UI timer.
3. Measure a clean frame with controlled illumination and exposure. Confirm
   the pulse falls inside that frame's exposure and is off on cancellation,
   timeout, camera close, service death, suspend and error.
4. Validate thermal limits and eye-safety independently before enabling
   repeated pulses or use near a face.

The sensor strobe path is not an alternative: it is unsupported by the
measured sensor capability. A userspace loop around completed-frame callbacks
would pulse late and cannot be treated as synchronized.

## Enrollment and lock-screen authentication

The current Android 16 system exposes the framework `IBiometricService`, but
read-only service and VINTF inspection found no biometric HAL service. The
probe app is not enrolled with Android and cannot unlock the device.

The next gates are:

1. Complete stable RAW/YUV frame delivery, correct orientation/geometry,
   controlled exposure and synchronized IR. Add iris/eye localization and
   quality feedback for a diagnostic enrollment screen.
2. Select and evaluate an iris matcher, including repeatability, false-match
   rates, presentation attacks and liveness. Store enrollment templates per
   Android user; do not put raw frames or templates in a normal app's shared
   storage.
3. Choose and implement the framework route only after the capture/matcher
   evidence exists. Android 16's `hardware/interfaces/biometrics` tree has
   Face and Fingerprint AIDL HALs, but no Iris AIDL HAL. The framework still
   has `TYPE_IRIS`, an `IrisService` registration bridge for configured legacy
   sensors, and `IrisAuthenticator`; however, the Android 16
   `BiometricService` authentication dispatcher logs `Iris unsupported` rather
   than starting iris authentication. So a legacy iris registration alone
   does not provide a functioning lock-screen path. Face AIDL is an available
   interface, but its IR sensor type describes infrared face hardware and
   does not make an iris matcher or make iris data semantically equivalent to
   face recognition. Any route needs enrollment, authentication, removal,
   active-user handling, cancellation, lockout, authenticator ID and
   hardware-authentication-token handling.
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
there is no enrollment or matcher.

The phone exposes Android's framework `IBiometricService`, but its service
inventory and vendor VINTF manifests contain no Face or iris HAL. Android 16
has no Iris AIDL HAL. Its framework retains an iris registration bridge for
legacy configured sensors, while the general authentication dispatcher still
marks iris unsupported. The Face AIDL interface is available, but
`FaceSensorType.IR` means infrared face sensor, not iris. Therefore the next
system step is to inspect this exact Lineage build's framework configuration
and decide whether to implement the missing iris dispatcher/service plumbing
or deliberately adapt through Face AIDL with accurate modality and UI behavior.
Either route needs service/VINTF registration, SELinux policy, product
packaging, enrollment, authentication, enumeration/removal, active-user
switching, cancellation, lockout, and authenticator-ID lifecycle. Enrollment
must validate the framework's hardware-authentication token (HAT);
authentication success may only return a HAT for a sensor that qualifies as
strong. A weaker sensor must return a null HAT.

The implementation order is:

1. Obtain stable raw captures and determine whether the sensor optics and
   current illumination/exposure can produce a repeatable iris texture. Fix
   the green saved-image overlay independently of the known magenta room light.
2. Implement offline eye/iris localization and matching, measure false accepts
   and rejects across consented multi-session samples, and test presentation
   attacks. Keep the diagnostic matcher outside Android's unlock path until
   results are measured.
3. After offline matching is credible, prototype the system-service route on
   a local build. First check whether the Lineage 23.2 branch has a supported
   way to complete iris authentication through `TYPE_IRIS`; Android 16's
   dispatcher currently reports it unsupported. If framework changes are
   needed, keep them explicit and reviewable. Treat Face AIDL only as a
   separate design option, because its IR sensor type is defined for face
   hardware. Do not claim `STRONG`, return fabricated HATs, or expose it to
   app authentication. Enrollment and authentication must use real framework
   callbacks, not a mock-success path.
4. Integrate Keyguard/Settings and enable enrollment only after matching,
   liveness, lockout, user isolation, cancellation, and cleanup work. Evaluate
   whether Class 1 convenience unlock is supportable; Class 2 and 3 require a
   secure biometric pipeline, and Android requires spoof-resistance testing
   for each class.

The Windows driver evidence describes capture and per-frame flash requests,
not a recovered iris-matching algorithm. The measured sensor reports no strobe
capability, so its hardware strobe is unavailable. The current `torch_0`
one-second test is not frame-synchronized and cannot be reused for
authentication illumination. Synchronized, bounded illumination with a
verified off path remains a prerequisite to recognition-quality capture.

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
