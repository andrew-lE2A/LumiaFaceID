# LumiaFaceID

Research and bring-up for the Windows Hello iris camera on the **Lumia 950 XL
(cityman)** running the unofficial **LineageOS 23.2 / Android 16** port.

## Current status

The sensor is identified and the Android camera stack can open it. A diagnostic
app can show the preview and receive YUV frames, and a separate demo flow can
collect three transient samples and compare a later frame. **This is not a
working biometric authenticator:** eye localization and matching are
experimental, the comparison cutoff is provisional, and nothing in the app
unlocks Android or persists an enrollment template.

| Area | What is known |
| --- | --- |
| Sensor | Model `0x0861`; Android exposes three cameras and the iris is camera ID 2, reported as front-facing. The normal front camera remains its own slot. |
| Image path | Camera2 preview and 1920×1080 YUV callbacks have been observed from the iris camera. The frames captured so far are too dark or lack a usable eye region; segmentation and orientation/geometry are not validated. |
| Kernel diagnostic | MCLK is about 9.6 MHz, CSID3 core about 240 MHz and PHY2 timer about 200 MHz. CSI selection register `0x0111` reads back `2`. The separate direct stream diagnostic has recorded zero sensor-counter increments and zero CSID3 packet/ECC/CRC deltas. These measurements are from that diagnostic path and do not negate the Camera2 callbacks through the Android camera stack. |
| IR emitter | A previous single minimum-level `torch_0` request (brightness 14, corresponding to the lowest measured nonzero hardware code) returned ON/OFF, and the user reported a faint red glow. A matching Camera2 result/YUV frame was received in that run. The software helper turns the LED off on capture completion or after its one-second maximum. Optical output and actual LED-to-exposure timing were not measured. |
| Live preview IR | **Not implemented.** The repeating preview remains IR-off. Enrollment and comparison requests pulse the LED around an individual still capture; this is not the Windows per-frame camera/KMD illumination path. |
| Windows comparison | Static analysis found that Windows carries pulsing-mode and IR-current settings in a per-frame camera result submitted to a camera KMD IOCTL. The receiving implementation, Cityman pin/output route, Android timing equivalent and current-code mapping are unresolved. |
| Unlock | No iris biometric service is registered in the installed Android build. No protected template store, validated matcher, liveness detection, lockout policy or successful Android screen unlock exists. |

The Windows flash driver's accepted levels and pulse limits are **not** Android
brightness conversions or validated eye-safety limits. Do not raise the
emitter level based on those values. The current minimum-level software pulse
also does not constitute optical or eye-safety validation.

## Demo app

The experimental app source and device instructions are in
[`android/iris-camera-probe/`](android/iris-camera-probe/README.md). Its visible
flow is:

1. Open the iris camera.
2. Start an in-memory enrollment and capture three IR-assisted frames.
3. Capture one more IR-assisted frame for the demo comparison indicator.

The app stops repeating preview during each still capture, requests the
minimum-level torch pulse, then asks the helper to turn it off when Camera2
reports that exposure complete. The matcher is an unvalidated log-Gabor
prototype with an uncalibrated demo cutoff. **“Demo unlock” changes only the
app's display; it does not authenticate the user or unlock Android.** Captured
pixels and templates are transient and are not saved by this enrollment flow.

To build the feedback/demo APK, set the Android SDK and signing variables
documented in [`android/iris-camera-probe/build.sh`](android/iris-camera-probe/build.sh),
then build with the feedback manifest:

```sh
PROBE_MANIFEST=android/iris-camera-probe/AndroidManifest.feedback.xml \
  sh android/iris-camera-probe/build.sh
```

The built APK is ignored by Git. With the phone connected, the helper scripts
install/launch the demo or stop it, remove its ADB forward, and force all four
LED channels off:

```sh
android/iris-camera-probe/demo-on-phone.sh [adb-serial]
android/iris-camera-probe/demo-off-phone.sh [adb-serial]
```

Do not use the IR emitter while it is aimed at a person or eye, or inside a
metal can or reflective enclosure. For any authorized emitter observation,
use a diffuse target with no person or animal in the direct or reflected path.
The software timeout is not an eye-safety limit.

## Main blockers and next work

1. **Recover the real illumination route and timing.** Linux's pinned CCI GPIO
   write path is a no-op. Windows CCI queue/output mapping and the camera KMD
   receiver are not resolved. GPIO21 has a CCI_TIMER0 mux option in SoC data,
   but it was unclaimed in the observed Android state and the live device tree
   has no active CCI timer group. The service-schematic text is not enough to
   prove that this signal reaches the front IR emitter. Avoid guessed GPIO,
   register or pinmux writes.
2. **Reproduce camera-synchronized IR safely.** Windows sends per-frame pulse
   and current metadata through its camera stack. Android currently has only
   a bounded software pulse per still request, with no measured optical edge
   timing. The emitter's output, current mapping, thermal behavior and safe
   exposure remain unknown.
3. **Get usable images.** Capture repeatable frames with visible iris detail,
   confirm orientation and eye geometry, and build reliable pupil/iris
   segmentation and quality rejection on representative phone samples.
4. **Validate recognition before authentication.** The prototype matcher has
   no calibrated false-accept/false-reject rates or presentation-attack
   resistance. Android biometric framework scaffolding is source-only and
   does not provide a camera-backed authenticator.

See the living [development checklist](LumiaFaceID-checklist.txt), the
[Windows driver analysis](docs/windows-driver-analysis.md), the
[Windows-to-Android authentication map](docs/windows-iris-stack-map.md),
[Android authentication gaps](docs/iris-authentication.md),
[recorded phone route test](docs/iris-route-review-2026-11-05.json), and the
[kernel and CSI investigations](kernel/README.md).

## Read-only phone baseline

On a computer connected to the phone, install Python 3.10+ and Android SDK
Platform Tools. Enable USB debugging and authorize the computer. With the
phone booted into its Android 16 cityman ROM, collect a read-only baseline:

```sh
python3 tools/collect_cityman.py --output cityman-report.json
# If more than one Android device is connected:
python3 tools/collect_cityman.py --serial YOUR_ADB_SERIAL --output cityman-report.json
```

The report contains selected build properties, camera/media device names,
camera/CCI device-tree properties and the outcome of each read. It omits raw
logcat, biometric images, templates and a full property dump. Review it before
sharing. Reports are ignored by Git, existing output files are not overwritten,
and the collector does not request root, change SELinux, restart services, scan
I²C or write device registers.

On the current Linux 3.10 kernel, full device-tree exports are
disabled/unimplemented. The collector also reads selected platform-device
`uevent` files; a report may still be marked incomplete because full device-tree
properties are unavailable. Its `platform_devices` section remains useful.

## Development

The Python tools have no third-party dependencies. To run the repository's
host-side tests (which also need a C compiler):

```sh
python3 -m unittest discover -s tests -v
```

Tests use simulated ADB, init services and kernel APIs; they do not validate
hardware acquisition, illumination or authentication. The managed Linux x86_64
cloud setup is documented in [`tools/setup_cloud.sh`](tools/setup_cloud.sh).

No firmware, sensor calibration, Windows driver binaries, private sensor
profiles or biometric data are distributed here.
