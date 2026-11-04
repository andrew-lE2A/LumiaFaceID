# Windows versus Android iris startup

This compares the hash-pinned Windows ARM sensor driver and Cityman CAMT
firmware with the current Linux diagnostic. It is static source analysis plus
previously recorded phone observations; it does not execute the Windows driver
or change device state. Driver, DCC and firmware provenance is in
[`hardware.md`](hardware.md), and detailed instruction-level Windows traces
are in [`iris-startup-audit.md`](iris-startup-audit.md).

| Startup phase | Windows evidence | Android diagnostic | Assessment |
| --- | --- | --- | --- |
| Controller and address | CAMT session maps to physical CCI master 0. Siiri probe uses eight-bit address field `0x6c`, 16-bit register address, model register `0x0000`. | CCI master 0, seven-bit SID `0x36`, word register address. Phone read model `0x0861`. | Address and controller conversion are consistent; sensor identity read succeeds. |
| Board power/reset | CAMT declares LDO17 2.8 V, LVS1 1.8 V, SMPS3 1.3 V, LDO3 1.2 V, and BOOST_BYPASS1 4.0 V. GPIO102 is the reset/shutdown control. | Enables the four sensor rails, checks fixed board voltages, asserts GPIO102 low and releases it high. No boost rail is requested. | The four sensor rail mappings and reset polarity align with available evidence. The boost resource’s startup role is unresolved; it must not be enabled without proving it is needed for the sensor rather than the illuminator. |
| Software reset and MCLK | Siiri writes `0x0103=1`, waits 10 ms, then writes the converted 9.6 MHz value `0x099a` to `0x0136`. | Kernel #21 used 20 ms; kernel #22 uses 10 ms and writes the same clock value. Internal MCLK branch measures about 9.6 MHz. | The source-derived 10 ms comparison is now complete; the sensor-pin clock itself remains unmeasured. |
| Post-reset identity | Siiri reads model `0x0000` again after reset and EXTCLK. | Re-reads and validates `0x0861` before applying the stream profile. | Same checkpoint succeeds. |
| Static mode setup | Windows applies 87 idle and 30 mode records from the matched DCC: 1920×1088, RAW10, one data lane, line length 2100. | Applies the same 117-record profile, then fixed frame/exposure/gain settings. Readbacks match. | No missing static mode record or per-module NVM setting has been identified. The bounded NVM header read found no sensor config entries. |
| CSI interface and VC | Windows `sensor_config` explicitly selects CSI-2 and supplies VC and lane count. Its ordering relative to mode configuration is not fully recovered. | Selects CSI-2 and VC0 after the mode program. Sensor already read VC0; writing it again did not change the result. | Selection values match current receiver setup, but the full Windows call ordering and actual lane transmission remain unverified. |
| Stream start | Windows unpause writes `0x0100=1`, followed by `0x0138=1`. | Uses the same write order. | No start-order discrepancy found. |
| Stop | Windows and Linux path stop the sensor through mode/control operations; Linux additionally asserts GPIO reset and unwinds its owned resources. | Attempts group-hold release, control/mode stop, asserts reset, and releases CCI, clocks and regulators. | Linux cleanup succeeds in the recorded trials. |

## What the comparison says

The 10 ms Windows Siiri reset delay was tested on kernel #22 with all other
settings held to the kernel #21 settle=22 trial. The model and register
readbacks matched; the frame counter, CSID packet/ECC/CRC counts and PHY status
were unchanged. The sensor still returned `-110` at `stream-test`, with clean
cleanup and all camera services restored. The reset-delay difference is not
the cause of the current no-frame result. See the
[kernel #22 record](../kernel/builds/iris-reset-10ms-01/phone-result.json).

The Windows driver does not read back `0x0136` in the traced startup path. The
Android read returns zero, while the CCI path reads the model and ordinary
profile registers correctly. Therefore the zero `0x0136` readback alone is not
proof that the EXTCLK write failed. Internal MCLK measurement likewise does not
prove a signal reaches the sensor pin.

The sensor-side sequence is not the only unresolved branch. A newer temporary
DT control added `camss_csi3phy_clk` to the CSID3 clock list and routed the
working front camera through CSID3. The preview produced 416 frames and CSID3
counted 1,094,240 packets with no ECC or CRC errors. This establishes a working
lower-lane CSID3 path when that gate is enabled. On the same boot, the iris
upper-combo trial still timed out: the pre-stream sensor counter was zero, all
16 samples stayed zero, and CSID3 counted no packets. See the
[front-control result](../kernel/builds/iris-csi3phy-front-control-01/phone-result.json).

## Next source-backed investigation

The timing comparison and available clock-gate trials did not reveal a sensor
startup fix. The remaining source-backed lead is to recover the exact CAMT
power/reset and CSI setup ordering, including which execution context enables
the upper-combo route. The lower-lane positive control means CSID3 itself can
receive a valid stream with the CSI3 PHY gate enabled, but it does not validate
PHY2's upper combo lanes or the iris sensor's MIPI output. Compare the iris
driver's complete register/CCI transaction order and CAMT power sequence before
changing sensor registers. CAMT's additional boost rail may serve the
illuminator and must not be treated as a sensor rail without source proof; do
not replay opaque DCC/NVM blocks or enable boost based on the current evidence.
