# Lumia iris unlock development roadmap

This roadmap is based on the local `main` state at commit `e1eae9f` and the
phone/build records currently in the repository. It describes the work needed
to reach Android screen unlock; it does not claim that enrollment, matching,
or authentication already works.

Last reviewed: 2026-11-07, local baseline `e1eae9f`; includes the upstream
`lumia-iris-notes` correction at `bd2fcdd`.

## Ordered work

## Remaining-work checklist at a glance

| Order | What remains | How to do it | Evidence required to pass |
| --- | --- | --- | --- |
| 1 (parallel feasibility gate) | Prove Android can protect templates and authenticate a match | Resolve the missing hardware Keymaster/KeyMint module and signed QSEE app, then verify that the pair runs with Cityman's TrustZone. Check credential-bound key security level and hardware-enforced authentication; separately prove how a match becomes an authenticated, replay-resistant result accepted by Android. If the platform cannot support this, stop before enrolling templates or connecting success to Keyguard. | A hardware-backed credential-bound key and a trusted, replay-resistant biometric success path verified on this ROM/device. Current evidence is software-backed only; this gate is open and blocks a secure unlock. See the [`trust-state snapshot`](android/keyinfo-probe/current-device-trust-readback-2026-11-07.json) and [`Keymaster module audit`](android/keyinfo-probe/keymaster-runtime-module-audit-2026-11-07.json). |
| 2 | Explain why valid RAW10 frames show no useful scene detail | With IR off, capture repeated frames of a well-lit, textured diffuse non-person scene plus a flat-field reference. Run `tools/iris-capture/raw10_diagnostics.py` before Windows crop/split; compare black offset, row/column noise, packing, stride and scene response. Keep pixels in local temporary storage. | Repeatable scene structure above the noise floor, with RAW packing, geometry, orientation and normalization explained. The existing 300 ms / ISO 800 capture has p95 559/1023 and maximum 871 without clipping, but shows only a broad gradient and fine grain. |
| 3 | Recover Windows' frame and biometric input contract | Continue static FFU analysis of `CameraAuthentication.dll`, `DeltaIrisEngineAdapter.dll` and `iris_mobile_v2.WindowsPhone.dll`. First resolve the revalidated `irm2_init_identification` stack-argument discrepancy and verify the actual paired engine/adapter version. Then trace BIR payload layout, pixel format, enrollment/identification calls, template format, quality/liveness outputs, errors and result handling. | A field-by-field input format and call/lifecycle map grounded in disassembly or runtime evidence, with the actual initialization ABI established. Do not assume Camera2 YUV equals the Windows payload. |
| 4 | Recover the synchronized IR path and establish its safety basis | Trace the Windows KMD flash request and CCI GPIO queue to the physical board output; trace Android camera/PMIC scheduling. Identify route and timing without guessed writes. Obtain calibrated optical/thermal measurements and qualified exposure limits before eye-facing operation. | Proven emitter route and frame timing, independently validated exposure limits, and verified off behavior on cancel/error/timeout. Until then, keep IR off for image work and do not enroll from eye-facing IR captures. |
| 5 | Build eye localization and a validated matcher | Only after geometry and permitted capture conditions are understood, implement quality rejection, segmentation, enrollment and matching. Evaluate consented representative samples with held-out false-accept/false-reject and presentation-attack tests. | Repeatable matching, calibrated thresholds, quality/liveness rejection and documented accuracy. The current Log-Gabor view is display-only. |
| 6 | Implement the Android authenticator and connect Keyguard | Build the pinned LineageOS/device tree; implement a privileged authenticator with exclusive camera ID 2 ownership, front-camera arbitration, per-user lifecycle, cancellation, timeout, lockout and trusted success handling. Preserve existing rear/front slots. | The installed service is discoverable by Android, fails closed correctly, owns/releases camera resources reliably, and accepts only the trusted match result. |
| 7 | Validate end-to-end lock-screen behavior | After the image, illumination, matcher, security and framework gates pass, test enrollment/removal, match/non-match, poor quality/spoof, cancel, timeout, camera conflict, lockout, user switch, credential fallback, reboot and cleanup. | Repeated unlock only on trusted matches; every failure stays locked; no camera or LED resource leaks. |

The security feasibility gate (item 1) must run in parallel with image and
Windows-contract work, and must pass before templates or a Keyguard success
path are enabled. If the device cannot provide a trusted biometric result and
protected template path, the current Android 16 build cannot safely offer
production iris unlock even if the camera and matcher work.

### 1. Build and correct the current one-frame camera probe

**Why first:** The last capture-start pulse delivered a YUV frame, but CPU
analysis ran on the Camera2 callback handler. The capture-result callback was
delayed by about 7 seconds. A separate analysis-thread refactor was needed to
keep image work off that handler.

