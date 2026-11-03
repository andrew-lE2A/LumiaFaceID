# Original iris driver: static probe evidence

Research date: 2026-11-03. This is offline analysis, not a hardware test or a
Linux sensor implementation. No Windows binary was executed or incorporated
into this repository.

## Reproduce the data extraction

Use the original ARM driver from the pinned public source in
[hardware.md](hardware.md). Its size is 410112 bytes and SHA-256 is
`0ea99897a1623afd7f165aa2943f2f69687c31dc42a123d6d21c2339ca8e78e5`.

```sh
python3 tools/inspect_iris_driver.py /path/to/qccamsensor_tertiarySMIApp8994.sys
```

The tool uses Python's standard library. It verifies the exact input hash,
maps PE32 sections and extracts bounded probe descriptors as JSON. It rejects
other binaries; there is no checksum override. It does not download files,
load a Windows driver, contact the phone or produce a flashable artifact.
`--output NEW_FILE.json` saves a new report without overwriting an existing file.

This extractor verifies data layout. The control-flow interpretations below
come from separate static ARM Thumb disassembly; the tool does not independently
verify those interpretations.

## Tertiary probe descriptors

The ARMNT PE image base is `0x400000`. Its `.rdata` section has RVA `0x35000`,
raw offset `0x33c00` and raw size `0x9200`. The tertiary table is at RVA
`0x3a168`, file offset `0x38d68`. Each descriptor is `<HBBI>`: register,
slave-address field, unused byte, register-address type. Three descriptors
are followed by an eight-byte zero terminator.

| Order | Driver branch label | Slave field | Probe register | Register-address bytes |
| --- | --- | --- | --- | --- |
| 1 | Siiri | `0x6c` | `0x0000` | 2 |
| 2 | Vespa | `0x78` | `0x00f0` | 1 |
| 3 | generic SMIA++ | `0x20` | `0x0003` | 2 |

Primary and secondary tables at RVAs `0x3a058` and `0x3a518` contain the same
three candidates in a different order: generic SMIA++, Siiri, Vespa.
These are supported driver candidates, **not a measurement of the physical
iris sensor's address or model**.

## Selection and read semantics

Addresses below are virtual addresses with the image base above:

- `cam_drv_ctrl_on`, `0x417522`–`0x417538`: the role/configuration field
  equal to 2 selects the tertiary table via literal `0x417630`.
- `cam_drv_ctrl_query_cam`, beginning `0x417720`: the common read wrapper
  is called at `0x4177b6` and `0x4177d4` for a candidate. The later call's
  return status gates success at `0x4177e2`; no fixed returned-byte chip-ID
  comparison was recovered in this selection path.
- The selected candidate address is subsequently used to choose the Siiri,
  Vespa or generic SMIA++ population path. An ACK/read success is therefore
  insufficient evidence of a particular physical part.
- The tertiary path passes logical argument 1 to this generic query routine.
  It is **not evidence of CCI hardware master 1**.
- The SMIApp read wrapper at `0x405800` rejects odd address fields and logs
  that it requires an eight-bit I2C address with the read/write bit cleared.
  It passes that byte through the peripheral request. The inspector preserves
  the original field rather than silently treating it as a Linux seven-bit
  address or a Qualcomm CCI SID.
- The peripheral interface's address-type code 1 uses a byte register
  address; code 2 uses a halfword register address. Those codes are not the
  number of bytes returned by the sensor.

The Siiri population path at `0x417e58` reads the model at register `0x0000`
using address `0x6c`, then uses manufacturer `0x0c` and revision 1 to form a
camera ID. This is a useful lead for comparing calibration metadata; it does
not establish which population path the user's phone actually takes.

