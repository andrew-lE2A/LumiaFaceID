# Prerequisite kernel: temporary boot test

This build contains the camera slave-read correction from
`patches/0001-camera-restore-slave-read-state.patch`. It is a baseline kernel
compatibility test. **It does not yet add an iris sensor, acquire iris frames,
or enable IR illumination.**

The original phone backup and repacked image are kept outside Git. The public
artifact is the kernel gzip stream built from the documented source and patch.
The repacker combines it with the owner's existing boot backup locally.

## Prepare on the Mac

Download the updated repository ZIP from GitHub, extract it, and open Terminal
in that updated project folder. These commands assume the uncompressed boot
backup is `~/Documents/cityman-current-boot.img`, retained by `gzip -k`.

```sh
shasum -a256 -c kernel/builds/prep-01/SHA256SUMS
python3 tools/repack_boot.py "$HOME/Documents/cityman-current-boot.img" \
  --kernel kernel/builds/prep-01/Image.gz \
  --output "$HOME/Documents/cityman-prep-01.img"
```

The repacker verifies the original boot-image ID and retains the ramdisk,
appended device trees, boot command line, load addresses, OS-version word and
partition size. By default it refuses changed DTBs. It also refuses an unfamiliar checksum convention,
nonzero trailing signature/footer data, oversized replacement or existing output
file. It supports the inspected legacy cityman format, not arbitrary Android
boot formats.

The separate iris-ID package uses an explicit, reviewed `--dtbs` update. That
mode additionally verifies the board identities, DTB count and ordering; it is
not used for this baseline build.

## Temporary boot

With the phone connected and the original backup retained:

```sh
adb reboot bootloader
fastboot boot "$HOME/Documents/cityman-prep-01.img"
```

`fastboot boot` loads this image temporarily; these instructions do not flash
the installed boot partition. If that command is rejected, preserve the exact
error instead of substituting a flash command. If temporary boot does not
complete, reboot to return to the installed image.

After the UI boots, run:

```sh
adb wait-for-device
adb shell cat /proc/version
```

The build identification should contain `lumiafaceid@cloud`. The release name
remains `3.10.108-perf-gcc84cab9` to avoid an unnecessary module-vermagic change;
use the builder stamp to distinguish it from the original `builder@...` image.
Report whether Android starts normally and paste `/proc/version`. Camera frame
delivery and iris operation are separate checks and are not implied by a
successful boot.

## Validation scope

Host checks and the source build can verify container layout, hashes,
configuration and compilation. They cannot establish on-phone boot behavior,
module ABI compatibility or camera behavior. Hardware results will be recorded
after an owner-run temporary boot.
