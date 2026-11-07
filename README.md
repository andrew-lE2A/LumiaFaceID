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
| Image path | IR-off RAW10 capture works. The earlier 20 ms / ISO 250 frame had p95 19; a 75 ms AE frame at ISO 1042 had p95 52 (above the advertised ISO maximum 800); a manual 300 ms / ISO 800 frame reached p95 139 in the 8-bit approximation. Full 10-bit analysis of that frame gives p95 559/1023, maximum 871, and no clipping; a smooth central-bright gradient dominates, with no identifiable scene or eye detail. The converter's 0°/90° settings change only Windows split axis/order and do not rotate pixels, so physical sensor orientation remains unknown. Pixel files remain outside Git. See the [manual 300 ms capture](android/iris-camera-probe/phone-raw10-manual300-iso800-2026-11-07.json), [AE capture](android/iris-camera-probe/phone-raw10-ae-followup-2026-11-07.json), [orientation-mode review](android/iris-camera-probe/raw10-orientation-mode-review-2026-11-07.json) and [original manual capture](android/iris-camera-probe/phone-raw10-windows-init-2026-11-06.json). |
| Kernel diagnostic | MCLK is about 9.6 MHz, CSID3 core about 240 MHz and PHY2 timer about 200 MHz. CSI selection register `0x0111` reads back `2`. The separate direct stream diagnostic has recorded zero sensor-counter increments and zero CSID3 packet/ECC/CRC deltas. These measurements are from that diagnostic path and do not negate the Camera2 callbacks through the Android camera stack. |
| IR emitter | A minimum-code `torch_0` request (brightness 14) returned ON/OFF during one diffuse-target Camera2 capture; the frame arrived and was analyzed in memory. The exact optical pulse edge was not measured, and the analysis summary was not retained. See the [capture record](android/iris-camera-probe/phone-ir-min-current-frame-2026-11-07.json). |
| Capture pulse | Enrollment, comparison and repeating preview remain IR-off. One phone run of the capture-start-triggered minimum `torch_0` pulse returned ON/OFF acknowledgements and one matching YUV frame. In that build, analysis blocked the Camera2 callback handler, so the result callback arrived about 7.06 s later. The current local source moves analysis to a separate thread; it now builds and an IR-off on-device analysis run confirmed prompt capture callbacks and worker completion. The revised IR pulse path itself has not been rerun. Sensor timestamps are `UNKNOWN`; optical overlap is unverified. See the [capture test record](android/iris-camera-probe/capture-start-pulse-build-2026-11-07.json) and [IR-off analysis-thread record](android/iris-camera-probe/phone-analysis-thread-ir-off-2026-11-07.json). |
| Windows comparison | Static analysis found that Windows carries pulsing-mode and IR-current settings in a per-frame camera result. The latest notes [bd2fcdd](https://github.com/leojukic03/lumia-iris-notes/commit/bd2fcddaada36f718aaedef94ce8b9dbce2b733d) correct the nominal PMI8994 estimate to `code × 12.5 mA` (codes 10/15/23/22: about 125/188/288/275 mA; Linux scale: 127/190/291/278 mA) and withdraw the luma-70 step-up procedure. These are not optical measurements or safety limits. Exact Cityman LED mapping, active default level, and Android camera-synchronized pulse path remain unresolved. `iris.sys` uses GPIO output index 0; its selector is separate. The test helper stays on phone loopback; no ADB forward is created. |
| Unlock | No iris biometric service is registered in the installed Android build. Local framework patches 0003-0008 add Keyguard plumbing and explicit fail-closed behavior, but are not built or installed. The default Keymaster wrapper has no hardware `keystore` module to load and falls back to software; `ro.hardware.keystore` is empty, `ro.crypto.state=unsupported`, and `/dev/qseecom` is absent. The prior credential-bound key test remained software-backed even with QSEECOM bound. No Cityman Keymaster trust app was found in the inspected firmware sets. There is no protected template store, validated matcher, liveness detection, lockout policy or successful Android screen unlock. See the [Keymaster module audit](android/keyinfo-probe/keymaster-runtime-module-audit-2026-11-07.json). |

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

Enrollment and comparison do not turn on the emitter. The app has a separate
confirmed diffuse-target one-frame illumination diagnostic. Its matcher is an
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

See the ordered [iris unlock development roadmap](IRIS-UNLOCK-ROADMAP.md) for
the sequence, methods, and completion checks for these gates.

1. **Get useful image detail and validate geometry.** Three IR-off RAW10 stills
   have been saved on a confirmed diffuse, non-person target, retrieved and
   decoded using Windows split modes for orientation inputs 0 and 90; those
   modes do not rotate the pixel array. The manual init frame spans 9–25; a
   later AE frame reached p95 52 at ISO 1042 (above the advertised maximum
   800); and a manual 300 ms / ISO 800 frame reached p95 139 in the 8-bit
   approximation (full RAW10 p95 559/1023, maximum 871, no clipping). The
   latest stretched image still shows only a broad gradient and fine grain,
   without useful scene or eye detail. These captures prove RAW10 retrieval/decoding
   but do not settle physical orientation or Windows normalization. Pixel
   files remain outside Git. See the [300 ms capture](android/iris-camera-probe/phone-raw10-manual300-iso800-2026-11-07.json),
   [AE follow-up](android/iris-camera-probe/phone-raw10-ae-followup-2026-11-07.json),
   [manual capture](android/iris-camera-probe/phone-raw10-windows-init-2026-11-06.json),
   and [orientation-mode review](android/iris-camera-probe/raw10-orientation-mode-review-2026-11-07.json).
   A next useful image test needs a brighter diffuse target/scene with IR
   disabled; do not aim IR at a person or eye.
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
   or unlock on it. A read-only inventory of the mounted vendor and firmware
   trees found no separately named Keymaster trustlet. See the [vendor
   secure-app inventory](android/keyinfo-probe/vendor-secure-app-inventory-2026-11-07.json).

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
