# Lumia Iris Camera2 Probe

A minimal Android Camera2 app for the Lumia 950 XL iris bring-up. The HAL can assign the iris different numeric camera IDs across boots, so the app reads camera metadata and selects the unique front-facing 1920×1088 sensor, then opens only that ID. If there is no unique match, it refuses to open a camera. The preview keeps the sensor aspect ratio and has a **Rotate +90°** control for adjusting the provisional mount angle. The screen and logcat show the selected ID, stream size, open/configuration errors, and capture-result callback counts.

The **IR + analyze** button is disabled until a capture-result callback arrives and is available once per app session. It asks a root-only localhost helper to set torch_0 brightness 14 (the lowest previously measured nonzero hardware level), requests one YUV frame, and sends `STOP` when that capture's result callback arrives after sensor exposure, without waiting for YUV delivery or CPU analysis. The buffer is still analyzed in memory and discarded; it is not saved to app storage. Capture failure, reader failure, activity close, and an 850 ms app timeout also release the helper, which has an independent one-second hard software maximum. A bounded phone run with a fake brightness file verified this order without enabling a physical LED: `STOP` was requested about 3 ms after the capture-result callback and about 1 ms before the YUV callback; the helper wrote the fake level back to zero. This verifies software ordering, not the physical LED edge or optical exposure overlap. Previous physical runs provide separate request/result/buffer timestamp evidence, but the sensor clock is unknown and optical timing remains unmeasured. This is not biometric authentication or a validated eye-safety level. Never aim the emitter at a person or eyes. Use only with a diffuse target and no one in the reflected path. **Do not use IR while the phone is covered by the metal can or any reflective enclosure.** The app cannot write the LED sysfs node directly. For a hardware test, start the helper over adb:

```sh
adb root
adb push iris-torch-server.sh /data/local/tmp/iris-torch-server.sh
adb shell chmod 700 /data/local/tmp/iris-torch-server.sh
adb shell 'nohup sh /data/local/tmp/iris-torch-server.sh >/data/local/tmp/iris-torch-server.log 2>&1 </dev/null &'
```

The helper binds only to `127.0.0.1`, rejects all commands except `PULSE`, writes brightness 14 and replies `ON`, then waits for `STOP` for at most one second. It writes 0 and replies `OFF` when stopped, disconnected or timed out. No background watchdog process is needed; its exit/signal trap also writes 0. It is temporary and stops when the phone reboots. Check `/sys/class/leds/led:torch_0/brightness` is `0` after use. Do not use the sensor-strobe path. The software helper's one-second bound is not an eye-safety limit.

