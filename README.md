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
| Image path | Camera2 preview/YUV callbacks and one IR-off RAW10 frame have arrived. RAW10 was 1920×1088 with packed stride 2400; those pixels were discarded. A one-shot RAW10 save control is now installed, but has not yet captured a file. A 100 ms / ISO 800 manual request returned 99.996 ms / ISO 800, so manual sensitivity works; one AE result's ISO 3922 remains unexplained. The file converter passes a synthetic packed-RAW10 fixture, but real sensor bytes, image quality, segmentation and Cityman rotation remain unvalidated. See the [manual capture record](android/iris-camera-probe/phone-manual-100ms-iso800-2026-11-06.json), [RAW-save build readback](android/iris-camera-probe/raw10-save-control-build-2026-11-06.json) and [synthetic converter check](tools/iris-capture/synthetic-raw10-converter-check-2026-11-06.json). |
| Kernel diagnostic | MCLK is about 9.6 MHz, CSID3 core about 240 MHz and PHY2 timer about 200 MHz. CSI selection register `0x0111` reads back `2`. The separate direct stream diagnostic has recorded zero sensor-counter increments and zero CSID3 packet/ECC/CRC deltas. These measurements are from that diagnostic path and do not negate the Camera2 callbacks through the Android camera stack. |
| IR emitter | A previous bounded minimum-level `torch_0` request (brightness 14, lowest measured nonzero code) returned ON/OFF; the user reported a faint red glow, and a Camera2 result/YUV frame arrived in that historical run. Optical output, eye-safety limits and LED-to-exposure timing were not measured. The current enrollment/comparison flow does not activate IR. |
| Live preview IR | **Not implemented.** The repeating preview and enrollment/comparison are IR-off. An advanced button can request one 250 ms minimum-level `torch_0` pulse for a confirmed diffuse-target diagnostic; it is not synchronized to exposure or an eye-safety validation. |
| Windows comparison | Static analysis found that Windows carries pulsing-mode and IR-current settings in a per-frame camera result. Commit [a53c69a](https://github.com/leojukic03/lumia-iris-notes/commit/a53c69ad38a9bd7884067e84c771776945c13a60) decodes LED-7 assist settings 13/20/30/100% to PMI8994 flash-field codes 10/15/23/22 (about 125–291 mA by the Linux scale). Exact Cityman LED mapping, active default level, and Android camera-synchronized pulse path remain unresolved. `iris.sys` uses GPIO output index 0; its selector is separate. The test helper stays on phone loopback; no ADB forward is created. |
| Unlock | No iris biometric service is registered in the installed Android build. Local framework patches 0003-0008 add Keyguard plumbing and explicit fail-closed behavior, but are not built or installed. The phone reports `ro.crypto.state=unsupported`; there is no protected template store, validated matcher, liveness detection, lockout policy or successful Android screen unlock. |

The Windows flash driver's accepted levels and pulse limits are **not** Android
brightness conversions or validated eye-safety limits. Do not raise the
emitter level based on those values. The current minimum-level software pulse
also does not constitute optical or eye-safety validation.

## Demo app

The experimental app source and device instructions are in
[`android/iris-camera-probe/`](android/iris-camera-probe/README.md). Its visible
flow is:

1. Open the iris camera.
2. Start an in-memory enrollment and capture three IR-off diagnostic frames.
3. Capture one more IR-off frame for the demo comparison indicator.

The current app flow does not turn on the emitter. Its matcher is an
unvalidated log-Gabor prototype with an uncalibrated demo cutoff. **“Demo
compare” changes only the app's display; it does not authenticate the user or
unlock Android.** Captured pixels and templates are transient and are not
saved by this enrollment flow. Do not restore the old ADB forward: it made the
helper's pulse request available to local host processes.

To build the feedback/demo APK, set the Android SDK and signing variables
documented in [`android/iris-camera-probe/build.sh`](android/iris-camera-probe/build.sh),
then build with the feedback manifest:

```sh
PROBE_MANIFEST=android/iris-camera-probe/AndroidManifest.feedback.xml \
  sh android/iris-camera-probe/build.sh
```

The built APK is ignored by Git. With the phone connected, the scripts
install/launch the IR-off demo or stop it, remove any stale ADB forward, and
force all four LED channels off:

```sh
android/iris-camera-probe/demo-on-phone.sh [adb-serial]
android/iris-camera-probe/demo-off-phone.sh [adb-serial]
```

Do not use the IR emitter while it is aimed at a person or eye, or inside a
metal can or reflective enclosure. For any authorized emitter observation,
use a diffuse target with no person or animal in the direct or reflected path.
The software timeout is not an eye-safety limit.

## Missing pieces before iris unlock

1. **Validate real image bytes.** The installed probe has a guarded button to
   save one IR-off RAW10 frame and geometry sidecar in app-private storage.
   Capture it only while aimed at a diffuse, non-person target. No sensor
   pixels have been saved yet. The offline converter passed a synthetic
   packed-RAW10 fixture, but it still needs a real frame; normalization and
   Cityman rotation remain unknown.
2. **Recover Windows-equivalent image geometry and useful eye detail.** Confirm
   RAW normalization, orientation, the two-view split and eye coordinates on
   representative IR0861 frames. Current proposals did not yield repeatable
   eye regions. Implement pupil/iris segmentation and quality rejection only
   after those inputs are understood.
3. **Resolve illumination routing and timing.** Linux's pinned CCI GPIO write
   path is a no-op. The iris sequence requests CCI GPIO output index 0; its
   configured selector is a separate request field. Windows CCI queue/output
   mapping and the camera KMD receiver are not resolved. GPIO21 has a
   CCI_TIMER0 mux option in SoC data, but it was unclaimed in the observed
   Android state and the live device tree has no active CCI timer group. The
   service-schematic text does not prove that this reaches the front IR
   emitter. Avoid guessed GPIO, register or pinmux writes.
4. **Establish optical limits and camera-synchronized IR.** Windows carries
   per-frame pulse/current metadata, but the prior Android software pulse did
   not measure optical timing or eye exposure. Driver codes and the lowest
   Android brightness are not safety limits. Do not use IR for eye-facing
   enrollment until routing, current, thermal behavior, timing and safe
   exposure are independently established.
5. **Build and evaluate a real matcher.** The current log-Gabor code is a
   diagnostic prototype, with no representative Lumia enrollment set,
   calibrated false-accept/false-reject results or presentation-attack
   resistance. No iris identity decision is suitable for authentication.
6. **Implement the Android biometric path.** There is no camera-backed iris
   authenticator, enrollment/removal service, camera arbitration against the
   normal front camera, lockout policy or tested Keyguard integration. Local
   framework patches are source-only; the experimental app's demo comparison
   never unlocks Android.
7. **Provide hardware-backed template protection and result trust.** The
   phone reports `ro.crypto.state=unsupported`. A credential-authenticated
   AndroidKeyStore key remained software-backed even during a temporary boot
   where QSEECOM bound and `/dev/qseecom` existed. This tested path cannot
   protect iris templates or attest a trusted match; do not enable enrollment
   or unlock on it.

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
