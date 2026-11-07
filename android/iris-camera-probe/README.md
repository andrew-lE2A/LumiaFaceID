# Lumia Iris Camera2 Probe

The app selects the unique front-facing 1920×1088 sensor from metadata, then opens only that camera ID. Its three-sample enrollment and demo comparison are now **IR-off only**: the earlier build incorrectly pulsed the emitter for samples that might be aimed at a person. IR-assisted eye capture is disabled until emitter output/current and exposure safety are independently established. IR-off samples may be too dark to encode a usable iris. This is an in-memory matcher demonstration, not Android enrollment or screen unlock.

Historical IR test: a previous version contacted a root-only helper to request
torch_0 brightness 14 (the lowest measured nonzero hardware code). One phone
run received a Camera2 result/YUV frame and the user reported seeing a faint
red glow. This confirms a software request and an observation, not optical
power, safe eye exposure, repeatable frame synchronization or useful iris
detail. The sensor timestamp source is unknown. **Do not point the emitter at
a person or eye.** A minimum driver code is not an eye-safety limit. Do not use
IR in a metal can or reflective enclosure.

The helper binds to the phone's `127.0.0.1` and always forces torch_0 back to
zero on disconnect, signal or timeout. Its current `ARM` transaction waits
for the Camera2 `onCaptureStarted` callback, accepts one `PULSE` command, then
turns the emitter off after 80 ms. The app reports the software callback and
helper acknowledgements; these do not measure the optical edge. A legacy
`PULSE` transaction retains its one-second auto-off for older app builds. An
ADB forward for `tcp:18761` exposes pulse requests to host-local processes;
the demo launcher removes stale forwards and never creates one. Enrollment
and comparison stay IR-off. The 2026-11-07 diffuse-target phone run exercised
the capture-start-triggered path once. The helper returned ON/OFF
acknowledgements and Camera2 delivered one 1920×1080 YUV image whose sensor
timestamp matched frame 589's `onCaptureStarted` and eventual capture result.
CPU analysis blocked the Camera2 callback handler, so the result callback
arrived about 7.06 seconds later, after the app's 850 ms wait expired. The
current local source moves analysis to a separate thread; this refactor has
not been built. The sensor timestamp source is `UNKNOWN`, so software events
do not establish optical overlap. Neither the requested cutoff nor minimum
brightness validates eye safety; do not point the emitter at a person or eye.
See [`capture-start test record`](capture-start-pulse-build-2026-11-07.json).

To install and open the IR-off diagnostic demo from the repository root:

```sh
android/iris-camera-probe/demo-on-phone.sh [adb-serial]
```

It requires `build/LumiaIrisProbe.apk`, refuses to start while any camera client is active, resets all four LED brightness nodes to zero, starts the loopback-only pulse helper, removes any stale `tcp:18761` forward, and installs/launches the demo. Start an IR-off diagnostic enrollment, collect three samples, then run a demo comparison if a usable template was produced. The threshold is provisional and unvalidated; no template is persisted, and Android is never unlocked. Advanced controls include the guarded one-shot IR test, manual ROI selection, exposure controls, and frame diagnostics. To close the app and force all LED nodes off, run:

```sh
android/iris-camera-probe/demo-off-phone.sh [adb-serial]
```

The app exposes emitter control only through the separate, confirmed diffuse-target test; enrollment and comparison cannot request IR. The helper timeout is a fail-safe, not an eye-safety limit.

Historical pulse-enabled app builds logged elapsed-realtime
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

To check capture-result/YUV timestamp matching after an **Analyze one live
frame** request, without reading any frame data:

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
itself remains in sensor orientation. The saved `.yuv` file is raw planar I420
(`Y`, then `U`, then `V`), not a PNG or
JPEG and not a screenshot of the probe UI. ROI graphics are drawn only over the
live preview. A green or purple appearance when opening that raw file with a
generic image viewer can come from interpreting the planar data with the wrong
format or dimensions; it does not by itself establish a sensor color defect.
The app does not apply a color correction to this diagnostic data. On launch,
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
the enrollment/comparison controls until the frame operation completes or
times out.
The same analysis now also reports luma statistics for the two rectangular
views described by the recovered Windows engine's `split_frame` path. It uses
the Windows nearest-quarter-turn calculation and 300-unit overlap, with
Android `SENSOR_ORIENTATION` supplied only as an unverified trial input. This
is a geometry probe: it does not copy/rotate the frame into Windows buffers,
and it does not establish that Camera2 Y has the same dimensions, byte layout,
normalization, or orientation as the private Windows BIR payload. Values are
discarded with the frame and cannot feed enrollment or comparison. See the
static-analysis caveats in [`docs/windows-iris-stack-map.md`](../../docs/windows-iris-stack-map.md).
The updated source compiled with Android 35 and a separately named temporary
package launched on the Lumia on 2026-11-06. The camera stayed closed, all
four LED channels read zero, and no biometric sensor/session appeared. This is
an app-start check only; see
[`phone-windows-split-app-launch-2026-11-06.json`](phone-windows-split-app-launch-2026-11-06.json).
The follow-up opened only iris camera 2, analyzed one unsaved IR-off YUV frame,
and exercised the split-statistics path. Its two views reported luma p95 values
151 and 153, but the face/eye ROI detector found no candidate. Timestamp
identity and clean camera/LED teardown were confirmed. The AE result again
reported ISO 2386 despite the advertised maximum of 800. See
[`phone-windows-split-frame-2026-11-06.json`](phone-windows-split-frame-2026-11-06.json).
The next build ran the existing coarse radial-contrast heuristic independently
inside each Windows-derived view, still display-only and excluded from matching.
One IR-off frame produced a candidate in view A (estimated pupil/outer radii
24/120 px) and no candidate in view B; the face/eye detector found no ROI.
This is not eye localization. Camera teardown again left no active clients and
all LEDs at zero. See
[`phone-windows-split-radial-probe-2026-11-06.json`](phone-windows-split-radial-probe-2026-11-06.json).
A follow-up manually selected that candidate's transformed preview location
and analyzed one more IR-off frame. Neither split view repeated a radial
proposal; the full-resolution crop yielded only a weak 4/10 px boundary with
0.111 valid phase bits. This is insufficient for iris coding and remains a
heuristic result, not proof about the earlier candidate. Camera teardown and
all LED-off readbacks passed; see
[`phone-manual-roi-followup-2026-11-06.json`](phone-manual-roi-followup-2026-11-06.json).
One controlled manual frame then requested 100 ms / ISO 800 and returned
99.996 ms / ISO 800. Its luma p95 was 102, below the preceding AE frame's 160;
both split halves produced only low-strength radial proposals, with no
face/eye ROI. Closing the camera restored AE mode, left no clients, and all
four LED channels read zero. See
[`phone-manual-100ms-iso800-2026-11-06.json`](phone-manual-100ms-iso800-2026-11-06.json).
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

