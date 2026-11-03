# MCLK observation on existing kernel #8

Kernel #8 selected CSI-2 successfully but recorded zero iris packets. Both
normal cameras recovered. Before changing another sensor or receiver setting,
measure the existing MCLK1 branch during the powered diagnostic window.
The owner confirmed the three required debugfs files are available.

## Completed phone measurement

The owner captured all 12 samples and confirmed both normal cameras work after
the test. Samples 2–4 had stable software rate 9,600,000 Hz and enable=1 on
both sides of the hardware count. They measured **9,600,109–9,600,183 Hz**.
Sample 1 crossed the initial rate transition; samples 5–12 were disabled and
measured zero, with the saved software rate returning to 19.2 MHz.

This establishes that the internal branch counts near 9.6 MHz while enabled;
it does not measure the sensor pin. The sensor counter and all CSI packet/error
counts stayed zero. All 20 sensor and 22 receiver readback pairs matched the
preceding interface-selection test. Sensor stop, receiver release and overall
cleanup returned zero; all three camera services restarted.

See [mclk-result.json](builds/iris-csi-03/mclk-result.json). The next
[receiver clock observation](IRIS-RXCLK.md) measures the CSID3 core and PHY2
timer on the same kernel. The MCLK instructions below document the completed
test; an identical repeat would add no new observation.

## Measurement procedure

This uses the existing `cityman-iris-csi-03.img` and prepared profile. No new
kernel, repack or ZIP is needed. Use the updated `tools/identify_cityman.sh`
from GitHub. The helper's optional `--observe-mclk` flag starts 12 clock
samples after camera services stop, alongside the single sensor test. It waits
for sampling to finish before restoring services and keeps the clock log in
`/data/local/tmp/cityman-iris-mclk.*` as well as printing it.

## Run on the Mac

Start with a fresh temporary boot, even if kernel #8 is already running:

```sh
adb reboot bootloader &&
fastboot boot "$HOME/Documents/cityman-iris-csi-03.img" &&
adb wait-for-device &&
adb root &&
adb wait-for-device &&
adb shell 'cat /proc/version; cat /sys/bus/platform/drivers/cityman-iris-id/*/result'
```

Confirm kernel **#8**, `status=ready`, `attempts=0` and `blocked=0`. Close the
Camera app. From the updated project directory, run once:

```sh
adb push "$HOME/Documents/cityman-iris-stream-profile.hex" \
  /data/local/tmp/cityman-iris-stream-profile.hex &&
adb shell sh -s -- csi2-once --observe-mclk < tools/identify_cityman.sh
```

Paste the full output, including all `MCLK sample=` lines and final cleanup
and service-restoration lines. The sensor counter may still time out: that
result is independent of the additional clock observations. If cleanup is
confirmed and services restore, check both normal cameras and report their
behavior. Follow `REBOOT_REQUIRED` if printed. Do not retry on the same boot.

## Interpretation and source limits

Each sample prints software rate/enable before and after the hardware
measurement. Samples with both enable values positive and a stable requested
rate of 9,600,000 Hz can show whether this internal branch counts near that
frequency. Zero while disabled is expected. Samples across transitions, or
samples missing the powered window, are inconclusive. The helper never forces
the clock on or writes its rate, enable or parent controls.

This is an internal frequency counter, not a probe of GPIO14 or the sensor's
clock pin. The debugfs read itself selects/enables the measurement mux and
reference clock inside the existing clock driver. It can affect timing; it is
not a completely passive hardware observation.

The pinned Linux 3.10 implementation is in `drivers/clk/qcom/clock-debug.c`
(`clock_debug_measure_get`) and `clock-local2.c` (`measure_get_rate` and
`run_measurement`). Each read normally takes about 15 ms, with local interrupts
masked during counting. Its polling loops have no timeout: 12 is a sample
count, not a hard wall-clock deadline. Missing files are rejected before
services stop. A failed read is reported as `MCLK_OBSERVATION_INCOMPLETE`;
camera restoration still depends on the independent sensor/receiver cleanup.

The source and gate mapping are in `clock-mmss-8994.c`: `mclk1_clk_src` has a
9.6 MHz XO-derived setting, and `camss_mclk1_clk` gates that source. The pinned
camera pinctrl maps MCLK1 to GPIO14. These agree with firmware's requested
MCLK1/GPIO14/9.6 MHz configuration; actual sensor-pin behavior is unmeasured.

Only the helper and host tests changed for this observation. Kernel #8's
published binary, driver sources, receiver route, clock requests, sensor
program, exposure/gain and settle settings are unchanged.

All 103 host tests pass, including missing clock files, read failure, saved
samples and sampler completion before camera-service restoration. These tests
exercise helper behavior with simulated files. The phone result above supplies
the actual internal branch measurement.
