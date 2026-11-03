# Receiver clock observation on existing kernel #8

The MCLK test measured the internal sensor-clock branch near 9.6 MHz, with
normal camera recovery. Packet reception is still unresolved. The next test
measures two internal receiver branches during the same one-shot cycle:

| Debugfs clock | Purpose | Source expectation, not yet a phone measurement |
| --- | --- | --- |
| `camss_csi3_clk` | CSID3 core | Initialization requests 240 MHz |
| `camss_phy2_csi2phytimer_clk` | PHY2 timer used for settle timing | 200 MHz |

The owner confirmed `measure`, `rate` and `enable` files exist for both clocks.
These clocks are generated inside the SoC; neither is a recovered MIPI clock
from the sensor. The measurements cannot establish an incoming physical signal
or a delivered image.

## Run once on a fresh temporary boot

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

One background sampler alternates between the two clocks for six rounds,
twelve measurements total. The clocks share a hardware debug mux, so they
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
Kernel binary, source hashes and DTBs are unchanged. Receiver frequency
measurements on the phone remain pending.