For a future safe, uncovered-target run, the app logs elapsed-realtime
timestamps immediately before sending `PULSE` and `STOP`, when it receives
`ON` and `OFF`, when it submits the one-frame request, when the capture-result
callback arrives, and when the YUV buffer arrives. It also logs the buffer timestamp and sensor timestamp source,
exposure duration and frame duration. The phone's iris camera currently
reports `SENSOR_INFO_TIMESTAMP_SOURCE_UNKNOWN`, so the sensor timestamp must
not be compared with app elapsed-realtime values. The analyzer instead checks
that the buffer timestamp equals its `CaptureResult.SENSOR_TIMESTAMP` and that
the request and buffer callback occurred between helper ON and STOP. Android
documents that result and buffer timestamps are identical for the same
capture ([Camera2 reference](https://developer.android.com/reference/android/hardware/camera2/CaptureResult#SENSOR_TIMESTAMP)).
This establishes frame identity and transaction order, not optical LED timing;
the helper events do not measure optical turn-on or turn-off latency.

To check capture-result/YUV timestamp matching after either **Analyze one live
frame** (IR remains off) or a later permitted emitter run, without reading any
frame data:

```sh
adb logcat -d -s LumiaIrisProbe:I | python3 tools/analyze_iris_pulse_timing.py
```

The analyzer reports result/YUV timestamp matches for both IR-off and IR-on
one-frame captures. When pulse logs are present, it also checks request and
image-callback ordering against helper acknowledgements. With `REALTIME`
timestamps it reports a possible first-row exposure overlap; with the phone's
current `UNKNOWN` source it avoids cross-clock subtraction. Neither mode
proves optical overlap.

The app has only an experimental, in-memory diagnostic enrollment and does not enroll an Android biometric or unlock Android. Framework integration requires a supported authenticator service and security review; see [`docs/iris-authentication.md`](../../docs/iris-authentication.md).

When the iris preview session is open, **Save one YUV frame** requests one
`YUV_420_888` still output and writes a packed I420 frame plus a small JSON
metadata sidecar to the app's private internal files directory. The button is
one-shot per app session; the capture has a five-second timeout. It does not
turn on the IR emitter. Packing honors each plane's row/pixel stride and
`Image.getCropRect()`; the sidecar records the crop origin, source buffer
dimensions and output dimensions. Live luma analysis uses the same crop origin
so detector and ROI coordinates refer to the pixels actually analyzed. The
frame is not an enrollment template and is not uploaded or written to shared
storage. Camera2 metadata identifies the sensor orientation; the pixel buffer
itself remains in sensor orientation. On launch,
the probe reports aggregate Y/U/V means, spread and ranges plus luma
percentiles, horizontal/vertical mean absolute gradients, clipping fractions,
and an 8×6 grid's local standard-deviation range for the latest private frame.
These spatial measurements help distinguish a nearly uniform stream from one
carrying image detail; they do not identify an iris, assess matching quality,
display pixels, or export frame data. The summary runs with the camera closed
and does not request camera permission; permission is requested only after
**Open iris** is selected. On saved frames, the generic detector summary reports
only whether it proposed a face-derived eye region, without showing coordinates.
It also reports whether the display-only whole-frame circle heuristic found a
candidate; that fallback never feeds enrollment or comparison.
The 2026-11-05 saved-frame analysis stayed on the phone; see
[`saved-frame-on-device-analysis-2026-11-05.json`](saved-frame-on-device-analysis-2026-11-05.json).
The probe also downsamples luma in memory, rotates it using the sensor
orientation, and runs Android's generic frontal-face detector to report at
most one coarse face candidate and eye-pair midpoint. It does not identify an
iris or save/export the downsample. A negative result is inconclusive, notably
for dark, sideways, occluded, or non-face scenes.

With the iris preview open, **Analyze one live frame (no save)** examines only
the next Y plane in memory, reports any coarse face/eye-pair estimate and maps
two heuristic eye crop boxes back into sensor coordinates, then discards the
frame. Image-derived geometry and comparison diagnostics are shown only in
the app's status view; they are not written to Logcat or files. The phase code
and consensus remain transient in process memory. The boxes are approximate
search regions inferred from Android's
generic face detector. If the detector returns a face, the one-frame path
searches each eye box for circular pupil and limbus edges, runs the phase coder
on the proposed annulus, reports candidate radii/edge strengths/valid-bit
fraction, then discards the code and frame. These are unvalidated proposals,
not pupil or iris segmentation, matching, or identity decisions. This
operation does not enable IR, store pixels, or enroll a template.
One-frame analysis and YUV saving are mutually exclusive, and either blocks
the IR pulse button until the frame operation completes or times out.
Both one-frame request paths now explicitly carry the currently selected
exposure mode. In the default manual mode, that is AE off, 30 ms exposure,
ISO 100, and 33.5 ms frame duration; choosing **Use AE auto (restore)** makes
one-frame requests use AE as well. Capture-result metadata for each one-frame
request is logged separately from repeating-preview results. Manual and AE
one-frame paths were checked on the phone on 2026-11-05 without saving image
data or enabling IR; see
[`camera2-still-exposure-result-2026-11-05.json`](camera2-still-exposure-result-2026-11-05.json).
The crop-aware live-frame path was separately exercised on 2026-11-05: one
IR-off frame from camera 2 had a full 1920×1080 crop and an exactly matching
Camera2 result timestamp, but its luma p95 was 3 and it was rejected before
ROI analysis. No pixels were saved; see
[`phone-crop-path-result-2026-11-05.json`](phone-crop-path-result-2026-11-05.json).
One AE-auto IR-off frame later reached luma p95 142 and matched its Camera2
result timestamp, but reported ISO 4860 against the advertised maximum of 800.
The instrumented result reported post-RAW sensitivity boost 100%, the only
advertised value, so ISP digital boost does not explain the high ISO. The
open-source HAL copies vendor sensor sensitivity directly into Camera2 and
maps ISP digital gain separately. The evidence points to an upstream vendor
sensitivity metadata or gain-scaling issue; it does not reveal the actual
analog gain. The frame produced no face/eye ROI; a whole-frame contrast
proposal remained display-only. See
[`phone-ae-quality-result-2026-11-05.json`](phone-ae-quality-result-2026-11-05.json).
A follow-up manual sensitivity sweep requested ISO 100, 200, 400, and 800 at
fixed 30 ms exposure. Each Camera2 result reported the matching requested ISO
and 100% post-RAW boost, confirming the anomaly is in the AE result path. The
available scene was near black (ISO 100 p95=3), so this did not establish
image response or actual analog gain. The temporary diagnostic control and
all four result records are in
[`phone-manual-sensitivity-sweep-2026-11-05.json`](phone-manual-sensitivity-sweep-2026-11-05.json).
The current source, including the range-aware ISO selector, was then built
and opened under a separate temporary package on the phone. Camera2 accepted
ISO 200 after one selector tap and reported ISO 200 while exposure and frame
duration stayed fixed at about 30 ms and 33.44 ms. The temporary package was
removed; all camera clients were closed and all four LED channels read zero.
This verifies request/callback behavior, not physical analog-gain response or
image quality. See
[`phone-current-source-manual-iso-smoke-2026-11-05.json`](phone-current-source-manual-iso-smoke-2026-11-05.json).
The current-source probe now has a separate manual-exposure selector. It
clamps requests to the advertised exposure range and sets frame duration to at
least exposure plus the readout margin, subject to the advertised maximum.
An IR-off phone run returned exposure metadata for 50, 75, 100, 200 and
300 ms. At 300 ms / ISO 800, one no-save YUV analysis reached luma p95=47,
above the provisional signal floor, but still found no face-derived eye ROI.
No image was retained; the temporary package was removed, all cameras closed
and all LED channels read zero. This is evidence that longer exposure and
requested sensitivity raise the captured signal, not that the sensor's analog
gain is calibrated or that the frame contains usable iris detail. See
[`phone-manual-exposure-check-2026-11-05.json`](phone-manual-exposure-check-2026-11-05.json).
The current source also delivered one IR-off YUV frame to the in-memory
analyzer. It was full-crop 1920×1080 with luma p95=2 and 100% of samples at or
below 16, so candidate processing correctly stopped at the provisional low-
signal gate. No pixels were saved, the temporary package was removed, all
camera clients closed, and all four LED channels read zero. See
[`phone-current-source-frame-analysis-2026-11-05.json`](phone-current-source-frame-analysis-2026-11-05.json).
On 2026-11-05, the installed older package again opened only camera 2 and
delivered 190 repeating capture-result callbacks over about 14.5 seconds; the
session closed cleanly and all four emitter channels remained at zero. This
was preview-only. The current local APK could not replace that installation
because its signing certificate differs, so this run does not revalidate the
newer YUV-analysis source. No app data was removed. See
[`phone-preview-recheck-2026-11-05.json`](phone-preview-recheck-2026-11-05.json).
The current APK was then installed under a temporary package name, leaving
the original app intact. One IR-off `YUV_420_888` request on camera 2 delivered
a full-crop 1920×1080 frame; its buffer timestamp exactly matched the
capture-result timestamp. The in-memory analysis returned luma p95=1 and
stopped at the existing provisional signal floor of 32. No pixels were saved,
all four emitter channels remained zero, and the temporary package was removed
after closing the camera. This confirms frame delivery and timestamp/crop
handling, but the scene still provides too little signal to assess iris
localization or matcher behavior. See
[`phone-current-source-yuv-recheck-2026-11-05.json`](phone-current-source-yuv-recheck-2026-11-05.json).
After the owner placed the phone in a white thin box, one minimum-level
`torch_0` pulse was tested with the current-source in-memory analysis path.
The single 1920×1080 YUV frame arrived 1.13 ms before the app's STOP request;
its buffer timestamp exactly matched the Camera2 capture-result timestamp.
Luma p95 was 212 (versus 1 in the previous IR-off capture), but no face/eye
pair ROI was found. A whole-frame contrast proposal remained display-only and
is not iris localization. The phone was closed and the temporary package,
helper and helper files were removed; camera clients were zero and all four
LED channels read zero. The box's reflectance and optical output were not
measured, and this is not eye-safety validation. See
[`phone-min-current-ir-analysis-2026-11-05.json`](phone-min-current-ir-analysis-2026-11-05.json).
The diagnostic now skips circle proposals and enrollment/comparison when the
frame's luma 95th percentile is below 32. This provisional floor rejects the
two earlier can-covered frames (p95 3 and 25); it is not calibrated. A later
covered AE frame reached p95 85 and produced no proposal, so an uncovered
capture is still needed to establish useful image quality and tune this gate.

`LogGaborIrisCodePrototype` is an isolated experiment that applies a
one-dimensional log-Gabor filter to each normalized annular row and encodes
response phase bits. Synthetic checks cover angular rotation alignment,
clipped-sector masking, low-overlap and flat-image rejection, separation from
one deliberately different generated texture, and three-sample consensus
enrollment. The matcher still assumes supplied concentric geometry, uses a simplified mask, has no validated
match threshold, and must not be treated as a completed or secure iris matcher.
Its `DiagnosticEnrollment` helper combines three compatible frame codes into
a rotation-aligned majority consensus in memory. The app exposes an explicit
three-frame diagnostic collection and later comparison action; it persists
nothing, and reports distance/overlap without any threshold or authentication
decision. Diagnostic phase and mask arrays are explicitly overwritten when
enrollment is reset, completes, the ROI changes, or the preview closes; the
current frame's luma and downsample scratch arrays are overwritten after
analysis, including error exits. This is best-effort application-memory
cleanup, not a protected memory or trusted biometric path. The log-Gabor
encoder and consensus builder also overwrite their short-lived FFT and
alignment scratch arrays on success and clear partial output arrays on errors;
see [`matcher-scratch-cleanup-result-2026-11-05.json`](matcher-scratch-cleanup-result-2026-11-05.json).
**Current source change:** three-frame enrollment
and comparison require either a detected face-derived eye-pair ROI with a
circular-boundary proposal inside one of its eye boxes, or a selected manual
ROI. The whole-frame circular-contrast fallback is display-only and cannot
supply a matcher code. If the generic face detector cannot find a face,
enrollment needs an explicit manual ROI selection instead of searching
unrelated scene structure.
**Select eye ROI (tap preview)** provides
an alternative for the dedicated sensor: tap the apparent iris center. The
app maps the touch through the preview transform, draws the selected area, and
searches a centered square crop whose width is half the smaller YUV dimension.
Changing the selection clears any transient enrollment. A manual tap is only a
user-selected crop; it does not prove that an iris is present. The detected
eye boxes and circular contours also remain unvalidated heuristics and do not
establish pupil/limbus segmentation. The source compiled and the UI label
appeared in an isolated temporary package on 2026-11-05. A center tap mapped to
preview-buffer fraction (0.499, 0.499). One IR-off YUV frame arrived with the
matching capture-result timestamp, but luma p95 was 1 because the sensor was
covered; the signal gate rejected it before ROI proposal. Overlay alignment
was separately checked without saving a screenshot: touch/buffer/screen
round-trip error was 0 px, and the ROI center/radius matched the rotated view
bounds. Matcher processing remains unverified. No pixels were saved. See
[`manual-roi-ui-result-2026-11-05.json`](manual-roi-ui-result-2026-11-05.json) and
[`manual-roi-overlay-geometry-result-2026-11-05.json`](manual-roi-overlay-geometry-result-2026-11-05.json).

The diagnostic logs Camera2 exposure time, sensitivity and frame duration. If
the iris advertises `MANUAL_SENSOR`, preview starts with the reversible no-IR
baseline of 30 ms / ISO 100 / 33.5 ms frame duration, derived from the 70.08 MHz
pixel rate, 2100-pixel line length and 1000-line initial exposure. Tap
**Use AE auto (restore)** to compare automatic control; closing the camera
returns the next session to the source-derived manual baseline. This is a
timing/control probe, not an image-quality calibration or illumination test.

## Build

Requires Android SDK platform 35, build-tools 35.0.0, JDK, and a signing keystore. This project uses direct SDK tools instead of Gradle.

```sh
ANDROID_SDK_ROOT=/path/to/android-sdk \
PROBE_KEYSTORE=/path/to/probe.keystore \
PROBE_KEY_ALIAS=irisprobe \
PROBE_STORE_PASSWORD='…' \
PROBE_KEY_PASSWORD='…' \
./build.sh
```

The APK is written to `build/LumiaIrisProbe.apk`. The local APK and signing materials are ignored by Git. Install with `adb install -r build/LumiaIrisProbe.apk`.

The pure-Java geometry, boundary-proposal and phase-code checks use generated
synthetic patterns only and can run on the host with
`python3 -m unittest tests/test_iris_probe_host.py` from the repository root.
The host checks also exercise crop-aware plane copying with padded row stride,
non-unit pixel stride, nonzero crop origin, bounds rejection and preservation
of the input buffer position. The saved I420 path rejects crop rectangles with
odd left or top origins until chroma rephasing is implemented; this avoids
writing U/V planes whose dimensions disagree with the output geometry.
Synthetic checks cover odd-origin rejection and aligned even-origin crops.
Crop extents are checked against each plane's dimensions, so row padding cannot
be misread as image pixels. They also verify that cleared diagnostic enrollment drops sample
references and that cleared sample/consensus codes no longer produce a valid
comparison. This remains a software behavior check, not guaranteed erasure of
all runtime copies; see
[`memory-zeroization-host-check-2026-11-05.json`](memory-zeroization-host-check-2026-11-05.json).

The iris camera appears when the installed kernel camera slot and
`libmmcamera_ir0861.so` plus the patched sensor-list module are active. The
phone's boot partition currently matches the tested kernel #18 image, and the
camera-order HAL update places the regular VS6955 camera at ID 1 and the iris
at ID 2. The probe still selects the iris by its unique 1920×1088 metadata.
