# Working-front-sensor control for CSID3

On 2026-11-03 a separate temporary boot reused kernel #9 and its original
ramdisk, changing exactly one byte in the Cityman DTB: front camera
`/soc/qcom,cci@fda0c000/qcom,camera@1`, `qcom,csid-sd-index`, from 2 to 3.
The Talkman DTB was unchanged. Decoded trees were compared to require exactly
that property change; kernel, sensor identity/slot, PHY selection, power
sequence and all other properties were unchanged. The installed boot partition
was never flashed. The iris diagnostic was never triggered on this control boot.

The pinned kernel reads this property in `msm_camera_dt_util.c` into the sensor's
CSID subdevice ID. `msm_csiphy_lane_config` writes the selected CSID to the
normal lower mux nibble; the ISPIF input and clock mux code can encode CSID3.
This justifies a controlled routing comparison, but does not establish that
all hardware routes are supported or that CSID3's full setup is correct.

## Observed result

The rear camera delivered 51 preview frames at the saved snapshot and 626417
CSID0 packets at release, with zero ECC/CRC errors. The front camera opened as
camera ID 1, but produced zero frames and no latest-frame metadata. Kernel
logs confirm PHY2, lane mask `0x7`, two lanes, settle `0x0e`, CSID3, non-combo;
CSID configuration used lane assignment `0x4320`, PHY selection 2, RAW10 CID0
and embedded-data CID1. At both releases CSID3 reported zero packets/ECC/CRC.
The camera stack automatically closed and reopened the failed stream; there
was no manual second trigger. All three camera services were running after
closing Aperture. Iris remained ready/idle, attempts=0, blocked=0.

[Structured evidence](builds/iris-csi-04/front-csid3-control.json) includes
raw kernel lines and private local report paths. No image was saved. IR
remained disabled. The installed boot partition still matched the original
backup's SHA-256 before rebooting to the installed system.

## What this changes

CSID3 has **no positive input control**. The failure with a working sensor
makes receiver routing/configuration a concrete unresolved branch; zero iris
packets must not be attributed solely to sensor startup. This result does not
prove a defective CSID3, a supported PHY2-to-CSID3 hardware connection, or that
the iris sensor transmits. The control uses lower normal lanes, while iris uses
upper combo lanes and a different CSID control flag. It therefore cannot
validate the iris PHY path even if corrected later.

Next, trace the CSID3-specific mux/input, clock/reset and register-map setup
against the working CSID2 path and original platform driver. The normal init
log prints the selected register-table version (`0x30010000`), not the actual
hardware version read later; do not interpret its difference from diagnostic
`0x30010003` as hardware changing between runs. Any follow-up instrumentation
must distinguish configuration readback from an incoming signal. Do not sweep
sensor dividers or settle values to compensate for this failed control.

After returning to installed kernel #29, the front camera delivered 28708
frames at the saved snapshot and the rear delivered 64. Aperture was closed
and all three camera services remained running. This confirms camera recovery
after the temporary route comparison.

## Follow-up source trace and preview observation

The owner observed a pink/purple preview while the front camera was open.
The exact boot and moment of that observation have not been established, and
no preview image was captured. The saved CSID3 control snapshot shows zero
produced frames; it cannot identify what appeared on screen or explain its
colour. The later installed-kernel snapshot establishes frame delivery, not
colour accuracy. A previous description of the colour as likely an artifact
was speculative; its cause remains unknown.

The pinned MSM8994 device tree assigns PHY2 its own `csi2_clk_src`, PHY2
clock and PHY2 timer clock regardless of the selected downstream CSID. CSID3
has separate CSI3 source, core, AHB, RDI and PIX clocks. The PHY mux register
is at `0xfda00040`; ordinary PHY2 uses its lower nibble and upper combo mode
uses its upper nibble. The normal front-camera control selected CSID3 through
the lower nibble; the iris diagnostic uses the upper nibble. A successful
front control would therefore still leave the upper mux path unverified.

CSID3's device-tree register resource is only `0x100` bytes, versus `0x400`
for CSID2. The shared v3.1 register table's highest listed offset is `0xb4`,
so the observed statistics and configuration offsets fit inside the stated
CSID3 resource. This rules out resource length alone as an explanation for
zero packet counts; it does not verify the physical register implementation.
Both devices select the same v3.1 table from their compatible string. The
logged table version is not the hardware version, which is read separately
at initialization. No evidence here establishes the missing routing or
justifies a register write.

## Public source comparison and connected-phone check