The public `Camera/Sensors/Calibration/0C086101.dcc` file has SHA-256
`656c1dd9c1d5a818a232319ef16b8ea7fa1936ce9ea40ed9c241ddbcaee86a85`.
It contains readable `Jopo_Foxconn` descriptions and an initial-exposure note.
Its filename is consistent with the Siiri ID formula if the runtime model were
`0x0861`. This is a candidate association only: neither the filename nor that
formula proves that this phone's iris sensor responds with that model. Apparent
register records in the calibration need their format and consumer semantics
validated before any attempt to turn them into sensor writes. Subsequent phone
testing now measured model `0x0861`; [iris-capture.md](iris-capture.md) records
the ID-formula association and the recovered block roles/static mode. The
manufacturer/revision constants remain unmeasured.

Additional static evidence narrows the role of this candidate: at virtual
addresses `0x4088dc`–`0x4088f8`, startup explicitly checks for model `0x0861`
and manufacturer `0x0c` before creating the peripheral-controller/queue objects
used by the IR/GPIO pulse path. This is stronger evidence than the filename
alone, but remains a code-path condition rather than a measured chip ID.

## CCI route resolved from firmware and platform code

The platform driver evaluates `CAMP.INFO` (platform virtual address `0x401aa8`)
and stores its integer result in the device context. The iris driver retrieves
it through IOCTL `0x23202f` into global `0x460dc8`. The pinned DSDT's method at
lines 46374–46377 returns `0x00060000`.

Iris session initialization at `0x41fdc4` uses bit 17 for the primary session
and bit 16 for the secondary/tertiary session. Platform request selector 1
uses the latter session. Bit 16 is clear in `0x00060000`, selecting session ID 1.
Its platform descriptor at `0x41b1a4` has controller group 0, mapping to the CCI
register block at offset `0x100`: **physical CCI master 0**. The primary bit 17
is set, selecting session ID 3/group 1/offset `0x200`, or master 1. This agrees
with the independently documented rear-master-1/front-master-0 layout.

Source identity for this trace:

- `Platform/arm/qccamplatform8994.sys` SHA-256:
  `6ae3eb8078998b3d4e75200c671b90c5e5f385168014c70465941bfad4e90aa2`.
- Pinned DSDT SHA-256:
  `014691f16291443cc5997098889d5881ed397501ea54ddcd091f1c81866488db`.

This is source/firmware-derived wiring evidence. It does not prove the physical
sensor has powered up or responded on the user's phone. In particular, a NACK
without correct CAMT power/reset does not establish sensor absence.

## Illumination evidence

The pinned `camcalibration.inf` and Cityman `SOFTWARE.reg` configure
`SOFTWARE\OEM\MMO\Camera\TFF` with `Module=7` and `PMICType=1`.
These values concern tertiary-flash configuration, not sensor model or safe
IR operating levels. The INF's `I2cFreqKhz=1000` setting belongs to `RFC`
(rear camera); it must not be copied to an iris configuration.

The original tertiary-flash ARM binary contains explicit
`tff_assist_current_cfg` and `tff_ir1_assist_current_cfg` diagnostics at file
offsets `0x306b0` and `0x306e8`. It also contains pulse validation, watchdog,
heat-load and cooldown paths. This supports an original PMIC/IR-assist control
path but supplies no validated numeric illumination limits. The `.dfc` loader
is part of the flash path; a `.dfc` filename must not be assumed to identify
the image sensor.

## First hardware probe completed; capture remains

The owner ran the separate iris-id-02 Linux diagnostic once. It read model
`0x0861` on master 0/SID `0x36`, with clean unwind and unchanged normal cameras
after the camera services restarted. No stream or illumination was commanded.
This establishes the first model read, not repeatability or frame acquisition.

The next implementation needs the complete initialization program, dynamic
timing/exposure updates, CSI routing and actual returned frames. The matching
calibration's mode block is only part of that program. Optical illumination
limits and Android enrollment/matching remain separate requirements.

The static inspector still reports supported candidates rather than turning
offline bytes into hardware observations; the measured result is recorded
separately in [device-baseline.md](device-baseline.md#iris-sensor-model-confirmed).
