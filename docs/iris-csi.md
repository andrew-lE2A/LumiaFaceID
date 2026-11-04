# CSI reception after the version 02 sensor test

Build #5 established that mode select latched and timing/geometry registers
could be read back. The counter stayed zero. The complete
[phone result](../kernel/builds/iris-stream-02/phone-result.json) records clean
stop/unwind and the owner's confirmation that both normal cameras still work.
Neither counter behavior nor mode select establishes packet transmission.

The owner subsequently completed the first receiver test on kernel #6:
setup/release succeeded, receiver version was `0x30010003`, all recorded
packet/ECC/CRC values were zero, and normal cameras remained unchanged. These
observations do not establish a missing physical signal; receiver configuration
and PHY status were not captured. See the
[phone evidence](../kernel/builds/iris-csi-01/phone-result.json).

Version 02 on kernel #7 then confirmed the complete target configuration in
readbacks, including the original bit-16 flag, while CSID3 still recorded zero
packets. PHY IRQ status words 3/4 changed to `0x4` and word 6 to `0x10` before
sensor stop. Their exact meanings have not been recovered, so these latched
changes cannot be called valid sensor transmission. Stop/cleanup and normal
camera recovery passed. The
[version 02 evidence](../kernel/builds/iris-csi-02/phone-result.json) preserves
all register pairs.

The same boot's working front/rear previews recorded positive packet counts
on CSID2/CSID0 with zero ECC/CRC errors. Front preview reached 128,964 packets
and rear preview 260,410. The additional bit-16 write is absent from the normal
camera path, showing that it is not generally required for nonzero counters on
these receivers. This comparison validates observation on receivers 0/2; it
does not supply a positive input control for CSID3. See
[camera-control-result.json](../kernel/builds/iris-csi-02/camera-control-result.json).

Kernel #8's explicit CSI-2 selection then latched `0x0111=2`, but all other
sensor pairs and all receiver pairs matched #7. Packet counts remained zero;
cleanup and normal camera recovery passed. See the
[comparison evidence](../kernel/builds/iris-csi-03/phone-result.json).
The subsequent [MCLK observation](../kernel/IRIS-MCLK.md) measured the internal
enabled branch near 9.6 MHz, with clean cleanup and normal camera recovery.
The completed [receiver clock check](../kernel/IRIS-RXCLK.md) measured stable
enabled CSID3 near 240 MHz and PHY2 timer near 200 MHz, with zero packet/error
counts and clean camera recovery. The [startup/link audit](iris-startup-audit.md)
tracks the remaining uncertainties without changing sensor registers.

## Routing evidence

Firmware evidence uses the pinned DSDT, SHA-256
`014691f16291443cc5997098889d5881ed397501ea54ddcd091f1c81866488db`.
Linux register/node mappings below use kernel commit
`cc84cab9900ee4e7a3046b3756858e9832caee72`, particularly
`arch/arm/boot/dts/qcom/msm8994-camera.dtsi` and the camera_v2 CSID/CSIPHY drivers.

| Item | Evidence | What remains unresolved |
| --- | --- | --- |
| Iris receiver | CAMT exposes `0xfda08c00`, corresponding to Linux CSID3 | Packet reception has not been established |
| Iris PHY | Hardware preparation maps `0xfda0b400` and supplies PHY selector 2 / combo flag 1 | Physical reception remains unverified |
| Shared dependency | CAMT depends on CAMF in `_DEP`; the iris one-lane combo request is forwarded through the front interface | Normal-front recovery passed once; repeatability remains untested |
| Lane count and placement | The matched program uses one lane; the original combo path selects data lane 4 and clock lane 3 | Physical reception and polarity have not been measured |
| Format | The matched mode and phone readback both give `0x0112=0x0a0a` | Actual packet data type, virtual channel and delivered byte layout |
| PHY combo support | Linux supports mask `0x18` / upper mux nibble, with lane 3 serving as combo clock | Initial settle count has no measured working window |

