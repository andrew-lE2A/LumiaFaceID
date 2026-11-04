# Lumia Iris Camera2 Probe

A minimal Android Camera2 app for the Lumia 950 XL iris bring-up. The HAL can assign the iris different numeric camera IDs across boots, so the app reads camera metadata and selects the unique front-facing 1920×1088 sensor, then opens only that ID. If there is no unique match, it refuses to open a camera. The preview keeps the sensor aspect ratio and has a **Rotate +90°** control for adjusting the provisional mount angle. The screen and logcat show the selected ID, stream size, open/configuration errors, and capture-result callback counts.

The **IR pulse** button is disabled until a capture-result callback arrives and is available once per app session. It requests torch_0 brightness 14 (the lowest previously measured nonzero hardware level) for one second. This is an unsynchronized control check, not illumination for an image or biometric authentication. Keep the emitter away from eyes. The app cannot write the LED sysfs node directly. For this test, the root-only localhost helper must be started over adb:

```sh
adb root
adb push iris-torch-server.sh /data/local/tmp/iris-torch-server.sh
adb shell chmod 700 /data/local/tmp/iris-torch-server.sh
adb shell 'nohup sh /data/local/tmp/iris-torch-server.sh >/data/local/tmp/iris-torch-server.log 2>&1 </dev/null &'
```

The helper binds only to `127.0.0.1`, rejects all commands except `PULSE`, writes brightness 14, and forces brightness back to 0 on completion or shell error. It is temporary and stops when the phone reboots. Check `/sys/class/leds/led:torch_0/brightness` is `0` after use. Do not use the sensor-strobe path.

The app does not enroll an iris or unlock Android. Android biometric integration requires a sensor HAL and matcher; see [`docs/iris-authentication.md`](../../docs/iris-authentication.md).

When the iris preview session is open, **Save one YUV frame** requests one
`YUV_420_888` still output and writes a packed I420 frame plus a small JSON
metadata sidecar to the app's private internal files directory. The button is
one-shot per app session; the capture has a five-second timeout. It does not
turn on the IR emitter. The frame is not an enrollment template and is not
uploaded or written to shared storage. Camera2 metadata identifies the sensor
orientation; the pixel buffer itself remains in sensor orientation. On launch,
the probe reports aggregate Y/U/V means, spread and ranges plus luma
percentiles, horizontal/vertical mean absolute gradients, clipping fractions,
and an 8×6 grid's local standard-deviation range for the latest private frame.
These spatial measurements help distinguish a nearly uniform stream from one
carrying image detail; they do not identify an iris, assess matching quality,
display pixels, or export frame data.

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

The iris camera appears when the installed kernel camera slot and
`libmmcamera_ir0861.so` plus the patched sensor-list module are active. The
phone's boot partition currently matches the tested kernel #18 image, and the
camera-order HAL update places the regular VS6955 camera at ID 1 and the iris
at ID 2. The probe still selects the iris by its unique 1920×1088 metadata.