**How:** Build the app with `android/iris-camera-probe/build.sh` and an
isolated temporary manifest/package. Check the worker/latch paths for frame arrival, capture
failure, camera close, timeout, and image release. Confirm the capture result
is delivered promptly while analysis runs off the camera handler. Start with
an IR-off preview/capture on camera ID 2; only use the bounded diffuse-target
IR diagnostic if it is needed to verify the existing pulse behavior.

**Done when:** Build succeeds; one IR-off YUV frame and its capture result are
associated without delaying Camera2 callbacks; teardown leaves no camera
client, helper, or nonzero LED channel. Any emitter run must also leave all
channels off. Camera timestamp source is currently `UNKNOWN`, so this test
cannot establish optical timing.

**Progress:** The refactor now builds and was exercised on camera ID 2 with IR
off. A 1920×1080 YUV image and matching capture result arrived about 1.3 ms
apart; the analyzer worker completion and input-buffer close were observed.
The camera was closed, the APK removed, no clients remained, and all four
LEDs read 0. Async failure/cancel paths compile but have not been forced on
the phone. See
[`phone-analysis-thread-ir-off-2026-11-07.json`](android/iris-camera-probe/phone-analysis-thread-ir-off-2026-11-07.json).

### 2. Get useful image detail and establish the pixel geometry

**Why:** The saved real RAW10 frame decoded correctly but was nearly black and
showed no eye detail. The converter's 0°/90° settings only change split axis
and view order; they do not rotate the pixels, so they did not test sensor
orientation.

**How:** Use the app-private RAW10 save path on a well-lit diffuse scene with
IR off, retrieve the image and metadata using
`tools/iris-capture/pull_and_convert_raw10.py`, and compare row packing,
normalization, crop, orientation, and Windows two-view geometry. First verify
with synthetic fixtures and static Windows format analysis. Save only the
minimum local artifacts needed for repeatable analysis; do not put private
sensor profiles, the FFU, or biometric samples in Git.

**Done when:** Multiple captures reproduce the same geometry and useful
contrast, and the Windows-derived conversion/split is explained against the
actual RAW format. Eye localization and quality rejection must work on
representative frames before matcher work proceeds.

**Progress:** Reprocessed the existing private RAW10 file with engine
orientation inputs 0 and 90. The cropped full-frame outputs have identical
SHA-256 hashes; the tool changes only split axis/order. The file remains too
dark for eye detail. Updated converter help and records to make clear that
this does not test physical sensor rotation. See
[`raw10 orientation-mode review`](android/iris-camera-probe/raw10-orientation-mode-review-2026-11-07.json).

A second IR-off RAW10 frame under auto exposure raised p95 from 19 to 52, but
the ISO result was 1042 (above the advertised maximum 800) and visual review
still showed only fine grain. It does not provide eye detail or validate AE.
The temporary package was removed and the phone is idle with all four LEDs
off. See
[`AE RAW10 follow-up`](android/iris-camera-probe/phone-raw10-ae-followup-2026-11-07.json).

A third IR-off frame used manual 300 ms / ISO 800; Camera2 returned
299.987 ms / ISO 800. Its 8-bit approximation p95 is 139. A new full-bit-depth
diagnostic found RAW10 p95 559/1023, maximum 871 and no clipped pixels; all
four 2-bit low-field values appear at similar frequencies. The cropped spatial
grid shows a smooth central-bright gradient, but percentile stretching still
reveals no identifiable scene or eye detail. Orientation inputs 0 and 90
produce byte-identical cropped pixels. The frame is not numerically empty, so
the next capture should use a textured, brightly lit diffuse scene and a
flat-field reference to distinguish scene content from sensor shading/noise.
All cameras were closed, the temporary app was removed, ADB returned to shell
UID, and all four LED channels read 0. The pixel file is local under
`/private/tmp`, outside Git. See
[`manual 300 ms / ISO 800 capture`](android/iris-camera-probe/phone-raw10-manual300-iso800-2026-11-07.json).

### 3. Resolve the real IR route and frame timing

**Why:** The one-shot Android `torch_0` test used software brightness writes.
Its ON/OFF acknowledgements do not prove when light reached the sensor. The
Windows CCI GPIO queue path, camera-KMD flash consumer, Cityman LED mapping,
and physical route remain unresolved. The current app pulse is not an
eye-safety validation.

**How:** Continue static FFU analysis: trace IOCTL `0x0023432A` and the
per-frame pulse/current fields through `qccamavs8994.sys`; resolve Windows
CCI queue/output 0, selector, completion, timing scale, and board route from
the driver and authoritative SoC/board data. In Linux, trace the camera/PMIC
flash scheduling interface before proposing code. Do not guess GPIO, pinmux,
register, current, or timing values. Require calibrated optical/thermal
measurement and a qualified safety basis before any eye-directed operation.