There is no Linux physical PHY3 in this tree. A CSID number and a physical PHY
number are different selectors; CAMT's CSID3 must not be translated to PHY3.
The front sensor's known two-lane settings also cannot simply be copied to the
one-lane iris sensor.

The pinned original ARM iris driver has a receiver configuration structure at
VA `0x461554`. Its property dispatch at `0x402138` includes these handlers:

| Property | Handler | Stored information |
| --- | --- | --- |
| `0x4f` | `0x402972` | CSID selector, four-byte input, range 0–3 |
| `0x51` | `0x4029b4` | PHY selector and combo flag, eight-byte input; combo range 0–1 |
| `0x52` | `0x4029e8` | Four-byte selector stored at context `+0x3c`, range 0–3; caller diagnostics name orientation |

These handlers show that routing is configured separately from the sensor
register program. Initialization at `0x402daa` clears the fields; those defaults
are not the routing evidence. The caller is in the pageable hardware-preparation
routine, starting at `0x83d220`, rather than in the core camera service:

1. At `0x83d2f8`–`0x83d308`, it maps physical `0xfda0b400`.
2. At `0x83d33a` it takes the top byte of `CAMP.INFO`. The pinned firmware returns
   `0x00060000`, so that byte is zero. The default branch at `0x83d34c`–`0x83d356`
   selects CSID3, consistent with CAMT's MMIO resource.
3. At `0x83d37a`–`0x83d380`, it constructs the eight-byte pair `{2, 1}`. In the
   CSID3 branch, `0x83d3ba`–`0x83d3cc` passes this pair as property `0x51`, setting
   PHY2 and combo mode 1. Property `0x52` is then supplied zero. Earlier notes
   called that field a mux selector; the original caller calls it orientation,
   so it is not used as evidence for clock-mux programming.
4. The configuration path at `0x403f94` selects the one-lane combo case. The
   CSID lane construction at `0x41dabc`–`0x41dace` places selector 4 in its first
   data-lane field. The PHY-enable construction at `0x41dd02`–`0x41dd1a`, together
   with the one-lane handling around `0x41e554`, selects the upper pair of PHY
   lanes. Linux's matching combo logic makes lane 3 the clock and lane 4 data:
   lane mask `0x18`, CSID lane assignment `0x0004`.

The original iris driver opens the front-sensor interface through
`CameraMIPICSI2HAL_FrontSensorInit`, VA `0x41f34c`, and forwards one-lane combo
configuration through IOCTL `0x232003` at `0x41e55a`. This independently supports
the sharing arrangement. These are static code/firmware conclusions, not a
measurement of packets on the owner's phone.
Driver identity and provenance are in
[windows-driver-analysis.md](windows-driver-analysis.md).

## Receiver observation settings

The original CSID construction at `0x41ded8`–`0x41dee4` builds
`(phy << 17) | 0x1000f`; the CSID3 register copy at `0x41e4a4`–`0x41e4a8`
writes it to receiver offset `0x8` (`CORE_CTRL_1`). The Linux configuration
builds `(phy << 17) | 0xf`. This establishes a bit-16 difference, not its exact
semantics or a proven cause of the zero counters. Linux mainline v6.6's
`camss-csid-4-1.c` likewise streams without that bit but does not collect these
statistics; its stream setup does not validate our counter measurements.

Version 02 matches the original bit in the diagnostic owner helper and saves
the control-word readback. For PHY2 it should read `0x0005000f`. Sensor
programming and PHY lane/timing settings remain fixed. Readbacks additionally
cover CSID lane/format configuration, PHY power/combo/lane configuration and
the eight PHY IRQ status words used by the existing IRQ handler. No extra
IRQs, test generator or image DMA is enabled. The observations are sampled
before the sensor stop writes, including after a sensor-counter timeout.

The original statistics reader at `0x41f1e4`–`0x41f29c` exports the low 16 bits
of the ECC word at `0x98`; version 02 follows that width. Packet count at `0x90`
and CRC at `0x94` remain 32-bit. A physical signal and counter behavior still
need to be established on the phone.

## Linux integration boundary

