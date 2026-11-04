# Implementation milestones

## 1. Establish the installed baseline — partial phone report received

Run `tools/collect_cityman.py` from the README on a host with authorized USB
ADB access. It records selected identity properties, kernel release, visible
media/video class names, and camera/CCI device-tree properties as original hex
plus string or big-endian cell decoding. Phandles, GPIO records and controller
indices are retained as data; the tool does not interpret them as wiring.

Every command retains its status, exit code and error output. Missing interfaces
and permission denials require diagnosis and do not justify automatically
requesting root. The baseline tool never opens a camera stream or collects
images. No phone is connected to this cloud workspace; only host-side tests can
run here at present.

Acceptance: review a report from the actual cityman Android 16 build and record
its identity. A report without any visible camera nodes does not itself prove
there is no compiled driver, and a `collected` status is not sensor readiness.

The [first phone baseline](device-baseline.md) verifies the expected product,
API and kernel revision. Its missing live tree exports are expected for the
pinned kernel. The collector now supports passive platform uevents as an
alternative source of registered-node identity. Full DT properties remain
unexported; subsequent source/DTB analysis and the on-phone model read provide
the additional evidence recorded below.

## 2. Identify and power the iris sensor — first cycle passed

Use the original driver/firmware and hardware observations to fill the unknowns
in [hardware.md](hardware.md). First implement sensor power ownership and
verified ID reads in the target Qualcomm kernel/stack. Keep IR illumination off
for initial identification. Avoid blind I²C bus scans and guessed register writes.

The owner ran the separate, opt-in `iris-id-02` diagnostic and measured model
`0x0861` with clean cleanup, one attempt and no blocked state. Camera services
were restored, and the owner confirmed rear/front cameras unchanged afterward.
The diagnostic has no illumination/stream controls and does not occupy a HAL
sensor slot. Repeatability and suspend/resume remain untested. See the
[hardware result](device-baseline.md#iris-sensor-model-confirmed).

## 3. Deliver repeatable frames — not implemented

Implement clock/link setup and streaming with the matched sensor library or
kernel sensor interface. Acceptance needs actual IR-camera frame delivery,
known format/geometry, repeated open/close and failure recovery. CSI counters,
enumeration, or a camera ID alone do not pass this milestone. Keep capture data
local and out of this repository.

The [first-frame investigation](iris-capture.md) recovers the matching original
calibration's block roles and 1920×1088 RAW10 mode. Its read overrides are kept
separate from configuration records; complete dynamic timing and CSI integration
still need implementation.

Integrate the illuminator only after its control and optical limits are verified.
Add bounded exposure and a fail-off path before enabling it in a capture session.
Validate suspend/resume, timeout, cancellation, process death and power-down.

## 4. Enrollment and Android biometrics — not implemented

The staged implementation plan and current Windows illumination findings are
in [iris-authentication.md](iris-authentication.md).

Choose and validate an iris matching implementation and the Android integration
route documented in hardware.md. Implement enrollment, per-user templates,
challenge handling, cancellation, lockout and session lifecycle. Evaluate spoof
resistance and Android requirements before advertising authentication strength.
Do not ship a mock authenticator or report success for a camera-only test.

## 5. Keep the normal selfie camera first — locally applied

The LineageOS 23.2 Cityman device tree was fetched locally and its camera HAL
was changed to place the normal VS6955 front camera before the optional IR0861
iris camera. The change is in
[`android/patches/0001-cityman-camera-hal-put-iris-after-selfie.patch`](../android/patches/0001-cityman-camera-hal-put-iris-after-selfie.patch).
The property `persist.camera.cityman.iris_last=1` enables the new ordering.
The rebuilt 32-bit ARM `libmmcamera_interface.so` was installed on the connected
phone through a writable vendor remount; the original library is saved on the
phone at `/data/local/tmp/libmmcamera_interface-cityman-backup.so` and on the
host at `/private/tmp/libmmcamera_interface-pre-update.so`.

After restarting the camera provider, `dumpsys media.camera` reports camera 0
as the 5344×3744 rear camera, camera 1 as the 2600×1952 VS6955 selfie camera,
and camera 2 as the 1920×1088 IR0861. Aperture opened camera 1 and delivered a
live preview. The user confirmed the room lighting is magenta, so the preview
color is expected; a captured photo still has a reported green overlay and
needs separate image-pipeline investigation. No iris and regular-front streams
were active together. Camera clients were closed afterward, all camera
services returned to `running`, and all four LED brightness channels read zero.

This update was applied directly to the connected phone, without flashing a
boot image or pushing changes to GitHub. It has not yet been validated across a
full reboot; the persistent property is set and the writable vendor filesystem
contains the updated library. The patch mirror and build-result record remain
local in this workspace.

## Build scope

The current Python collector requires no package installation. Its tests run
with `python3 -m unittest discover -s tests -v` from the repository root. Use
the existing checkout; each cloud task is already isolated, so no additional
Git worktree is needed.

`sh tools/setup_cloud.sh` prepares checksum-pinned Platform Tools 37.0.1 under
`/workspace/.lumiafaceid/sdk`, initializes ADB's required user configuration
directory, verifies ADB/fastboot startup, and runs the host tests. It has been
run twice successfully in this instance to check repeatability. ADB reported
no attached devices. The reusable install script and startup guidance are saved
in the environment draft; publication and fresh-task restoration are not yet
validated.

The linked kernel and Android device tree are research inputs, not vendored
copies. Future driver code must be built against the matching pinned kernel
with its compatible ARM64 toolchain and configuration; Android modules need
the matching LineageOS source tree. This workspace currently has roughly
60 GiB free, so a full Android source sync/build has not been attempted.
The prerequisite kernel has now been built and privately repacked with the
owner's supplied boot backup; see [the kernel build report](../kernel/README.md).
The public artifact contains only the source-built kernel, with a local
repacker for the owner's ramdisk and device trees. It does not yet acquire iris
frames, and no phone has been flashed or boot-tested by this environment.
