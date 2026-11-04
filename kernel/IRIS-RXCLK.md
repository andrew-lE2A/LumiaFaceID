# Receiver clock observation on existing kernel #8

The MCLK test measured the internal sensor-clock branch near 9.6 MHz, with
normal camera recovery. Packet reception is still unresolved. The next test
measures two internal receiver branches during the same one-shot cycle:

| Debugfs clock | Purpose | Source expectation, not yet a phone measurement |
| --- | --- | --- |
| `camss_csi3_clk` | CSID3 core | Initialization requests 240 MHz |
| `camss_phy2_csi2phytimer_clk` | PHY2 timer used for settle timing | 200 MHz |
| `camss_csi3phy_clk` | separate CSI3PHY gate | not part of the earlier measurement |

The owner confirmed `measure`, `rate` and `enable` files exist for both clocks.
These clocks are generated inside the SoC; neither is a recovered MIPI clock
from the sensor. The measurements cannot establish an incoming physical signal
or a delivered image.

## Completed phone measurement

The owner reports stable enabled CSID3 core measurements of **239,999,157 Hz**
and PHY2 timer measurements of **199,999,414–200,000,878 Hz** on kernel #8.
Model `0x0861` and interface `0x0111=2` were confirmed. The sensor counter stayed
zero across 16 reads, and CSID3 packet/ECC/CRC counts stayed zero. The diagnostic
returned `-110` at stream-test. Sensor stop, receiver release and overall cleanup
returned zero; all three camera services restored. The owner confirmed both
ordinary cameras still work after every test.

[rxclk-result.json](builds/iris-csi-03/rxclk-result.json) now includes all 12
raw samples, recovered directly over ADB from the still-running kernel #8 boot.
CSID3 sample 1 crosses enable/rate initialization and is inconclusive; sample 2
is the sole stable enabled core measurement. PHY2 timer samples 1–2 are stable
enabled measurements. Both clocks are disabled in rounds 3–6 and measure zero.

The same read-only collection recovered all 20 sensor and 22 receiver snapshot
pairs: all are valid and identical to the preceding interface-selection test.
The saved result still shows attempts=1 and clean cleanup; all three services
are currently running. This collection did not start the sensor, reboot, read
the private profile, or repeat the clock measurements. Camera behavior and
service restoration during the test remain owner-reported evidence.

These internal measurements support the expected
240/200 MHz receiver clocks. They do not establish a recovered MIPI clock,
physical lane activity, valid packets or a delivered image. Another identical
clock test is not the next step. See the [startup/link audit](../docs/iris-startup-audit.md).

## CSI3PHY gate observation

A later one-shot added read-only `rate`/`enable` polling for
`camss_csi3phy_clk` and the selected PHY2 branch `camss_csi2phy_clk` while the
camera services were stopped. In the active iris receiver window,
`camss_csi3phy_clk` reported 240 MHz / disabled, while `camss_csi2phy_clk`
reported 240 MHz / enabled; `camss_csi3_clk` was 240 MHz / enabled and the
PHY2 timer 200 MHz / enabled. The sensor again timed out with no frames or
CSID3 packets, and cleanup was clean. The full [phone result](builds/iris-csi3phy-clock-01/phone-result.json)
includes transitional and teardown samples.

The pinned Linux CSIPHY2 device-tree node requests `camss_csi2phy_clk`, not
`camss_csi3phy_clk`. Existing front-camera sampling also found CSI3PHY disabled.
The Windows CAMT resource description refers to CSI3 clocks, but its exact
mapping to this Linux gate and whether it is needed alongside the chosen PHY2
route are unresolved. No clock was manually enabled. That mapping should be
checked against the original Windows startup path; a driver-voted comparison
is recorded below.

### Driver-voted CSI3 PHY comparison and pre-stream counter

