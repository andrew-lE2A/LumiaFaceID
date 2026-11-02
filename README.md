# LumiaFaceID

Bring-up of the **Lumia 950 XL (cityman) Windows Hello iris camera** on
**LineageOS 23.2 / Android 16**.

**Status: hardware investigation. There is no working iris driver or biometric
unlock implementation in this repository yet.** The first tool collects a
read-only baseline from the existing port. It does not power the sensor, enable
the infrared illuminator, enroll a user, or authenticate anyone.

## Collect a baseline

On a computer connected to the phone, install Python 3.10+ and Android SDK
Platform Tools. Enable USB debugging on the phone and authorize that computer.
With the phone booted into its Android 16 cityman ROM:

```sh
python3 tools/collect_cityman.py --output cityman-report.json
# If more than one Android device is connected:
python3 tools/collect_cityman.py --serial YOUR_ADB_SERIAL --output cityman-report.json
```

The output includes selected build properties, camera/media device names,
camera/CCI device-tree properties, and the outcome of each read. It omits raw
logcat, biometric images, templates, and a full property dump. Review it before
sharing. Generated reports are ignored by Git. Permission-denied and unavailable
interfaces remain recorded as unavailable; the tool does not request root,
change SELinux, restart services, scan I²C, or write device registers.

Exit codes: `0` = requested reads completed, `1` = collection incomplete,
`2` = tool/ADB/argument error, `3` = device/build differs from cityman Android 16.
Successful collection does **not** mean the iris sensor works. Reports with
failed reads are still saved. Existing output files are never overwritten.

On the port's current Linux 3.10 kernel, the full device-tree exports are
disabled/unimplemented. Collector 0.2.0 also reads selected platform-device
`uevent` files for registered camera/CCI node names and compatible strings.
The report can still say `incomplete` because full device-tree properties remain
unavailable; send the saved JSON anyway. Its `platform_devices` section is useful
and does not require enabling root or changing the kernel.

## Development

No third-party Python dependencies are required:

```sh
python3 -m unittest discover -s tests -v
```

In the managed Linux x86_64 cloud environment, `sh tools/setup_cloud.sh` installs
pinned, checksum-verified Android Platform Tools outside the checkout and runs
the tests. Use `--adb /workspace/.lumiafaceid/sdk/platform-tools/adb` with the
collector there. A phone must be connected to the host running the collector;
this cloud environment does not provide access to your computer's USB devices.

Tests use a simulated ADB transport. Hardware validation has not been performed.
See [the verified sources and missing hardware information](docs/hardware.md)
and [the implementation milestones](docs/bring-up.md).

For offline driver research, [windows-driver-analysis.md](docs/windows-driver-analysis.md)
records the recovered original tertiary-camera probe table and its limits.
`tools/inspect_iris_driver.py` reproduces the table extraction from the exact
pinned local ARM driver; it does not access the phone.

Target port: [XDA thread](https://xdaforums.com/t/rom-16-unofficial-lineageos-23-2-lumia-950-xl-cityman.4807007/).
No firmware, sensor calibration, Windows driver binaries, or biometric data are
distributed here.