**Done when:** The output is proven to be the iris emitter, camera-synchronized
timing is observed independently of software logs, cleanup is verified for
error/cancel/timeout paths, and safe exposure limits are independently
established. Until then, no IR eye capture or enrollment.

### 4. Recover or replace the Windows recognition pipeline

**Why:** The current Log-Gabor implementation is a display/demo prototype.
It has no representative data, calibrated thresholds, or liveness validation.
The Windows ARM32 PE engine depends on Windows/WinBio interfaces and is not
an Android library that can simply be loaded.

**How:** Finish the static ABI and call-flow analysis of
`DeltaIrisEngineAdapter.dll` and `iris_mobile_v2.WindowsPhone.dll`, including
the BIR/vendor-data layout, eye selection, enrollment lifecycle, template
format, quality rejection, liveness, identification result and error paths.
Determine whether a clean native Android implementation can reproduce the
contract or whether a validated replacement algorithm is required. Keep the
matcher outside Keyguard until it has representative, consented test data and
documented false-accept/false-reject and spoof-testing results.

**Done when:** Enrollment and identification produce repeatable results on a
held-out evaluation set, reject poor-quality frames, and have an explicit
liveness and failure policy. A demo similarity score is not a match gate.

### 5. Establish secure enrollment storage and a trusted success signal

**Why:** The tested AndroidKeyStore credential-bound key remained
software-backed. The phone reports `ro.crypto.state=unsupported`; no trusted
iris matcher, protected template store, or authenticated success path is
demonstrated. A camera app cannot safely assert biometric success to
Keyguard.

**How:** Determine whether the cityman firmware/TEE can support a real
hardware-backed KeyMint/Keymaster key and trusted iris processing. Inspect
vendor and secure firmware sources and verify with a credential-bound key
whose reported security level and authentication enforcement are hardware
backed. If no such path exists, document that limitation and do not store
usable templates or report matches as trusted. Do not substitute an app-side
boolean, software key, or fabricated Hardware Authentication Token.

**Done when:** Per-user templates are protected by a verified hardware-backed
credential path, and the trusted component returns a correctly bound,
authenticated result with replay protection. If the device cannot provide
this, the production unlock gate remains closed.

### 6. Implement and integrate the Android authenticator

**Why:** Patches 0003–0008 only add source-level discovery and Keyguard
plumbing. There is no camera-backed authenticator, enrollment/removal,
lockout, or camera arbitration; current service behavior intentionally fails
closed with `HW_UNAVAILABLE`.

**How:** Build the pinned LineageOS 23.2 device/framework tree with the patches
and resolve compile/API issues. Implement a privileged authenticator/service
that owns camera ID 2, serializes access against the regular front camera
(both use CSIPHY2), supports cancellation and bounded timeouts, enrolls and
removes per-user templates, enforces lockout/rate limits, and forwards only
trusted results. Preserve normal rear/front camera behavior. Use temporary
boot/install workflows for device validation; do not flash experimental
kernels.

**Done when:** Android reports the iris authenticator correctly, enrollment
state follows the active user, generic and Keyguard requests have correct
fail-closed behavior, camera ownership is exclusive and cleanly released, and
the service builds and runs on the target ROM.

### 7. Validate end-to-end lock-screen behavior

**How:** After image, illumination, matcher, security, and framework gates
pass, test enrollment, successful identification, non-match, spoof/poor
quality, cancellation, timeout, camera conflict, lockout, user switch,
credential fallback, reboot, and removal. Verify Keyguard unlocks only on a
trusted result and that failures never unlock.

**Done when:** Repeated end-to-end trials pass the security and error-path
checks, with measured accuracy and no camera/LED resource leaks. Until all
prior gates pass, keep the feature unavailable to the lock screen.

## Immediate next action

Continue offline with the exact Lumia FFU adapter/engine pair: establish why
`irm2_init_identification` consumes an entry `SP+8` settings pointer while its
callsite leaves a diagnostic format-string pointer there, and verify which
engine binary Windows actually loads. This unresolved initialization ABI can
invalidate rotation and the recovered algorithm path. In parallel, test the
trusted Android biometric feasibility gate. The next camera capture remains a
well-lit textured diffuse non-person scene plus a flat-field reference, IR off;
the latest RAW frame has no useful scene detail. Do not use IR for eye capture
until route, optical timing and exposure safety are independently established.

## Current constraints

- Keep work local unless a push is explicitly requested.
- Keep the FFU and private sensor profile unchanged and out of Git.
- Never stream iris camera ID 2 with the normal front camera.
- Do not point the emitter at a person or eye or use a reflective enclosure.
- Windows driver current/timing guards and Android software pulse cutoffs are
  not validated eye-safety limits.
