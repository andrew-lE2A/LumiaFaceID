# Startup and MIPI audit after the receiver-clock measurement

The [kernel #8 receiver-clock result](../kernel/builds/iris-csi-03/rxclk-result.json)
now includes the raw clock log and saved snapshots recovered directly over ADB
without retriggering the completed one-shot. Internal MCLK1 is near
9.6 MHz, CSID3 core near 240 MHz, and PHY2 timer near 200 MHz. All three clocks
can be present while the sensor engine or physical MIPI link is inactive.
The unchanged sensor counter is the origin of `-110`; receiver initialization
and release succeeded independently. No iris image has been delivered.

## Source inputs rechecked locally

The former cloud workspace is not needed for this audit. Original inputs were
retrieved into `/tmp`, verified with the existing hash-pinned inspectors, and
never executed. Neither binary nor calibration data is added to Git.

- ARM iris driver: SHA-256
  `0ea99897a1623afd7f165aa2943f2f69687c31dc42a123d6d21c2339ca8e78e5`.
- Calibration: SHA-256
  `656c1dd9c1d5a818a232319ef16b8ea7fa1936ce9ea40ed9c241ddbcaee86a85`.
- Linux `drivers/media/platform/msm/camera_v2/sensor/csiphy/msm_csiphy.c`
  at commit `cc84cab9900ee4e7a3046b3756858e9832caee72`: SHA-256
  `2e36e02a2f61204a27cdc29fe2745828ab2cb424cc01652c4735ecfd127a0dd0`.

Original binary/calibration URLs and provenance are in [hardware.md](hardware.md).
The [pinned Linux PHY source](https://github.com/giannoccarol/android_kernel_mmo_msm8994/blob/cc84cab9900ee4e7a3046b3756858e9832caee72/drivers/media/platform/msm/camera_v2/sensor/csiphy/msm_csiphy.c)
is the receiver implementation reviewed here. LLVM's ARM Thumb disassembler
was used for the following virtual-address ranges. Embedded literal pools and
jump tables must be read as data, even when `llvm-objdump -d` prints instructions.

```sh
python3 tools/inspect_iris_driver.py /tmp/lumia-iris-original.sys
python3 tools/inspect_iris_dcc.py /tmp/lumia-iris-original.dcc
python3 tools/inspect_iris_startup.py /tmp/lumia-iris-original.sys
llvm-objdump -d --triple=thumbv7-windows \
  --start-address=0x411d60 --stop-address=0x411f44 \
  /tmp/lumia-iris-original.sys
```

## Sensor startup: confirmed matches and unresolved branches

| Operation | Rechecked original code | Current diagnostic / remaining uncertainty |
| --- | --- | --- |
| Reset and EXTCLK | `0x40bf70` writes `0x0103=1`; `0x40bf7c` requests a 10,000-unit delay; Siiri branch converts clock input and calls write16 for `0x0136` at `0x40bfd6` | Diagnostic waits 20 ms and writes `0x099a`; no evidence here for increasing MCLK or rewriting EXTCLK repeatedly |
| Post-reset identity | Siiri branch calls read16 for model at `0x40bff6`–`0x40bffa` | Diagnostic rechecks `0x0861` before applying profile |
| Ordinary unpause | `0x411e64`–`0x411e78` writes `0x0100=1`, then `0x0138=1` | Same order already implemented; zero `0x0138` readback does not by itself identify a missing write |
| Pre-unpause hook | `0x411dc4`–`0x411dd4` conditionally applies stored settings with internal index 15 | Internal index 15 maps to DCC ID `0x0013`, absent from the pinned file (trace below) |
| Post-unpause hook | `0x411e82`–`0x411e88` conditionally calls a function pointer | Resolved to `0x405c50`, a conditional streaming-start logging callback (trace below) |
| Delayed auxiliary path | `0x411e8a` tests a software state field; only its nonzero branch delays, makes an auxiliary peripheral request, waits again, and writes `0x0c01=1` at `0x411ebe` | Delay producer resolved to mechanical-shutter handling; applicability to iris is not established (trace below) |

The unpause routine also has explicit other-model branches: manufacturer 9 or
15 with model `0x5e80` takes the extra `0x3c0d/0x3c22` sequence. That is not
evidence to apply those writes to model `0x0861`. Similar other-model checks
surround `0x0352/0x0353`. The current evidence does not support transplanting
these operations.

Internal apply indices are **not DCC directory IDs**. The apply routine at
`0x4138fc` indexes a stored pointer/count table in eight-byte slots. A hook
argument of 15 does not establish that DCC block `0x000f` exists or that opaque
block `0x000e` should be replayed. The matching DCC still has the same nine
blocks; read overrides and software configuration remain separate from the
117-register idle/mode program (351 bytes including addresses). The pre-unpause hook can now be narrowed further: the byte jump-table entry
for directory ID `0x13` at `0x414bf0 + 0x13` targets `0x414caa`, which stores
its payload pointer at output `+0x3c`. Configuration passes output at stack
`+0x28`; `0x40c83e` loads stack `+0x64` (that same field) and `0x40c850`–
`0x40c852` stores it as internal slot 15. The preceding loop at
`0x40c698`–`0x40c6c2` clears all 68 stored slots before loading this file.
Since this exact DCC has no `0x0013`, its direct configuration path supplies no
pre-unpause hook. That hook is therefore not evidence of a missing program in
our extracted idle/mode profile. Other runtime population paths still need consideration; an external-trigger
requirement remains unestablished.

The added `inspect_iris_startup.py` reproduces the callback literal/Thumb target,
pre-unpause directory jump-table target and matching absolute delay-field
addresses. It accepts only the original SHA-256. Its bounded Thumb decoders do
not execute driver code or infer the meaning of the callbacks; the intervening
stores and function semantics below remain separately reviewed disassembly.

## Callback and auxiliary-path follow-up

Direct ADB inspection found the phone still on kernel #8 with attempts=1,
`cleanup_errno=0`, receiver stage `released` and all three camera services
running. The saved clock log contains one stable enabled CSID3 sample and two
stable enabled PHY2 timer samples. All 20 sensor and 22 receiver pairs match
`iris-csi-03/phone-result.json`. No diagnostic or clock measurement was rerun.
The report's UTC timestamp comes from the Mac; the phone's saved file timestamp
is not used to date the experiment.

The post-unpause callback is now resolved through its actual registration:

1. At `0x40a698`, a literal load from `0x40a844` fetches Thumb pointer
   `0x405c51`; `0x40a69a` stores it in the callback argument structure at `+0x28`.
2. `0x40a6be`–`0x40a6c0` passes this structure to initialization `0x4171e4`.
3. `0x417248` and `0x41724e` copy argument `+0x28` into the callback table at
   `0x83b340 + 0x28`, the slot called at `0x411e82`–`0x411e88`.
4. The target routine at `0x405c50`–`0x405cc0` checks logging state and builds a
   logging event. Its UTF-16 message at `0x4250d0` is
   `Streaming started in still mode`. The reviewed callback contains no CCI,
   sensor-register, receiver or pulse-control call. It supplies no missing
   hardware-start operation for our diagnostic.

The delayed auxiliary branch's delay field is at absolute `0x831f08`:
`0x411e8a` accesses `0x831ecc + 0x3c`, while producer `0x4162ca` accesses
`0x831ec8 + 0x40`. Treating those two structure bases as identical would miss
this connection. The producer is within `cam_drv_SMIApp_ms_handle` at
`0x415ee8`; its entry/exit log names are referenced at `0x41633c` and
`0x4162e4`, and its diagnostics identify mechanical-shutter timing. At
`0x4162a0`–`0x4162ca`, the delay is saved conditionally on software state
`0x460d98 == 1`. The later unpause path consumes then clears it.

The direct call at `0x40d04a` is itself gated: configuration pointer at `+0x18`
must be present, capability/context `+0x14c` bit 0 must be set, and the request
bit 0 must be set. Request bit 1 determines whether an additional argument is
supplied. These are separate conditions from reading model `0x0861`. The
original context initialization at `0x411a06` clears the delay field. This trace
does not establish that the iris session requests mechanical-shutter handling,
and does not justify adding `0x0c00/0x0c01` or auxiliary peripheral writes.
The name/consumer trace is stronger than treating a nearby conditional branch
as a required Siiri initialization step; exact runtime applicability remains
unmeasured.

## Read-only local collection

From the project directory, with an authorized ADB connection:

```sh
mkdir -p reports
python3 tools/collect_iris_evidence.py --serial DEVICE_SERIAL \
  --output reports/iris-evidence-new.json
```

The collector only reads saved iris sysfs results, existing receiver-clock logs,
`/proc/version` and the three camera-service states. It never reads the private
profile, live sensor registers or debug-clock `measure` controls. It refuses an
existing output file, malformed/incomplete clock logs, unexpected log paths,
failed reads, or a changed diagnostic result during collection. Reports omit
the ADB serial and stay in the ignored local `reports/` directory. A missing
saved clock log is represented by an empty list, not fabricated measurements.
The currently recovered report is `reports/iris-csi-03-adb-evidence.json`.

## Receiver: what the source actually establishes

`msm_csiphy_lane_config` explicitly selects the upper mux nibble for combo
mask `0x18`, writes `csid_core << 4`, and makes the first enabled lane the combo
clock in the 20 nm path. Its power/mode construction and lane misc writes
agree with the existing `0x30`, `0x31`, `0x10`, `0x04` and `0x08` readbacks.
This independently checks the software configuration; it does not verify
physical lane polarity, a clock transition or high-speed data reception.

The PHY IRQ handler reads eight status words and **clears each value it reads**.
The diagnostic samples those same words without clearing them. Consequently,
a snapshot is not a cumulative event log: an IRQ can consume a status between
snapshots. The recorded changes in words 3/4/6 are real saved values, but this
source supplies no bit-name decoding and cannot distinguish valid HS traffic
from idle/setup/error transitions. Do not label them PLL lock, stop-state or
packet evidence without a matching register definition.

The settle value is written directly to lane CFG3, with possible integer
rescaling when a lower timer rate is selected. The measured timer near 200 MHz
and saved value `0x14` constrain that question; they do not establish the
analog settle interval or a working window. In particular, `20 / 200 MHz =
100 ns` is arithmetic, not a verified hardware encoding. Do not start a settle
sweep before recovering that encoding and a source-supported transmitter rate.

Working front/rear cameras validate packet counting on CSID2/CSID0. They still
provide no positive control for CSID3's combo input. RAW10/VC0 setup readback
also cannot establish the actual transmitted VC/data type. A CSID test generator
could validate a downstream counter/path only; it would bypass the sensor and
PHY and cannot establish an incoming signal.

## Next discriminating work

1. Check the remaining mode/PLL programming and original Siiri dynamic settings
   against the exact calibration. The resolved logging hook and conditional
   mechanical-shutter path supply no evidence-backed new startup write. Record
   each operation, condition and order before proposing a comparison.
2. Recover matching PHY status definitions and timer/settle encoding. If adding
   instrumentation, collect events through the owning driver's existing IRQ
   handler and preserve cleanup; avoid competing MMIO reads/clears or enabling
   new interrupts merely to obtain activity.
3. If source tracing leaves sensor-pin MCLK or MIPI lane activity unresolved,
   an electrical observation is needed to distinguish pin delivery, absent HS
   output and receiver acquisition. Internal debug clocks cannot substitute for
   this. Keep any observation independent of IR illumination.

No new phone run or kernel build is requested by this audit. Repeating the
completed clock/interface test would not resolve these branches. Any eventual
comparison remains one-shot on a fresh `fastboot boot`, with camera services
stopped, explicit sensor/receiver cleanup and both normal cameras checked after
restoration. Preserve the original boot backup and private profile. IR remains
disabled; authentication and ISPIF/VFE image delivery remain future work.

## Local validation

The read-only collector was run against the connected Lumia on the existing
kernel #8 boot. Its recovered samples/readbacks are in `rxclk-result.json`;
the full local capture stays under `reports/`. The startup-link extractor was
run on the hash-pinned original driver and reproduced the addresses above.
Host tests cover interrupted/invalid collection, changed results, hostile log
paths, existing evidence preservation, and bounded Thumb literal/jump-table
mapping. These checks do not establish sensor transmission or replace a kernel
build/phone test for any future runtime change. No runtime driver source changed
in this follow-up.

## Subsequent local hardware checks

Kernel #9 adds only five programmed-clock word readbacks; its one-shot still
returns zero sensor-counter changes and zero CSID3 packets, with clean cleanup.
See [complete clock results](../kernel/IRIS-PLL.md). A separate DTB-only
[front-camera CSID3 control](../kernel/IRIS-CSID3-CONTROL.md) also returns zero
packets from the otherwise working front sensor. Receiver routing/configuration
therefore remains unresolved independently of iris startup. No new startup
write follows from either observation. Both comparisons used temporary boots;
IR stayed disabled and development remains local.