Build `iris-csi3phy-precount-01` adds a named `camss_csi3phy_clk` handle to
the isolated iris node and enables it only around the explicit CSI receiver
test. It does not change the shared CSID clock table. It also records sensor
register `0x0005` immediately before the `0x0100=1` stream-on write. The
temporary image was RAM-booted; the installed kernel was not written.

The pre-stream counter was already `0x00` (valid, errno 0). With the CSI3 PHY
gate voted on, a hardware clock measurement reached 239,999,157 Hz. The sensor
still timed out: all 16 post-start counter samples were `0x00`, and CSID3
packet/ECC/CRC counts remained zero. Sensor stop, receiver release, and overall
cleanup returned zero. All camera services were running after cleanup, and
the phone returned to installed kernel #29. See the complete
[build manifest](builds/iris-csi3phy-precount-01/manifest.json) and
[phone result](builds/iris-csi3phy-precount-01/phone-result.json).

This closes the CSI3 PHY gate-off question for this driver path, but does not
prove the clock waveform reaches the sensor or establish MIPI reception. The
`0x00` pre-value also does not distinguish standby from a transition into
streaming. Next source-backed clock comparisons are the separate CAMT votes
for `camss_csi2_clk` and `camss_csi0_clk`; their independent tests are below.

### CAMT supplementary clock comparisons

Build `iris-csi-camt-clocks-01` adds root-only `csi-trial` selectors for
`clock=csi2` and `clock=csi0`. Each trial adds exactly one CAMSS gate to the
baseline CSI3 PHY vote, then releases it during cleanup. The six-round
read-only sampler was extended to include both selected gates.

The `csi2` trial measured `camss_csi2_clk` at 240,000,109 Hz while enabled; the
`csi0` trial measured `camss_csi0_clk` at 240,001,940 Hz while enabled. In both
trials the pre-stream counter was `0x00`, all 16 post-start samples remained
`0x00`, and CSID3 packet/ECC/CRC counts stayed zero. Both cleanly released
sensor and receiver resources and restored the camera services. The phone
returned to installed kernel #29. Full samples and outputs are in the
[CAMT clock build manifest](builds/iris-csi-camt-clocks-01/manifest.json) and
[phone result](builds/iris-csi-camt-clocks-01/phone-result.json).

