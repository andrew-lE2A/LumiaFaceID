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
| Front receiver and PHY | CAMF exposes `0xfda08800` and `0xfda0b400`, corresponding to CSID2 and CSIPHY2 | This alone does not assign iris lanes |
| Shared dependency | CAMT depends on CAMF in `_DEP`; CAMT has no separate PHY MMIO resource | PHY2 sharing is a candidate, not a complete wiring map |
| Lane count | The matched mode program sets `0x0114=0`, one data lane | Physical data/clock lane positions and polarity |
| Format | The matched mode and phone readback both give `0x0112=0x0a0a` | Actual packet data type, virtual channel and delivered byte layout |
| PHY combo support | Linux supports combo mode; mask `0x18` selects the upper CSID mux nibble | Whether this is the iris route and its correct lane assignment |

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
| `0x52` | `0x4029e8` | Mux selector, four-byte input, range 0–3 |

These handlers prove that routing is configured separately from the sensor
register program. Their existence does not establish the caller's values.
Initialization at `0x402daa` clears these fields; zero-initialized defaults
must not be treated as a recovered cityman route. The sensor configuration
path around `0x403e3e` uses the fields and distinguishes ordinary and combo
PHY operation. The original iris driver also opens the front-sensor interface
through `CameraMIPICSI2HAL_FrontSensorInit`, VA `0x41f34c`. Recovering the
caller/configuration values remains necessary to complete this source trace.
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

The bounded receiver test should initialize the selected PHY/CSID, configure
lane routing and RAW10 reception, then execute the existing one-shot sensor
start/stop. Save packet/error observations before releasing the receiver and
unwinding power. The pinned CSID release path already logs packet, ECC and CRC
diagnostics; those diagnostics are useful for link bring-up but do not prove
a delivered image. Keep receiver failures distinct from the sensor's
unchanged-counter criterion so one does not erase evidence from the other.

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
