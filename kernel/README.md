# Kernel prerequisite for sensor-ID diagnostics

`patches/0001-camera-restore-slave-read-state.patch` fixes an existing camera
ioctl before it is considered for diagnostics. It is **not an iris driver** and
does not create a sensor slot, configure rails or enable illumination.

Base: `giannoccarol/android_kernel_mmo_msm8994` commit
`cc84cab9900ee4e7a3046b3756858e9832caee72`, matching the user's kernel release.

## Why the patch is needed

In both native and compat `CFG_SLAVE_READ_I2C`, the original code saves the
sensor client's target address, substitutes the requested address, reads, and
leaves that address in the client on both success and failure. Later operations
could target the wrong device. It also stores through a userspace pointer
directly rather than using the kernel's user-copy interface.

The patch restores the saved CCI SID or I2C address immediately after the read,
before either result path, and returns the result using `copy_to_user()`. A
failed copy returns `-EFAULT`. It preserves the existing power-state behavior:
this ioctl still does not establish that a sensor has been powered correctly.
It must not be treated as permission for arbitrary reads on active camera slots.

## Existing interfaces and the missing iris slot

The pinned CCI driver does not set `V4L2_SUBDEV_FL_HAS_DEVNODE`, so its raw CCI
ioctl is a kernel subdevice interface, not a user-accessible `/dev/v4l-subdev`
endpoint. No raw CCI debugfs/sysfs interface was found in that source.

The sensor-init ioctl requires an existing DT-populated `g_sctrl[camera_id]`.
It cannot create the absent iris slot, and it rejects replacing a rear/front
slot after successful probe. Root ADB access alone does not supply an iris
power path or a dedicated diagnostic endpoint.

## Validation completed on 2026-11-03

- `git apply --check` and actual patch application passed against the exact base.
- The affected ARM64 `msm_sensor.o` compiled successfully with `mmo_defconfig`.
- `CONFIG_COMPAT=y`; the object contains both `msm_sensor_config` and
  `msm_sensor_config32`, so both changed handlers were compiled.
- Compiler source: `LineageOS/android_prebuilts_gcc_linux-x86_aarch64_aarch64-linux-android-4.9`
  commit `5e030eafe024784a73cdf47e6936ac0dbfc763dc`.
- Reported target compiler: GCC `4.9.x 20150123 (prerelease)`.
- Existing host Kconfig and unimplemented-syscall warnings occurred during
  preparation; the patched sensor object compiled without an error.

The GCC launcher uses an unavailable `/usr/bin/python` shebang in this cloud
image. Invoking the unmodified launcher with Python 3 works; no toolchain
files or verification checks were changed.

Reproduce with an exact-base, disposable kernel checkout and the compiler above.
Use an existing isolated checkout when available; no Git worktree is required.
After verifying the checkout has no user changes:

```sh
lumia_kernel=/tmp/cityman-kernel-build
lumia_gcc=/tmp/cityman-gcc49
lumia_out=/tmp/cityman-kernel-out
lumia_patch=/workspace/LumiaFaceID/kernel/patches/0001-camera-restore-slave-read-state.patch

git -C "$lumia_kernel" rev-parse HEAD
git -C "$lumia_kernel" apply --check "$lumia_patch"
git -C "$lumia_kernel" apply "$lumia_patch"
make -C "$lumia_kernel" O="$lumia_out" ARCH=arm64 \
  CROSS_COMPILE="$lumia_gcc/bin/aarch64-linux-android-" \
  CC="python3 $lumia_gcc/bin/aarch64-linux-android-gcc" mmo_defconfig
make -j2 -C "$lumia_kernel" O="$lumia_out" ARCH=arm64 \
  CROSS_COMPILE="$lumia_gcc/bin/aarch64-linux-android-" \
  CC="python3 $lumia_gcc/bin/aarch64-linux-android-gcc" \
  drivers/media/platform/msm/camera_v2/sensor/msm_sensor.o
```

Object SHA-256 from this run:
`b3d812dc940ee01a8732d611d3575f8febc6e3c529f131688338753d86302cd3`.
This identifies the retained build output, not a required checksum for every
rebuild with different timestamps or paths.

The full `Image.gz-dtb` target subsequently built successfully with this patch.
No hardware test has been run, and no phone was flashed. The next implementation still needs a
dedicated opt-in iris/diagnostic slot with confirmed bus routing and sensor-only
power sequencing. The IR illuminator should remain off for identification.

The original firmware/platform-driver trace now supports CCI master 0 for the
iris path; see [windows-driver-analysis.md](../docs/windows-driver-analysis.md).
The sensor's runtime response and the sensor-only power path remain untested.

Before packaging an experimental boot image, obtain a backup of the phone's
current `boot` partition. This supplies the actual ramdisk, header and boot
parameters and provides a recovery copy. Rooted ADB permits reading this
partition without flashing anything. Compress the backup before sharing if
the partition is padded. Do not build a guessed boot header from the old source
comments or overwrite the owner's recovery backup.

## Full build and packaging

The uploaded backup is a 35651584-byte header-v0 image, page size 4096, with
an appended-DTB gzip kernel and two board DTBs. Its ID uses the legacy empty-DT
SHA-1 size term; the repacker detects and retains that convention. The original
embedded effective `CONFIG_` settings match `mmo_defconfig`. An unchanged
repack round-tripped the complete backup byte for byte.

Full-build command after the patch and configuration steps above:

```sh
# In this disposable source tree only, preserve the existing release suffix.
printf '%s\n' '-gcc84cab9' > "$lumia_kernel/.scmversion"
PATH="/tmp/lumia-host-tools/usr/bin:$PATH" make -j3 -C "$lumia_kernel" \
  O="$lumia_out" ARCH=arm64 \
  CROSS_COMPILE="$lumia_gcc/bin/aarch64-linux-android-" \
  CC="python3 $lumia_gcc/bin/aarch64-linux-android-gcc" \
  KBUILD_BUILD_USER=lumiafaceid KBUILD_BUILD_HOST=cloud KBUILD_BUILD_VERSION=1 \
  Image.gz-dtb
```

The PATH entry supplies Debian `bc` 1.07.1-4, obtained through signature-checked
Debian repository metadata and extracted locally. Other build tools are the
existing host GCC/Make and the pinned ARM64 toolchain. Compilation succeeded
with existing warnings in the legacy source; no warnings or checks were disabled
to make it pass.

The public kernel-only artifact and build manifest are in
[`builds/prep-01`](builds/prep-01/manifest.json). The kernel release remains the
original value to avoid an unnecessary module-vermagic change, while the
`lumiafaceid@cloud` builder stamp identifies the new build. Module compatibility
and boot behavior still need hardware validation.

The new private test image was packed and reparsed successfully. Its ramdisk,
both DTBs, boot parameters, load addresses, OS-version word and partition length
match the original backup. The public repacker has host tests for both supported
checksum styles, corrupted data, footer/signature refusal, bounds, DTB
preservation and output-file protection. See [BOOT-TEST.md](BOOT-TEST.md) for
local assembly and temporary-boot instructions. No uploaded boot/ramdisk bytes
are included in Git.