These two source-listed clock votes did not resolve sensor startup or link
reception. The next useful branch is to establish whether the programmed
stream profile reaches a valid sensor mode and begins MIPI transmission. The
current pre-counter remains `0x00` before stream-on, so investigate the sensor
startup sequence against the Windows driver (especially initialization order
and the profile's execution context) before another receiver-clock sweep.

### Front-camera CSID3 positive control

The follow-up [CSID3 control](IRIS-CSID3-CONTROL.md#external-csid3-positive-control-with-the-csi3-phy-gate)
adds the CSI3 PHY gate to the CSID3 device clock list and routes the working
front camera to CSID3. Aperture then produced 416 preview frames; CSID3
released 1,094,240 packets with IRQ `0x55` and zero ECC/CRC. This is a positive
control for CSID3's lower PHY2 lane path when its CSI3 PHY gate is enabled.
An iris trial on the same boot still had a zero pre-counter, zero frame changes,
and zero CSID3 packets. The known-good lower-lane input now works; the iris
upper-combo path or sensor transmission remains the gap.

## Reproduction on a fresh temporary boot

Use the updated helper from GitHub. Keep the existing kernel #8 image and
prepared profile. No kernel rebuild or repack is needed. First run on the Mac:

```sh
adb reboot bootloader &&
fastboot boot "$HOME/Documents/cityman-iris-csi-03.img" &&
adb wait-for-device &&
adb root &&
adb wait-for-device &&
adb shell 'cat /proc/version; cat /sys/bus/platform/drivers/cityman-iris-id/*/result'
```

Confirm kernel #8, ready state, `attempts=0`, and `blocked=0`. Close the Camera
app. From the updated project directory, run:

```sh
adb push "$HOME/Documents/cityman-iris-stream-profile.hex" \
  /data/local/tmp/cityman-iris-stream-profile.hex &&
adb shell sh -s -- csi2-once --observe-receiver-clocks < tools/identify_cityman.sh
```

Paste the entire output, including `RXCLK sample=` lines and cleanup/service
restoration. After clean restoration, check both normal cameras and report
their behavior. Follow `REBOOT_REQUIRED` if printed. Do not retry on the same
boot. The sensor's unchanged-counter timeout is independent of this observation.

The updated helper samples five clocks for six rounds (30 samples); earlier
results have two- or three-clock logs. The clocks share a hardware debug mux,
so they
must not be measured by independent concurrent samplers. Readings are saved in
`/data/local/tmp/cityman-iris-rxclk.*` and printed before service restoration.
Missing files cause refusal before services stop. The helper never writes
clock rate/enable/parent controls or changes sensor/receiver configuration.

Interpret stable enabled samples; disabled zero readings and transition samples
are inconclusive. Measurements may miss part of the short powered window.
The existing counter read changes its diagnostic mux/reference clock and can
affect timing. The legacy counter's polling has no timeout: the sample count
does not impose a hard deadline. See the [MCLK measurement limits](IRIS-MCLK.md#interpretation-and-source-limits).

## Why the logged request does not establish CSID frequency

The pinned kernel is `cc84cab9900ee4e7a3046b3756858e9832caee72`.
Its `arch/arm/boot/dts/qcom/msm8994-camera.dtsi` CSID3 node has this mapping,
also verified directly in the published kernel #8 Cityman DTB:

| Clock index | Device-tree name | Clock provider symbol | Initial requested rate |
| --- | --- | --- | --- |
| 2 | `csi_clk` | `clk_csi3_clk_src` | 240 MHz |
| 3 | `csi_ahb_clk` | `clk_camss_csi3_clk` | inherited |
| 4 | `csi_src_clk` | `clk_camss_csi3_ahb_clk` | unspecified (zero) |

`msm_csid_get_clk_info` selects index 4 by the name `csi_src_clk` and copies
its zero rate into `csid_max_clk`. `msm_csid_config` sends the runtime rate
request to that index, rather than index 2. `clk_get` resolves device-tree names
through `of_clk_get_by_name`, so the mapping affects the clock object it gets.
The AHB branch has no independently programmable rate. Its rate-rounding error
is stored in an unsigned value, then clamped to `csid_max_clk=0`; the generic
clock implementation can return success for an unchanged cached zero rate.
The source thus predicts the real source can remain at its initialization
rate, despite a logged runtime request of 200 MHz.

CSID0 and CSID2 have the same name ordering and produced working previews.
The mismatch therefore does not establish the iris root cause. Moreover, the
CSID3 source table supports 100 and 240 MHz under its declared limit, so even
a correctly routed 200 MHz request can round to 240 MHz. This observation
measures existing behavior before considering a correction.

The PHY2 timer mapping is consistent: `csiphy_timer_src_clk` selects
`clk_csi2phytimer_clk_src` with a 200 MHz request, and its branch is
`camss_phy2_csi2phytimer_clk`. The clock provider and debug-mux selectors are in
`drivers/clk/qcom/clock-mmss-8994.c`; CSID configuration and indexing are in
`drivers/media/platform/msm/camera_v2/sensor/csid/msm_csid.c`. The helper's
`csi_clk=200000000` field remains a request, not a measured frequency.

## Validation

All 107 host tests pass. The added cases exercise both clocks in one saved
sequence, missing second-clock refusal before service changes, rejection of
sensor-only modes, and leaving cameras stopped when cleanup fails despite
successful sampling. Existing MCLK and service-recovery cases still pass.
Kernel binary, source hashes and DTBs are unchanged. Receiver measurements are now recorded above; all 12 raw sample rows have been recovered over ADB.
