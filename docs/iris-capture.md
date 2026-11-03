# First-frame bring-up after sensor identification

The owner measured model `0x0861` through the separate diagnostic on build #3,
with `cleanup_errno=0`, `attempts=1`, `blocked=0` and all three camera services
restored. The owner also confirmed normal rear/front camera behavior afterward.
This validates one sensor power/reset/read/unwind cycle. It does not establish
repeatability, suspend recovery, delivered frames or an Android authenticator.

## Matching original calibration

The original Siiri population path hardcodes manufacturer `0x0c` and revision 1
around the measured two-byte model. Its resulting camera ID is `0C086101`.
This makes the original `0C086101.dcc` a source-supported match for the next
investigation; manufacturer and module revision have not been measured.

Original input: [WOA-Project/Lumia-Drivers, pinned calibration](https://github.com/WOA-Project/Lumia-Drivers/blob/b5af93f99ea800c28551727df55e57a07ba61a82/components/QC899X/Hardware/HARDWARE.CAMERA.MMO_8994/Drivers/Camera/Sensors/Calibration/0C086101.dcc).
Size: 496797 bytes. SHA-256:
`656c1dd9c1d5a818a232319ef16b8ea7fa1936ce9ea40ed9c241ddbcaee86a85`.
No calibration binary is included in this repository.

The offline extractor verifies that exact input before emitting a bounded
directory and static register summary:

```sh
python3 tools/inspect_iris_dcc.py /path/to/0C086101.dcc
```

It never executes a Windows driver or contacts a phone, and does not emit a
flashable artifact or a register replay script. `--output NEW_FILE.json` saves
a new file and refuses to overwrite existing evidence.

## Container and consumer evidence

Consumer addresses below refer to the pinned ARM sensor driver in
[windows-driver-analysis.md](windows-driver-analysis.md), image base `0x400000`.
The extractor checks data layout; these control-flow conclusions were reviewed
separately through Thumb disassembly.

At `0x414af0`, `cam_drv_SMIApp_extract_config_data_blocks` accepts formats 30/31.
For format 31, `0x414b4c`–`0x414b70` reads the block count byte at `0x34`, takes
the directory from `0x38`, and advances six bytes per entry. Each entry is a
big-endian 16-bit ID followed by a big-endian 32-bit size. Payloads follow in
directory order. This file has nine blocks:

| ID | Payload offset | Bytes | Recovered role |
| --- | --- | --- | --- |
| `0x0020` | `0x006e` | 123 | Opaque to this extractor |
| `0x0005` | `0x00e9` | 120 | Overrides of values returned by sensor reads |
| `0x000c` | `0x0161` | 24 | Software configuration, left opaque |
| `0x0000` | `0x0179` | 264 | Idle configuration records |
| `0xff00` | `0x0281` | 93 | Mode index 0 records |
| `0x0021` | `0x02de` | 8 | Opaque to this extractor |
| `0xfe9b` | `0x02e6` | 480962 | Opaque to this extractor |
| `0x0006` | `0x759a8` | 14991 | Opaque to this extractor |
| `0x000e` | `0x79437` | 98 | Opaque to this extractor |

The four bytes after the payloads are retained as an opaque trailer. Its
algorithm has not been established; the full-file SHA-256 identifies the input.

The dispatch table at `0x414bec` maps block 0 to the idle pointer, block 5 to
the override pointer (`0x414c46`), and IDs from `0xff00` to mode pointers
(`0x414d06`–`0x414d14`). `cam_drv_SMIApp_store_register_settings`, starting
`0x4137ac`, treats ordinary register records as a big-endian 16-bit address plus
one byte of data and stops at `00 00 00`. Software configuration has a separate
format and must not be parsed as register triplets.

The override block contains 39 records before its terminator. Its semantics
are established by `cam_drv_SMIApp_read8`, `0x40ed48`–`0x40edd2`: after the
sensor read, it searches the stored block-5 table and substitutes a matching
returned byte. These are not an initialization program. Replaying them would
attempt writes to addresses also used for static frame/capability information.

The idle block contains 87 records and the mode block 30, excluding terminators.
This establishes container boundaries, not a complete startup sequence.
`cam_drv_SMIApp_apply_register_settings` also handles command addresses beginning
at `0xfff9`, including delays and block loads. The extractor retains such values
as data and never interprets them as actions.

## Static mode facts and remaining capture work

Mode 0 contains these pairs, also used by the original mode-computation path
around `0x4121f0`–`0x41224c`:

| Registers | Static value | Interpretation |
| --- | --- | --- |
| `0x034c` / `0x034d` | `0x0780` | Output width 1920 |
| `0x034e` / `0x034f` | `0x0440` | Output height 1088 |
| `0x0112` / `0x0113` | `0x0a0a` | Uncompressed RAW10 encoding |
| `0x0114` | `0x00` | SMIA lane mode 0; one data lane |
| `0x0342` / `0x0343` | `0x0834` | Line-length register 2100 |

The manufacturer/model-specific branch at `0x412276`–`0x412298` uses output
dimensions as the window dimensions for `0x0c`/`0x0861`, rather than requiring
the usual crop-start/end register calculation. A generic SMIA implementation
must preserve this distinction.

The mode block does not include frame length (`0x0340/0x0341`), EXTCLK
(`0x0136/0x0137`) or mode select (`0x0100`). The original driver supplies dynamic
settings elsewhere. The presence of `0x0130/0x0131` must not be relabeled as the
EXTCLK pair merely because its value resembles a clock. Frame rate, link timing,
exposure and final startup/stop order still need a consistent reconstruction.
These dimensions describe stored data, not an observed image.

Next implementation work:

1. Trace the Siiri configuration path, including software configuration,
   dynamic frame/exposure/gain updates, and explicit stop/reset recovery.
2. Resolve CAMT's physical PHY, lane assignment, CSI mux and CSID route against
   the port's existing camera stack. DSDT's CAMT MMIO `0xfda08c00` names CSID3;
   the physical PHY and mux still need mapping. MSM8994's Linux tree has three
   physical PHY nodes, indexed 0–2. Rear/front routing must remain intact.
3. Integrate one consistent sensor program and userspace descriptor with the
   legacy Qualcomm camera pipeline. Keep IR controls absent for the first-frame
   test; an actual returned frame with known geometry/format is the acceptance
   criterion. Enumeration and CSI interrupts alone are insufficient.

The current kernel remains the tested ID diagnostic. The extractor was run on
the exact original calibration and produced the nine blocks and mode summary
above. Twelve tests use synthetic data to cover malformed directories, bounds,
record terminators, ambiguous mode registers, input identity and output-file
preservation. All 79 host tests passed at that extraction milestone.
The subsequent [sensor-stream diagnostic](../kernel/IRIS-STREAM.md)
now implements a bounded sensor program/start/counter/stop cycle. Its recovered
Siiri clock calculation, fixed test timing and shutdown path can be tested
before adding CSI/ISP reception. It does not yet return image frames.