The latest linked reverse-engineering notes ([commit `eb1fca3`](https://github.com/leojukic03/lumia-iris-notes/commit/eb1fca3cf9b9996595964153360089658f082255))
add an off-device-tested optional Windows AE cap of 667 sensor lines (about
20 ms), 4× analog gain (ISO 400), and no ISP digital gain. That option is for
the sensor plugin and remains off by default; it is not evidence that the
Camera2 probe should clamp its diagnostic controls. The same commit documents
Windows' left 300-column crop and overlapping two-view split. An offline
converter is available at
[`tools/iris-capture/windows_frame.py`](../../tools/iris-capture/windows_frame.py)
for an actual RAW10/RAW16 capture with known dimensions and stride. The exact
Windows tone mapping and Cityman rotation remain unresolved, and this converter
does not handle the app's current YUV capture or provide a matcher input.

CameraService readback on 2026-11-06 confirmed iris camera ID 2 advertises
full-array RAW10 (format 37), RAW16 (format 32) and RAW_OPAQUE outputs at
1920×1088, with the RAW capability set. One bounded IR-off RAW10 still request
then delivered an image plane: 1920×1088, row stride 2400, pixel stride 0,
2,611,200 bytes, full-frame crop. Its timestamp matched the capture result.
The packed row size matches four 10-bit pixels in five bytes; the in-memory
decoder completed and discarded the pixels. The standalone file converter
has not yet processed a real sensor file because no pixel data were saved.
The result also reported ISO 3922, above the advertised 100–800 range, so AE
metadata needs separate investigation before exposure tuning. See
[`phone-raw10-callback-2026-11-06.json`](phone-raw10-callback-2026-11-06.json)
and the static capability
[`raw-stream-capability-readback-2026-11-06.json`](raw-stream-capability-readback-2026-11-06.json).

The follow-up manual YUV capture requested 100 ms / ISO 800 and received
99.996 ms / ISO 800, with no post-RAW boost and AE inactive. This shows the
manual-sensitivity path applies the requested value; it does not explain the
single AE result that reported ISO 3922. The frame was IR-off, was not saved,
and contained no detected face/eye ROI. See
[`phone-manual-100ms-iso800-2026-11-06.json`](phone-manual-100ms-iso800-2026-11-06.json).

The Advanced controls now include a separate one-shot **Save one RAW10 frame**
action. A confirmation dialog requires the operator to aim only at a diffuse,
non-person target. It requests exactly one still with the emitter disabled,
saves packed RAW10 bytes and geometry metadata only under app-private files,
and permits one save per app installation; it detects an existing RAW file
after activity recreation. Clear this app's data or reinstall it to reset the
one-shot gate after retrieving the file. It does not enable IR, run enrollment,
or upload pixels. One real frame has been saved. The source was a confirmed
diffuse, non-person target; the request was IR-off and returned 19.987 ms / ISO
250. The packed RAW10 file was retrieved and decoded at candidate rotations 0
and 90; both outputs are nearly black (p95 19–20 on the converter's 8-bit
scale), so this does not validate useful iris detail, Windows normalization
or orientation. The raw pixels remain outside the repository. The offline
converter also passed a synthetic packed-RAW10 fixture with padded rows. See
[`phone capture record`](phone-raw10-windows-init-2026-11-06.json) and
[`synthetic converter check`](../../tools/iris-capture/synthetic-raw10-converter-check-2026-11-06.json).

For another authorized diffuse non-person capture after clearing app data or
reinstalling, retrieve and render both rotation candidates with:

```sh
python3 tools/iris-capture/pull_and_convert_raw10.py \
  --package com.lumia.irisprobe.rawsave20261106 \
  --output-dir /private/tmp/lumia-iris-captures \
  --confirm-non-person-target
```

The script only reads an already saved, full-array RAW10 frame from a
debuggable probe package. It never opens the camera or turns on the emitter;
it refuses to overwrite an existing capture directory. The fake-ADB check
and one real Lumia capture have both exercised the two rotation outputs.

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
