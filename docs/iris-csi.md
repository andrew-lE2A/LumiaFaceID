# CSI reception after the version 02 sensor test

Build #5 established that mode select latched and timing/geometry registers
could be read back. The counter stayed zero. The complete
[phone result](../kernel/builds/iris-stream-02/phone-result.json) records clean
stop/unwind and the owner's confirmation that both normal cameras still work.
Neither counter behavior nor mode select establishes packet transmission.

The next implementation needs a receiver configured before sensor start and
an observable result afterward. Another identical counter-only run will not
answer that question.

## Routing evidence

Firmware evidence uses the pinned DSDT, SHA-256
`014691f16291443cc5997098889d5881ed397501ea54ddcd091f1c81866488db`.
Linux register/node mappings below use kernel commit
`cc84cab9900ee4e7a3046b3756858e9832caee72`, particularly
`arch/arm/boot/dts/qcom/msm8994-camera.dtsi` and the camera_v2 CSID/CSIPHY drivers.

| Item | Evidence | What remains unresolved |
| --- | --- | --- |
| Iris receiver | CAMT exposes `0xfda08c00`, corresponding to Linux CSID3 | Packet reception on that receiver has not been tested |
| Iris PHY | Hardware preparation maps `0xfda0b400` and supplies PHY selector 2 / combo flag 1 | Physical reception remains untested |
| Shared dependency | CAMT depends on CAMF in `_DEP`; the iris one-lane combo request is forwarded through the front interface | Independent ownership and normal-front recovery require a phone check |
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
new build still needs its first phone test. Receiver diagnostics are useful
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

The original generic static-information path writes `0x0111=2` before the
matched mode program later writes `0x0111=0`. Build #5 read zero. The generic
SMIA enum alone is therefore insufficient justification to override the
matched mode to 2. Keep this ordering question explicit while tracing the
original configuration; no new register/clock variant is prescribed here.