The existing diagnostic owns only its sensor power/reset/clock votes and CCI
session. It does not own a CSIPHY, CSID, ISPIF or VFE session. The Linux
CSIPHY driver maintains both reference counts and lane masks; teardown with a
zero lane mask can expand to all lanes. A new receiver test must acquire and
release only its own resources through the existing camera driver interfaces.
It must not write MMIO behind those drivers or reuse an active front-camera
session. Camera services must remain stopped throughout the receiver/sensor
test, with restoration conditional on complete cleanup.

The [bounded receiver test](../kernel/IRIS-CSI.md) now initializes this PHY/CSID, configures
lane routing and RAW10 reception, then executes the existing one-shot sensor
start/stop. It saves packet/error observations before releasing the receiver
and unwinding power. Receiver failures remain distinct from the sensor's
unchanged-counter criterion. The initial settle count 20 is unmeasured; the
version 02 recorded configuration and status but no packets. Receiver diagnostics are useful
for link bring-up but do not prove a delivered image.

The first capture milestone then adds an ISPIF/VFE RDI path and returns a
bounded RAW10 buffer with checked dimensions, stride and byte count. A camera
descriptor, stream enumeration or interrupt alone does not meet that milestone.
IR remains outside this first-frame implementation.

## Clock and interface readback limits

`0x0136` and `0x0138` returned zero on build #5. The original Siiri startup
writes EXTCLK, and its unpause path writes mode select then `0x0138`. The
physical MCLK was not measured. Readback semantics for these two registers
remain unresolved; changing the hardware clock solely because they read zero
would not follow from this evidence.

The original generic static-information path writes `0x0111=2`; the matched
mode program contains `0x0111=0`. Builds #5–#7 read zero at start. The complete
original session's final ordering remains unresolved. The generic SMIA enum
alone does not establish that overriding the mode's value will fix reception.

Following the kernel #7 result and same-boot working-camera comparison, a
separate [explicit CSI-2 selection test](../kernel/IRIS-CSI2.md) is now provided.
The generic sensor configuration at `0x4165f2`–`0x4165fa` writes 2 to `0x0111`;
the call is reached through `read_static_information` at `0x40f2f0`. That
function is invoked from initial configuration (`0x40cac6`) and get-details
(`0x40ba10`). This identifies a real source operation but does not establish
the final write order for the original iris session.

The optional `csi2-once` comparison applies only that fixed interface selection
after the matched program, verifies its readback, then uses the same bounded
receiver/sensor cycle. It does not silently replace `csi-once` or change lane
routing, clock requests or settle count. On kernel #8 the selection latched,
but did not resolve the missing packets. This rules out that one write as a
sufficient fix in this setup; the overall cause remains unresolved.

## Source-derived settle comparison

Windows mode setup derives a 350.4 MHz DDR clock for the active 1920x1088
RAW10, one-lane mode from its 70.08 MHz pixel rate. The recovered settle
formula with the 200 MHz PHY timer gives 22 ticks (`0x16`). Temporary kernel
#17 applied that value, and both PHY settle registers read it back. The sensor
counter and CSID3 packet/ECC/CRC counts stayed zero; cleanup returned zero and
all camera services restarted. This comparison shows that the calculated
settle value alone does not explain the missing frames. See the [build
manifest](../kernel/builds/iris-csi-settle-01/manifest.json) and [phone
result](../kernel/builds/iris-csi-settle-01/phone-result.json).

The #17 sysfs summary had a hard-coded `settle=20` string. Its PHY register
readbacks were `0x16`; the source formatter is corrected locally for a future
build. No physical transmission or delivered image was established.

Kernel #18 followed the Windows dynamic sensor configuration by recording
`0x0110` before explicitly setting VC0. It was already zero; pre-start and
post-start snapshots remained zero, matching CSID3's configured CID0. Packet
and frame-counter observations stayed zero. This rules out a VC0 mismatch in
this reset/start path but says nothing about physical data activity. See the
[VC comparison record](../kernel/builds/iris-csi-vc-01/phone-result.json).