The [upstream Linux CSIPHY implementation](https://code.googlesource.com/linux/torvalds/linux/+/f24ba334afafc70c3149e9db9c0cf8ecc6d52a09/drivers/media/platform/qcom/camss/camss-csiphy.c)
uses the upper clock-mux nibble when combo mode and lane mask `0x18` are
selected, and the lower nibble otherwise. The comparable
[Qualcomm Android driver](https://android.googlesource.com/kernel/msm/+/c65465727b39511c26ff33d03ed35a5e4dee6bc4/drivers/media/platform/msm/camera_v2/sensor/csiphy/msm_csiphy.c)
uses the same condition. This supports the existing mux operation as a
source-based starting point; these implementations do not establish the
MSM8994 board's physical connectivity or sensor transmission. The
[Linux CAMSS documentation](https://www.kernel.org/doc/html/v5.12/admin-guide/media/qcom_camss.html)
identifies its supported SoCs as MSM8916 and MSM8996, so its example topology
must not be assumed to describe MSM8994. No documented Lumia iris workaround
was established by this search.

On the connected phone, installed kernel #29 was still running. A fresh
ordinary front-camera preview produced 76 frames at the saved camera-service
snapshot (`reports/camera-web-followup-initial.txt`). Aperture was closed and
all three camera services were running. This check did not record an image or
establish preview colour, and did not exercise the iris sensor or CSID3.

## Test-generator interface check

A read-only ADB inspection on installed kernel #29 found four `msm_csid`
subdevices (`v4l-subdev3` through `v4l-subdev6`). Their names alone do not
identify their instance numbers. The pinned CSID driver handles subdevice ID,
configuration, and release ioctls; its CSID source has no test-pattern control
or test-generator implementation. The [mainline CAMSS driver](https://code.googlesource.com/linux/torvalds/linux/+/5a5409d90bd05f87fe5623a749ccfbf3f7c7d400/drivers/media/platform/qcom/camss/camss-csid.c)
has test-pattern support for other Qualcomm platforms, but this alone does not
establish the Lumia CSID3 register layout or packet-counter behavior for a
synthetic source. No test generator was enabled and no register writes were
made during this check. Matching hardware documentation or a verified driver
implementation is needed before proposing that temporary-kernel experiment.

### Follow-up: register definitions and comparable implementation

The pinned v3.1 table does declare test-generator addresses: control `0xa0`,
VC config `0xa4`, and data-type config `0xac`, `0xb0`, `0xb4`. The earlier
statement that the driver has no implementation refers to operational code;
the declarations exist. A [later Qualcomm camera_v2 CSID driver](https://android.googlesource.com/kernel/msm/+/fdfa87a6100a6d82c8ab3de9d1b694073bc148a7/drivers/media/platform/msm/camera_v2/sensor/csid/msm_csid.c)
contains a test-mode configuration path describing blanking, byte count, line
count, data type, and payload fields. This is a concrete candidate for a
source-based experiment, but the source is from another kernel revision and
its applicability to this hardware must be established before use. In
particular, determine the exact start/stop sequence, whether its v3.1 hardware
mapping matches all five offsets, and whether generated packets affect the
receiver's input statistics. A synthetic source would not test PHY wiring or
sensor startup. No generator or phone-side test was run in this follow-up.

The subsequent source search located Qualcomm test-mode setup fields but did
not recover a complete start/stop sequence or establish that the later source
uses this phone's exact generator layout. An attempted download of that full
source did not complete. These missing details leave the proposed synthetic
control unready for a phone run; no register writes or phone tests were made.

## Clock state during a repeated front-camera control

A further temporary boot of the same hash-verified front-to-CSID3 image
reproduced camera ID 1 with zero frames and CSID3 release counts of zero.
While the camera stack was attempting the front stream, read-only debugfs
samples reported `camss_csi3_clk`, `camss_csi3pix_clk`,
`camss_csi3rdi_clk`, `camss_csi3_ahb_clk`, `camss_csi2phy_clk`,
`camss_phy2_csi2phytimer_clk`, `csi2_clk_src`, and `csi3_clk_src` enabled.
The software-reported source/core/pixel/RDI rates were 240 MHz, and the PHY2
timer was 200 MHz. AHB reported rate 0 while enabled; its rate semantics are
not established. `camss_csi3phy_clk` was disabled, while the actual selected
PHY2 clock was enabled. `camss_csi2_clk`, CSI2 PIX and CSI2 RDI were disabled.

These samples were sequential software debugfs reads, not simultaneous
hardware frequency measurements; the camera stack automatically retries a
failed stream. They do not prove all clock signals reach the hardware. They
make a missing software enable for CSID3 core, PIX, RDI or the selected PHY2
clock a less compelling explanation at the sampled times. Raw local evidence:
`reports/csid3-clock-states.txt`, `reports/csid3-clock-camera.txt`, and
`reports/csid3-clock-dmesg.txt`. Iris remained idle with zero attempts; all
three camera services were running after the camera was closed. The phone was
rebooted to its installed kernel after the test.

## Research lead: capture lane events in the CSID IRQ handler

[Qualcomm's camera bring-up guide, section 9.3](https://usermanual.wiki/Document/00bringUp80nu3232hmultimediadriverdevelopmentandbringupguidecamera.1677897646.pdf)
covers MSM8994 among multiple platforms, with examples based on MSM8916. It
identifies CSID IRQ status bits 0–3 as start-of-transmission events and bits
4–7 as end-of-transmission events, and suggests inspecting them during sensor
bring-up. This is useful evidence for a diagnostic, but the bit mapping should
be validated on the Lumia with an ordinary camera before applying it to iris.

The pinned driver reads and clears IRQ status in `msm_csid_irq`; the iris
before/after readback is therefore a momentary snapshot, not a history of
lane events. Its debug IRQ configuration is compiled out (`DBG_CSID` is 0).
The existing `irq 0x0` release log does not prove no events occurred. The
guide's proposed all-bits mask should not be copied blindly: it could generate
an excessive interrupt rate or enable unrelated error sources.

A focused next diagnostic would add bounded, per-device counters or an OR mask
inside the existing handler, while preserving its reset completion and clear
semantics. On a fresh temporary boot, validate only the minimal required IRQ
mask and observation window first against the ordinary working CSID2 front
camera, then compare the same front sensor on CSID3 and finally the iris
one-shot. Stop and restore the original IRQ mask before releasing each device;
use bounded accumulation rather than logging every interrupt. Record which
mask was actually enabled, failures and cleanup. A positive lane event without
packets would motivate examining acquisition or packet format; no observed
event would still not distinguish absent sensor output from a broken route,
mask, or PHY acquisition. This is a research direction, not yet implemented or
tested. No sensor-register, routing, settle or IR changes follow from it.

## Bounded lane IRQ results: kernel #10

The local `0005-cityman-csid-lane-irq.patch` clears and enables lane IRQ bits
0–7 for CSID2/3 after configuration, records the first observed lane-event
status in the existing IRQ handler, then masks these eight bits to bound the
interrupt load. The mask is cleared as part of normal release, and the result
is logged after `disable_irq`. It was built in the case-sensitive Linux volume
and booted temporarily; 122 host tests passed.

| Input | Receiver / PHY lanes | Captured lane IRQ | Packets | Frames |
| --- | --- | --- | --- | --- |
| Ordinary front camera | CSID2, PHY2 lower, `0x7` | `0x55`, one sample | 242296 | 137 at snapshot |
| Ordinary front camera, rerouted | CSID3, PHY2 lower, `0x7` | `0x00`, no sample | 0 | 0 |
| Iris one-shot | CSID3, PHY2 combo upper, `0x18` | `0x00`, no sample | 0 | not delivered |

The CSID2 positive control establishes that this instrumentation captured
lane events on the working path; it does not establish that CSID3's interrupt
path is functional. The CSID3 front-camera test points to unresolved receiver
routing, acquisition or interrupt behavior. The iris counter remained zero
for 16 reads, with `-110` at `stream-test`; stop, receiver release and cleanup
were successful. Both ordinary cameras delivered frames afterward (47 front,
32 rear at their respective snapshots); all camera services ran, and the
installed boot partition matched the original backup. IR remained disabled.
The phone was rebooted to the installed kernel. No image was saved.

See [CSID2 control](builds/iris-irq-01/csid2-control.json),
[CSID3 control](builds/iris-irq-01/csid3-control.json), and
[iris result](builds/iris-irq-01/iris-result.json) for structured evidence.
These first-event masks are bounded samples, not cumulative event counts.

## Original CSID3 control flag: front-camera comparison

The original Lumia driver constructs CSID3 `CORE_CTRL_1` with bit 16 set;
the Linux normal-camera path did not. Kernel #11 was built with a separate
[experiment patch](../kernel/experiments/csid3-front-flag-control.patch)
that adds this bit only for a non-iris CSID3 configuration and logs the
readback. This comparison was grounded in the original driver's register
construction, but its applicability to the ordinary front sensor was not
established in advance. The existing iris diagnostic already sets this bit.

On a temporary boot, the rear camera delivered 36 frames at its snapshot. The
front camera on PHY2 lower lanes and CSID3 read back `CORE_CTRL_1=0x0005000f`,
but delivered zero frames and recorded zero lane events, packets, ECC and
CRC. The camera stack automatically retried the failed stream. Iris stayed
idle with zero attempts. All three camera services were running afterward,
and the installed boot partition still matched its backup. This rules out the
absence of this bit alone as the explanation for the failed front-camera
CSID3 control; it does not rule out other routing, acquisition or interrupt
causes. The test did not exercise iris transmission. See the
[structured local result](builds/iris-csid3-flag-01/result.json).

After returning to installed kernel #29, the front and rear cameras delivered
205 and 93 frames respectively at their snapshots. All camera services were
running after closing Aperture.
