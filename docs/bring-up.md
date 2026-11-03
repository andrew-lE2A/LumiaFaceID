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
alternative source of registered-node identity. Full DT properties and iris
sensor identification remain outstanding.

## 2. Identify and power the iris sensor — blocked on hardware evidence

Use the original driver/firmware and hardware observations to fill the unknowns
in [hardware.md](hardware.md). First implement sensor power ownership and
verified ID reads in the target Qualcomm kernel/stack. Keep IR illumination off
for initial identification. Avoid blind I²C bus scans and guessed register writes.

Only after the complete wiring and sensor program are established, add an opt-in
cityman device-tree patch and the appropriate sensor implementation to the
port's camera stack. Test failed probe, power unwind and shared camera-rail
ownership. A disabled dummy sensor node would not provide a usable driver, so
none is included here.

## 3. Deliver repeatable frames — not implemented

Implement clock/link setup and streaming with the matched sensor library or
kernel sensor interface. Acceptance needs actual IR-camera frame delivery,
known format/geometry, repeated open/close and failure recovery. CSI counters,
enumeration, or a camera ID alone do not pass this milestone. Keep capture data
local and out of this repository.

Integrate the illuminator only after its control and optical limits are verified.
Add bounded exposure and a fail-off path before enabling it in a capture session.
Validate suspend/resume, timeout, cancellation, process death and power-down.

## 4. Enrollment and Android biometrics — not implemented

Choose and validate an iris matching implementation and the Android integration
route documented in hardware.md. Implement enrollment, per-user templates,
challenge handling, cancellation, lockout and session lifecycle. Evaluate spoof
resistance and Android requirements before advertising authentication strength.
Do not ship a mock authenticator or report success for a camera-only test.

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
