# Windows iris stack map

This is offline static analysis of the pinned WOA Lumia driver package and
previously recorded Lumia sensor evidence. No Windows binary was executed and
no phone state was changed. It maps which Windows component appears to own each
part of the path, and separates confirmed binary metadata from behavioral
inference.

## Inputs and provenance

The public source package is
[`WOA-Project/Lumia-Drivers`](https://github.com/WOA-Project/Lumia-Drivers/tree/b5af93f99ea800c28551727df55e57a07ba61a82),
pinned at `b5af93f99ea800c28551727df55e57a07ba61a82`.

| Component | Public package path | What inspection establishes |
| --- | --- | --- |
| Sensor driver | `.../Camera/Sensors/Iris/arm/qccamsensor_tertiarySMIApp8994.sys` | ARM32 SMIA++ driver; probe, CCI, DCC configuration and stream-control evidence is documented in [windows-driver-analysis.md](windows-driver-analysis.md) and [iris-startup-audit.md](iris-startup-audit.md). |
| Authentication UMDF driver | `.../Camera/Authentication/arm/CameraAuthentication.dll` | ARMv7 Thumb PE32, 118,784 bytes, SHA-256 `5e7be37803a0573727ea309a52d5f5e6569875485951ec56023f5d9175b5cd4e`. It has camera capture, frame handling, exposure, pulsing, IR-current and eye-coordinate interfaces. |
| Authentication INF | `.../Camera/Authentication/CameraAuthDriver_arm.inf` | Installs the ARM32 UMDF service and its runtime files. The ARM64 device ID maps to a null device; the ARM32 device ID maps to the real `umdf2\CameraAuthentication` device. |
| ARM64 authentication DLL | `.../Camera/Authentication/arm64/CameraAuthentication.dll` | PE32+ AArch64, 24,416 bytes, SHA-256 `75dd9dc3bdaab6b0af17e704b18a4e810bdaa2abf8afe918e9dff4abaa617746`. Its embedded PDB path is `LumiaNull.pdb`; imports are framework/trace support, with no camera, Media Foundation, or Icaros imports. It is the null implementation, not a port of the ARM32 capture stack. |
| Tertiary flash driver | `.../Camera/Flash/Tertiary/arm/qccamflashtertiary8994.sys` | Separate flash/illumination path. Its numeric guard rails are not validated eye-safety limits. |
| Siiri calibration | `.../Camera/Sensors/Calibration/0C086101.dcc` | Static sensor configuration and software calibration. It is not the matcher or the complete runtime pipeline. |
| ARC dependency | `Icaros.dll` (imported by `CameraAuthentication.dll`; extracted from the Windows Mobile FFU below) | The authentication module imports `IARCEngine` and `IKurreStash` APIs from it. These names show a separate camera/ARC component, but do not establish iris matching or template storage. |
| Icaros camera ESP support | [`WOA-Project/icaros_cam_esp`](https://github.com/WOA-Project/icaros_cam_esp/tree/73daf34734904dee9f27d7c5ed992353d92204bd) and `.../Camera/Thermal/icaros_cam_esp.inf` | The INF binds `ACPI\MSHW1010`, labels the device “Icaros Camera Extra Sensory Perception,” and installs a separate kernel driver. Its source handles camera power state, orientation/accelerometer/gyroscope data, thermal cooling, and focus-stat buffers. This is ancillary camera support; the code inspected does not implement iris streaming or iris matching. |
| Icaros thermal helper | [`WOA-Project/icaros_cam_esp_thermal`](https://github.com/WOA-Project/icaros_cam_esp_thermal/tree/67cfbde380464867425d066bdf7fe9299f6aa18c) | A virtual thermal-zone helper: camera ESP sends it camera power events and simulated temperature; the helper services thermal read requests and threshold notifications. Its INF calls the temperature a simulated machine temperature in tenths of kelvin. This is not a measurement of iris sensor temperature and provides no eye-safety or IR-current limit. |

Both authentication DLLs were retrieved from the pinned public repository
into `/private/tmp` for inspection. The ARM32 hash matches the provenance hash
recorded in [hardware.md](hardware.md); the ARM64 hash was computed from its
pinned package file. Neither DLL is included in this repository.

### Windows Mobile WinBio iris components recovered

The same FFU's `MainOS` image contains Windows Biometric Framework iris
sensor/engine components beyond the camera and ARC paths. The following
extracted ARMv7 Thumb PE32 files remain outside Git in `/private/tmp`:

| Component | SHA-256 | Static evidence |
| --- | --- | --- |
| `DeltaIrisEngineAdapter.dll` | `a38076cd597752c847d2da222e6210c3cd1800f43e873784fcaa1ac14d097059` | Exports `WbioQueryEngineInterface`; imports `irm2_*` frame, enrollment, identification, template, eye-info, camera-control and liveness functions from the algorithm DLL. Strings name enrollment/update/commit, duplicate checks, template loading, match-result storage, exposure control and anti-spoofing frame handling. |
| `IrisSensorAdapter.dll` | `40633018c9416fa03cf70ca9d28bc2490005b36256abdd1726002853ee648ab2` | Exports `WbioQuerySensorInterface`; imports `SensorsNativeApi.dll` sensor open/start/stop. Strings reference capture, sensor status/calibration, LED and ALS lifecycle/read operations. |
| `iris_mobile_v2.WindowsPhone.dll` | `9e8c53cdf428e4dbdc953ef548105aa4c18905595d739441ee68ffdc76862a43` | Exports 22 `irm2_*` APIs for preview/capture, frames, feature extraction, enrollment, identification, comparison, templates, eye info, liveness and UI hints. Strings expose per-eye processing, frame splitting, spoof checks and image dimensions (width 640–10000; height 480–10000). |

This corrects the earlier conclusion that no Windows iris matcher or
enrollment API had been found. The adapter imports and engine exports establish
the recognition component boundary and available operations. They do not
establish exact runtime call order, thresholds, liveness strength, template
protection or recognition quality. The DLLs were not executed.

The engine adapter's exact imports from `iris_mobile_v2.WindowsPhone.dll` are
`irm2_on_frame`, `irm2_init_identification`,
`irm2_get_identification_result`, `irm2_get_liveness_check_status`,
`irm2_set_liveness_check`, `irm2_get_version`, `irm2_init_enrollment`,
`irm2_get_ui_hints`, `irm2_get_enrollment_info`,
`irm2_continue_enrollment`, `irm2_get_template`, `irm2_get_eye_info`, and
`irm2_get_camera_control`. The algorithm DLL additionally exports
`irm2_compare`, `irm2_get_capture_info`, `irm2_get_features`,
`irm2_get_kind3_image`, `irm2_get_kind7_image`, `irm2_init_capture`,
`irm2_init_feature_extraction`, `irm2_init_preview`, and `irm2_preview`.
These names give a practical API inventory for future interface mapping; they
do not reveal structure layouts or argument semantics.

Static ARMv7 call-site tracing in `DeltaIrisEngineAdapter.dll` now locates
separate engine paths for enrollment and identification. The enrollment path
calls `irm2_init_enrollment` at `0x10007e54`,
`irm2_continue_enrollment` at `0x100081b6`, and
`irm2_get_template` at `0x100083cc`; a nearby enrollment-info path calls
`irm2_get_enrollment_info` at `0x10008474`. The identification path calls
`irm2_init_identification` at `0x10009d62` and
`irm2_set_liveness_check` at `0x10009dca`. In the frame-processing path,
`irm2_on_frame` is called at `0x1001bf5a`, and the result path calls
`irm2_get_identification_result` at `0x1001c1f8`. These addresses are image
addresses in the extracted adapter DLL. The call sites establish that the
adapter has distinct enrollment and identification orchestration and submits
frames to the imported engine; they do not recover the exact state machine,
argument meanings, enrollment acceptance thresholds, liveness policy, or
template protection.

The enrollment call-site disassembly gives a few additional boundaries without
exposing the proprietary state schema. `irm2_continue_enrollment` is called
only on a branch where an adapter field at offset `0xdc` equals
`0x0004001a`; the value's meaning is not established. A negative engine return
is logged as an enrollment-update error, while the adapter subsequently
queries enrollment status through its own helper. The separate
`irm2_get_enrollment_info` call passes a 12-byte output area, but its fields
and units are unresolved. Template retrieval uses `irm2_get_template` and has
its own return-code handling. Thus Windows exposes progress/status and
template retrieval as separate operations; the adapter trace does not justify
assuming that every accepted frame immediately yields a committed template.

The identification worker calls the imported `irm2_get_liveness_check_status`
at `0x1000742e` with a four-byte output area, on a state-gated path after
checking adapter fields at offsets `0x2d0` and the referenced state value.
The return/status value is passed to diagnostic logging. This confirms a
separate liveness-status query in the worker, but does not show what evidence
the algorithm uses or whether it gates an identity result. Separately, the
per-frame worker calls `GetTickCount64` immediately before and after
`irm2_on_frame` and records/logs the elapsed processing time. That timing is
algorithm latency, not a sensor exposure timestamp or a measure of LED/frame
synchronization.

`irm2_compare` is exported by the algorithm DLL but is not among the adapter's
static imports. I traced the adapter's only visible `GetProcAddress` call:
it loads `kernelbase.dll` and resolves `LocalFree` for buffer cleanup. There
is no call-site evidence that this adapter dynamically resolves
`irm2_compare`; its export alone does not show that WinBio calls it or explain
its comparison semantics. The adapter's statically imported
`irm2_get_identification_result` remains the confirmed result path.

The sensor adapter's strings show a format-negotiation path: it queries the
engine's preferred format, enumerates supported formats, selects one, then
starts capture. Capture data is fetched through
`IOCTL_BIOMETRIC_CAPTURE_DATA`, exported, and pushed to the engine. It also
queries sensor status and calibration through separate biometric IOCTLs. This
is stronger than a generic Camera2 preview contract: the Windows engine and
sensor adapter agree on a biometric capture format before streaming. The
actual format GUID and pixel layout are not visible from these strings and
remain a key reverse-engineering target.

Additional sensor-adapter labels cover cancel and reset; the engine adapter's
labels cover sample acceptance, frame analysis, enrollment and identification
workers, match-result reporting, spoof reporting and eye-info reporting.
Together, this supports a
component flow of sensor capture -> WinBio engine adapter -> `irm2_*` engine
calls -> biometric result reporting; it does not prove the exact threading or
buffer handoff sequence. The engine's validation strings require one or two
eyes and image dimensions of 640–10000 by 480–10000, and expose camera and
nominal resolution parameters. These are input constraints from compiled
assertions, not recommended capture settings. Pixel format, rotation values,
enrollment quality policy and match thresholds remain unresolved.

### Windows Mobile registry configuration recovered from the FFU

The `MainOS` image's SYSTEM and SOFTWARE registry hives were extracted
read-only. The extracted SYSTEM hive SHA-256 is
`4ba9aa297e95764ef6b16ca3811f4b4e761f334f66fd2d944125b7b0211e7aec`; the
SOFTWARE hive SHA-256 is
`3a56f93210545cefa37ff2adf7799d4a5b50c0d18f26e7f339b57bf8d1e50f15`. Both
hives remain outside Git in `/private/tmp`.

In `SYSTEM\\ControlSet001\\Services\\WbioSrvc\\Service Providers\\Iris`,
`BiometricType=16`. Microsoft's WinBio constants identify value 16 (`0x10`)
as `WINBIO_TYPE_IRIS`. Under `Virtual Sensors`, GUID
`{C690138D-2D36-4B72-9544-9DF240FA8222}` is named “Iris recognition sensor”
and has `Capabilities=128` (`0x80`), `SensorMode=1`, and
`SystemSensor=1`. Configuration 0 selects `IrisSensorAdapter.dll`,
`DeltaIrisEngineAdapter.dll`, and `WinBioStorageAdapter.DLL`, with a
16-millisecond capture interval, one-second presence lifetime, and database
ID `3081A9DF-8B0A-456E-8F7F-F53467FB5A2E`. The global active configuration is
`None`.

Microsoft defines `0x80` as `WINBIO_CAPABILITY_VIRTUAL_SENSOR`: the sensor
adapter manages its own connection to biometric hardware. The same persisted
mask does not contain `WINBIO_CAPABILITY_SECURE_SENSOR` (`0x100`). This is
evidence that this WinBio sensor registration did not advertise the secure
sensor capability; it does not settle whether a separate platform component
provided another protection mechanism. The recovered engine adapter's ordinary
`irm2_*` imports and this registry record therefore do not establish a
TPM-bound secure-match path. Microsoft's secure-sensor requirements describe
the missing capability and its isolated matching, secure input, PAD and
credential-release requirements ([WinBio biometric type constants](https://learn.microsoft.com/en-us/windows/win32/secbiomet/winbio-biometric-type-constants),
[capability constants](https://learn.microsoft.com/en-us/windows/win32/secbiomet/winbio-capability-constants),
[secure sensor requirements](https://learn.microsoft.com/en-us/windows/win32/secbiomet/sensor-requirements-for-secure-biometrics)).

The SOFTWARE hive key `OEM\\MMO\\Iris\\Sensor` contains the following
installed settings:

| Value | Data |
| --- | ---: |
| `ColdPeriod` | 120000 |
| `ExposureTargetAverage` | 70 |
| `ExposureTimeLimitMax` | 20000 |
| `InitExposureTime` | 20000 |
| `InitIso` | 250 |
| `IsoLimitMax` | 400 |
| `MinimumBatteryTemperature` | 2682 |
| `ViewportX`, `ViewportY` | 240, 570 |
| `ViewportWidth`, `ViewportHeight` | 475, 300 |

Static analysis now locates their consumer: `IrisSensorAdapter.dll` opens
`Software\\OEM\\MMO\\Iris\\Sensor` and queries these named values through
`RegQueryValueExW`. The adapter reads the exposure bounds, ISO bounds, target,
initial exposure/ISO and viewport fields during sensor initialization and
extended-info setup; the corresponding hive entries are all `REG_DWORD`.
The initialization routine reads these fields at image addresses
`0x100056ca`–`0x10005948`; it passes `InitExposureTime` and `InitIso` to
`SetInitExposure` at `0x10007888`. Those raw values enter the initial exposure
request, but their physical units cannot be inferred from the field names
alone. The code divides `ExposureTargetAverage` by 100 when the value is at
most 100; the installed value 70 therefore becomes a target fraction of 0.70.
The viewport reads occur in the extended-info routine at
`0x10006f88`–`0x100070ce`; all four integers are copied into its result
structure and logged as `Viewport: x,y widthxheight`.

This confirms that Windows consumes the persisted profile. It still does not
establish exposure-time units or the viewport's coordinate space, so do not
copy those numeric values directly into Android. `ColdPeriod` and
`MinimumBatteryTemperature` are also read by the adapter's environment check,
but their units and policy context remain unconfirmed and they are not safe
illumination or thermal limits. `ExposureTimeLimitMin`, `IsoLimitMin`, and the
bright-scene keys are queried by the adapter but are absent from this
extracted SOFTWARE hive; the corresponding local fields are zero-initialized
before the queries, so a missing value leaves zero at that point in the code.

In a separate DLL, `CameraAuthentication.dll`, the same text
`ExposureTargetAverage` occurs under the `Nips3A.Aec` trace category and is
passed as a label through an indirect call in frame/AEC code. That is a
diagnostic field and not the registry read described above.

The SYSTEM hive also registers `Origa2Auth` as a demand-start kernel driver
(`Start=3`, `Type=1`, image
`\\SystemRoot\\System32\\drivers\\Origa2Auth.sys`). Its extracted ARM32
binary is a 20-KiB ARMv7 NT-native driver with an embedded private PDB path
ending in `Origa2Auth.pdb`. Its imports are `BCryptGenRandom`, pool allocation
and release, Unicode-string copy, and WDF binding routines. The import table
does not identify a TPM, biometric, or secure-world interface. That absence
does not rule out dynamically resolved interfaces or a role mediated by
another driver. The `Start=3` setting also means this registry record alone
does not show that the driver was loaded during normal iris use. Its purpose
remains unresolved, and the service name alone is not evidence that it
authenticates iris matches.

Parsing the SYSTEM hive's DriverDatabase narrows the package binding:
`Origa2Auth.inf` is supplied by provider `MMO` and binds `ACPI\\MSHW1002` to
service `Origa2Auth`. Separately, Qualcomm's `qcbifbattdrv8994.inf` describes a
“Qualcomm BIF Battery Device” and installs service `qcbifbattdrv` for its PMIC
configuration. The values `AuthLibraryGuid`, `AuthInterfaceGuid`,
`AuthInterfaceVersion=0x00010000` and `QCAuthLibInUse=0` are specifically under
`ControlSet001\\Services\\qcbifbattdrv\\AuthLibrary`, not under the
`Origa2Auth` service key. This is a material lead that the matching GUIDs are
part of the BIF battery authentication configuration. It does not yet prove
that Origa2Auth services that battery driver, nor that either component is
part of iris capture or Windows Hello. These are installed registry/package
records, not evidence of runtime activity.

Static ARM32 Thumb disassembly adds a narrow WDF call-flow boundary. The
`INIT` routine at image address `0x408000` calls the framework function table
at byte offset `0x1d0` (slot 116 in Microsoft's published KMDF function enum),
consistent with `WdfDriverCreate`. The `PAGE` routine at `0x407000` calls
table offset `0x12c` (slot 75, `WdfDeviceCreate`), then offsets `0x328` and
`0x334` (slots 202 and 205 in that enum, typed-context lookup and object
reference). The same `PAGE` routine calls table offset `0x134` (slot 77,
`WdfDeviceCreateDeviceInterface`), so it registers a WDF device interface;
the call passes GUID `{54F544B9-B075-42B1-B170-3F3B3A433D91}` from image
address `0x404048` and a null reference string. A public exact-string search
found no match. The recovered SYSTEM hive contains an `AuthLibraryGuid` value
with this exact GUID, as well as a separate `AuthInterfaceGuid` value
`{3BD43166-179A-4FE6-90D6-916ED84D7D3C}` and the names `AuthInterfaceVersion`
and `QCAuthLibInUse` in the `qcbifbattdrv\\AuthLibrary` key. A second setup
routine at `0x401794` calls
`WdfDeviceAddQueryInterface` (slot 228, table offset `0x390`) with the distinct
GUID `{3BD43166-179A-4FE6-90D6-916ED84D7D3C}`, matching `AuthInterfaceGuid`.
Thus Origa2Auth registers the same `AuthLibraryGuid` and `AuthInterfaceGuid`
used by the separate Qualcomm BIF battery driver configuration. This points
more strongly to an authentication-library interface shared with that battery
stack than to the iris path, though the consumer and contract remain
unresolved. Neither GUID match alone proves biometric function. The device-add
path at `0x403be0` also constructs callback/config records and refers to a
framework table slot at offset `0x324` (slot 201).
This establishes a KMDF-style driver/device object setup and context handling;
it does not reveal a biometric match result, a trusted credential release, or
even the driver's device-interface consumer. The semantics of the callback
records and the interface consumer have not yet been recovered. The
embedded `WDF_BIND_INFO` at `0x405008` gives version major 1, minor 15, build 0,
and function count 444; the slot names are therefore checked against the
matching KMDF 1.15 enum. The call at slot 201 is `WdfDriverMiniportUnload`, but
its use in this driver's callback/config path remains unclear. This version
metadata strengthens the API mapping, not a claim about biometric or runtime
behavior. No driver was executed.

The mapped calls and offsets are recorded in
[`origa2auth-wdf-static-map-2026-11-05.json`](origa2auth-wdf-static-map-2026-11-05.json).

### WinBio framework contract and secure-sensor boundary

Microsoft's generic WinBio documentation describes the sensor adapter as
negotiating capture and forwarding a sample to the engine; the engine turns
that raw sample into a feature set, supports enrollment, and identifies against
stored templates. The generic enrollment workflow is
`SensorAdapterStartCapture` -> `SensorAdapterFinishCapture` ->
`SensorAdapterPushDataToEngine` / `EngineAdapterAcceptSampleData` ->
`EngineAdapterUpdateEnrollment`; commit includes a duplicate check and
`EngineAdapterCommitEnrollment`. The sensor capture IOCTL returns a
`WINBIO_CAPTURE_DATA` payload containing a `WINBIO_BIR`; its vendor-specific
data format is implementation-defined. These generic docs align with the
adapter strings, but do not prove the exact Lumia implementation details
([Microsoft adapter workflow](https://learn.microsoft.com/en-us/windows/win32/secbiomet/adapter-workflow),
[capture IOCTL](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/winbio_ioctl/ni-winbio_ioctl-ioctl_biometric_capture_data),
[capture payload structure](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/winbio_ioctl/ns-winbio_ioctl-_winbio_capture_data)).

Microsoft separately defines secure biometric sensors as requiring matching
inside an isolated environment, secure sample input that never exposes the
sample to the normal OS, presentation-attack detection, and secure credential
release. WinBio 4.0 adds `CreateKey` and `IdentifyFeatureSetSecure` for
TPM-backed authorization. The Lumia binaries identified so far expose ordinary
`irm2_*` frame, enrollment and identification calls. Static analysis of
`DeltaIrisEngineAdapter.dll` resolves its WBF interface version: its exported
`WbioQueryEngineInterface` returns the table at `0x10028040`, whose header is
`Version={3,0}`, `Type=2`, and `Size=0xac`. Microsoft defines the version
header as two 16-bit major/minor fields; WBF engine interface v4 adds
`CreateKey` and `IdentifyFeatureSetSecure`. Thus this recovered engine table
is v3.0 and does not expose the documented v4 TPM secure-match methods.
Together with the registry's `Capabilities=0x80` mask (no `0x100` secure-sensor
bit), this establishes that the registered WinBio iris path does not advertise
or implement Microsoft's documented v4 secure-sensor protocol. It does not
rule out a separate trusted mechanism outside this WBF interface; the role of
`Origa2Auth.sys` remains unresolved. These requirements are an Android security
bar, not evidence that Windows Hello used this exact secure interface
([interface version structure](https://learn.microsoft.com/en-us/windows/win32/api/winbio_adapter/ns-winbio_adapter-winbio_adapter_interface_version),
[engine interface](https://learn.microsoft.com/en-us/windows/win32/api/winbio_adapter/ns-winbio_adapter-winbio_engine_interface),
[secure-sensor requirements](https://learn.microsoft.com/en-us/windows/win32/secbiomet/sensor-requirements-for-secure-biometrics)).

The v3 engine's `QueryPreferredFormat` returns the registered-format pair
`Owner=0x001b`, `Type=0x0601`. Static disassembly of
`IrisSensorAdapter::QueryFormat` shows it calls that engine method, compares
the returned owner/type pair against the sensor's supported-format list, and
falls back to the same pair if no list entry matches. Microsoft defines this
pair as the basic iris image format under INCITS 379 (CBEFF format type
`0x0601`; owner `0x001b` is INCITS M1). This is a WinBio/BIR format
negotiation, not a CSI-2 or Android `ImageFormat` declaration. The engine's
`AcceptSampleData` implementation adds one detail: its internal routine reads
`VendorDataBlock.Size` and `VendorDataBlock.Offset` (BIR fields at offsets
`0x10` and `0x14`) and parses a vendor-defined record from that block.
Microsoft's `WINBIO_BIR` definition assigns those fields to the optional
vendor-data block. This shows that the standard owner/type negotiation is not
itself the sensor-byte layout; the engine consumes a separate vendor record.
The internal path checks that the vendor block is at least `0x24` bytes,
reads DWORDs at vendor-block offsets `+4` and `+8`, checks their sum against
`VendorDataBlock.Offset + VendorDataBlock.Size`, and passes a calculated
pointer into that block as the second argument to the imported
`irm2_on_frame` routine (adapter image addresses `0x1001bd84`, `0x1001bf5a`; import
thunk for `irm2_on_frame` at `0x1001d190`). This directly ties the private
vendor record to iris-algorithm input. The exact record schema and image
payload remain unresolved. In particular, the binaries examined here do not
yet establish the image dimensions, bit depth, byte order, or normalization.
Accordingly, this finding identifies the Windows biometric-record contract
but does not justify changing the Android RAW/YUV pixel interpretation
([registered-format structure](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/winbio_types/ns-winbio_types-_winbio_registered_format),
[BIR structure](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/winbio_types/ns-winbio_types-_winbio_bir),
[NIST CBEFF format table](https://www.nist.gov/document/ansi-nist2007tilton-cbeffpdf)).

At the adapter's `irm2_on_frame` call site (`0x1001bf5a`), the instruction
sequence explicitly places the parser-returned pointer in `r1` and zero in
`r2` immediately before the call. The adapter measures elapsed call time
around this operation. The zero-valued third argument is a static call-site
fact; its meaning is not identified, and it must not be treated as an image
length, rotation value, or pixel-format flag without the engine's ABI.

The aligned ARMv7 disassembly makes the pointer calculation explicit: it adds
the BIR's `VendorDataBlock.Offset` to the DWORD at vendor-block offset `+4`,
then passes that address to the algorithm; the DWORD at `+8` participates in
the preceding range check. These are private vendor-record fields, not
standard BIR members, so calling them a payload offset and payload length is
still a working interpretation rather than a recovered schema.

Using LLDB's ARMv7 decoder from the aligned address `0x10011690` (the export
RVA `0x11691` carries the Thumb bit), static analysis of `irm2_on_frame` shows
that a non-null frame argument enters a frame-preparation path. The routine
reduces the context value at offset `0x118` modulo 360, converts it to a
nearest quarter-turn index (add 45 degrees, divide by 90, then mask to 0..3),
and uses the configured dimensions at context offsets `0x10` and `0x14` while
preparing the frame. The resulting index is passed to the buffer helper below.
This establishes that the Windows algorithm accounts for four right-angle
orientations before processing. It does not establish the sensor's native
rotation, whether the input is packed or planar, or how channel values are
normalized; those still need to be recovered from the adapter's vendor record
and the rest of the frame path. The decoder must start at the aligned address:
starting at the odd Thumb-tagged export address produces misleading
instruction boundaries.

The rotation context value has a concrete initialization input. In the aligned
`irm2_init_identification` disassembly (`0x10011014`), the routine reads a
stack-passed settings pointer from entry `SP+8` (the third stack argument after
`r0`–`r3`), validates the first DWORD as `0x28` or `0x2c`, copies that
structure, then stores its DWORD at offset `+0x1c` into context offset
`+0x118`.

There is a static argument mismatch at the adapter callsite (`0x10009d62`,
through import thunk `0x1001d184`, whose IAT slot is `0x1001f1c4`). The call
setup explicitly writes the fifth and sixth arguments at outgoing `SP+0` and
`SP+4`; the engine reads its settings pointer from outgoing `SP+8`. In this
adapter function, the visible value left in `SP+8` is the earlier format-string
pointer `0x10020a58`, which resolves to `"Template count: %d context size: %d"`,
and there is no intervening store to that slot before the initializer call.
Those bytes cannot pass the engine's `0x28`/`0x2c` header check. This is a
disassembly-level inconsistency between these two binaries or their apparent
calling convention; it is not a phone measurement and does not prove that the
shipping Windows image fails. Verify the exact paired DLLs and ABI before
using this path to assign a camera rotation. The semantic name of the
settings-field `+0x1c` remains unproven.

The same routine calls a private buffer helper at `0x10011884` and
`0x100121a0` (helper address `0x1001055c`). The first call passes the original
`irm2_on_frame` buffer pointer; the later call passes a stack scratch buffer
at `sp+0x38`. Both pass the context dimensions from `+0x10` and `+0x14` and
conditional buffer candidates from `+0xb4` and `+0xb8`. Bits in `+0xe4` and the
presence of a value at `+0x108` determine which candidates are passed. An
assertion string in the same DLL names the operation as
`split_frame(pixels, ctx->width, ctx->height, ctx->pix[0], ctx->pix[1],
overlap, quadrant)`, matching the first call's pointer, dimensions, two
candidate buffers, and rounded orientation index. The caller sets per-view
dimensions at context offsets `+0xec` and `+0xf0`: for even orientation
indices, `(width + 300) / 2` by `height`; for odd indices, `width` by
`(height + 300) / 2`. The helper copies one view from axis offset zero and the
other from `(axis_length - s) / 2`, where `s = min(axis_length / 2, 300)`;
for axis lengths of at least 600, the view extent agrees with the caller's
`(axis_length + 300) / 2`, and the views overlap by 300 units. Below 600, the
helper's clamp makes the copied extent smaller than the stored per-view
dimension, so the meaning of those fields or the low-resolution path needs
further tracing. Bit 1 reverses buffer ordering for indices 2 and 3. The
subsequent enrollment/identification callsites pass `ctx->pix[i]` with these
per-view dimensions to per-index frame processors. This supports a two-view
split of one incoming frame (consistent with the code's two-eye processing
path), not eye-boundary detection or validated eye crops. The helper's
indirect calls go through the import-address-table entry at
`0x10015000`, which the PE import table identifies as `MSVCR110.dll!memmove`.
Its branches compute byte counts and offsets from the supplied dimensions and
flags, then copy contiguous ranges or repeated row-sized ranges from the
passed source buffer into the selected candidate buffers. Flag bit 0 selects
the contiguous or row-by-row branch; bit 1 swaps the two candidate-buffer
arguments. On the first call, the caller passes the rounded orientation index,
so those bits select contiguous versus row-wise copying by index parity and
swap the candidates for indices 2 and 3. On the later call, the argument is
formed as `(value << 16) + 0x14`; its low two bits are zero, selecting row-wise
copying without swapping. The helper's byte copies do not perform per-pixel
channel arithmetic. Although the assertion signature includes an `overlap`
argument, the helper body never reads its stack slot; its fixed 300 literal
drives the copy bounds. The `split_frame` name and two indexed pixel buffers
establish a two-view rectangular split, but do not identify the pixel format,
bit depth, or color/channel layout. The helper computes row offsets and byte
counts directly from the configured pixel dimensions, with no channel-count
multiplier; that is consistent with a one-byte-per-pixel input at this stage,
but does not prove whether the source is grayscale, a luma plane, or another
representation. The numeric overlap is 300 in the caller/helper calculations;
interpreting it as pixels follows from the engine's `image_width`/`image_height`
settings, though the lower-resolution clamp mismatch remains unresolved. This
also does not prove that this helper alone rotates or converts the image, and
does not justify an Android-side YUV plane-order or conversion change.

The Android probe has a deliberately limited diagnostic port of this result
in `WindowsIrisSplitGeometry.java`: it computes the two source rectangles and
reports per-rectangle luma statistics during a one-frame analysis. It uses the
Android sensor-orientation metadata as an experimental input because the
Windows context-field mapping is not yet verified. It does not materialize
Windows-style buffers, alter pixels, or feed the matcher. The Windows payload
format, normalization, crop, and orientation are still unresolved, so this
port demonstrates only that the geometry can be represented in the current
probe; it is not evidence that Android frames now match the Windows input
contract.

The sensor adapter's returned interface table is also version 3.0 (`Type=1`,
`Size=0x7c`). Its `PushDataToEngine` entry resolves to `0x1000eef9`. Static
disassembly shows that path reads the sample buffer and total byte count from
its sensor context at offsets `0x6c` and `0x70`; its helper takes the sample
length from buffer offset `0x10`, passes the sample beginning at buffer offset
`0x14`, and calls the engine interface's `AcceptSampleData` slot. Thus the
sensor adapter forwards a framed sample into the BIR parser; it does not
construct the iris image payload in `PushDataToEngine`. Following the calls
back from this handoff resolves both the writer and the prefix: the adapter's
capture worker issues `DeviceIoControl` with `0x00440014`, the WBDI
`IOCTL_BIOMETRIC_CAPTURE_DATA` control code, first using a four-byte output
buffer to obtain the required size and then repeating the request with the
allocated full buffer. The full request returns into the sample buffer held
at sensor-context offset `0x6c`; the returned byte count is held at `0x70`.
The `WINBIO_CAPTURE_DATA` layout is four 32-bit header fields at offsets
`0x00` through `0x0c` (`PayloadSize`, `WinBioHresult`, `SensorStatus`, and
`RejectDetail`), followed by `WINBIO_DATA` at offset `0x10`. Its `Size` is at
`0x10`, and its `Data` begins at `0x14`. The sample bytes passed to
`AcceptSampleData` are therefore a BIR beginning at byte `0x14`, not a raw
pixel plane. The Windows header definitions match the disassembled offsets
([capture IOCTL](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/winbio_ioctl/ni-winbio_ioctl-ioctl_biometric_capture_data),
[capture-data structure](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/winbio_ioctl/ns-winbio_ioctl-_winbio_capture_data),
[WINBIO_DATA structure](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/winbio_ioctl/ns-winbio_ioctl-_winbio_data),
[sensor interface](https://learn.microsoft.com/en-us/windows/win32/api/winbio_adapter/ns-winbio_adapter-winbio_sensor_interface),
[PushDataToEngine callback](https://learn.microsoft.com/en-us/windows/win32/api/winbio_adapter/nc-winbio_adapter-pibio_sensor_push_data_to_engine_fn)).

A separate layout check against Microsoft's `WINBIO_BIR` definition confirms
that its four `WINBIO_BIR_DATA` descriptors occur in order: header, standard
data, vendor data and signature. Each descriptor carries a 32-bit size followed
by a 32-bit offset, so the third descriptor is at BIR offsets `0x10` and
`0x14`; the disassembly's reads at those positions are consistent with
`VendorDataBlock.Size` and `VendorDataBlock.Offset`. This validates the outer
BIR field mapping only. The private words at offsets `+4` and `+8` inside the
vendor block remain vendor-defined, and their exact image-layout meaning is
not established by the standard ([Microsoft `WINBIO_BIR`](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/winbio_types/ns-winbio_types-_winbio_bir),
[`WINBIO_BIR_DATA`](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/winbio_types/ns-winbio_types-_winbio_bir_data)).

**Additional boundary from the complete callsite:** the validator returns the
address `BIR + VendorDataBlock.Offset + vendorRelativeOffset` after checking
`vendorRelativeOffset + vendorPayloadLength <= VendorDataBlock.Size`. The
caller passes that address as `irm2_on_frame`'s second ARM argument (`r1`) and
passes literal zero in `r2`; it does not pass the validated payload length.
The engine's frame path uses its configured width and height when splitting
the input into two overlapping views, and the split helper's byte arithmetic
does not multiply by a channel count or take a row stride. This supports the
inference that the payload consumed by `irm2_on_frame` is a tightly packed,
one-byte-per-pixel plane whose dimensions are implicit in the engine context.
It does **not** prove that the plane is sensor RAW, grayscale, or Y/luma, nor
that Android's Camera2 Y plane has matching rotation, crop, black level or
normalization. The validated length is a bounds check, not an engine argument;
the expected `width * height` extent still needs to be reconciled with the
vendor payload length before an Android adapter is written.

The `StartCapture` table entry dispatches according to sensor-context mode and
reaches the worker that performs the two-stage capture-data IOCTL. Its
completion path stores the resulting buffer and size into the sensor context.
`FinishCapture` then validates the returned capture record and its BIR vendor
block, including sizes, offsets, dimensions and enclosing-buffer ranges,
before returning the sample for `PushDataToEngine`. The indirect callback
around this work is a C++ concurrency task wrapper: it constructs and destroys
a `Concurrency::scoped_lock` around a task object's virtual operation. This
resolves the handoff owner and the 20-byte prefix. The remaining Windows-side
gap is the vendor BIR record schema and how its image bytes are normalized
before `irm2_on_frame`.

`LumiaSensorAlgorithmControl.dll` (SHA-256
`4b6983f5f4177d6b113c06cbea8cd78e1418dd20cb1a8054e39f4d27b28154d6`) exports
open/close/speed/speed-mode controls, but their semantics and connection to
iris processing are unknown. `Origa2Auth.sys` (SHA-256
`0b8fcbe9a420d660a69d9396fe49e0a565844ffba2c3f83208f36201ef851e4d`) registers
WDF interfaces whose GUIDs match `qcbifbattdrv\\AuthLibrary` values in the
SYSTEM hive. That points toward a BIF battery-auth interface; no iris-stack
consumer or trusted iris result path has been found. The adapter and engine PDB
identities were checked against Microsoft's public symbol server and returned
404; no matching symbols or source were recovered.

The CodeView GUID-age values are `cdc6fbf6-a3db-43de-b99c-d34290e94816-1`
for `DeltaIrisEngineAdapter.dll`,
`d90677b4-1031-47f6-bf8a-3c2245c8be67-1` for `IrisSensorAdapter.dll`, and
`75196382-d6c2-4061-b78c-4c97580a2137-1` for
`iris_mobile_v2.WindowsPhone.dll`. Their embedded PDB paths point to private
build workspaces; exact public symbol-server lookups for these identities did
not yield the PDBs.

### Windows Mobile retail FFU located

For comparison with the WOA driver bundle, the LumiaDB RM-1085 listing was used
to download the Windows 10 Mobile retail FFU
`RM1085_1078.0053.10586.13169.12742.034EE8_retail_prod_signed.ffu` to
`/private/tmp` (outside Git). The 2,995,126,272-byte file has local SHA-256
`3c6241fca0d302c0e462fa2ac438cfeb1f1ec6ef46b868a79e487ba19d61f4ef`. Its FFU
header identifies platform `Microsoft.MSM8994.P6211`, 128 KiB image chunks,
and manifest OS version `8.15.13169.318`; the manifest describes the 2016-06-21
update. The FFU was parsed read-only and the `MainOS` NTFS partition was
extracted to `/private/tmp/cityman-mainos.img`; no image was applied to a
device.

The FFU manifest establishes that this Windows Mobile image includes both the
camera-authentication package and the previously missing Icaros package. It
lists `CameraAuthentication.dll` (118,784 bytes) under
`MMO.Camera_Authentication.MSM8994` and `Icaros.dll` (3,323,248 bytes) under
`MMO.Camera_IcarosDll.MSM8994`, with the latter at
`$(runtime.system32)\Icaros.dll`. Both package CAB paths carry build
`1078.53.16236.35018`. The `MainOS` NTFS file record confirms the extracted
path `\Windows\System32\Icaros.dll`. Its unnamed NTFS data stream is 3,329,672
bytes, 6,424 bytes larger than the manifest's `size` field; the PE security
directory ends exactly at the NTFS stream boundary. Preserve this discrepancy
for a later comparison with the package CAB. The extracted file's local
SHA-256 is
`ac9d4aadd935cb48a171001e3d1d66da71a84fb34d92a787e230a667f82023a7`.
It remains outside Git at `/private/tmp/Icaros.dll`.

The FFU's matching `CameraAuthentication.dll` was extracted separately from
`\Windows\System32\drivers\umdf\CameraAuthentication.dll`. It is also
ARMv7 Thumb PE32, 118,784 bytes, with local SHA-256
`3f81977708e9907f043053037fef87f013cf9d9a2cf92b634e949bec45679e95` and a
2016-05-02 build timestamp. Its only named export is `FxDriverEntryUm`, and it
imports `Icaros.dll` methods for `IARCEngine`, `IKurreStash`, and
`IKurreStashPool`, plus `TImageInfo`. This directly connects the Mobile
authentication binary to the extracted Mobile Icaros implementation.

The WOA ARM32 authentication DLL has the same size and exported entry. Its
SHA-256 differs (`5e7be378...b5cd4e`), but the two import tables contain the
same 18 DLL dependency names and the same 86 named imports after normalizing
one CRT dependency: Mobile imports `MSVCR120.dll`, while WOA imports
`LUVCR120.dll`. This is strong evidence that both builds share the same
external capture/ARC interface. They are still distinct binaries; compare code
and data before assuming identical behavior.

A byte-level comparison of the recovered Mobile and WOA ARM32 files narrows
that difference further. Both are 118,784 bytes, and exactly four file-byte
positions differ: `0x150`-`0x151` in the PE checksum and `0x1a814`-`0x1a815`
in the CRT import string (`MSVCR120.dll` versus `LUVCR120.dll`). Their
`.text`, `.data`, `.pdata`, and `.reloc` sections are byte-identical; the only
other difference in `.rdata` is that two-character dependency name. The
capture/ARC implementation is therefore byte-identical between these copies
after normalizing the PE checksum and CRT import label. This makes the Mobile
call-flow analysis directly applicable to the WOA ARM32 module's machine code.
It still does not prove that the two OS images used the same registry values,
sensor firmware, Icaros implementation or runtime call sequence.
The hashes, changed offsets and section comparison are recorded in
[`windows-camera-auth-binary-comparison-2026-11-05.json`](windows-camera-auth-binary-comparison-2026-11-05.json).

Read-only PE inspection identifies an ARMv7 Thumb PE32 DLL with a 2016-05-02
timestamp. Its imports include `D3D11.dll`, `VCOMP120.dll` (OpenMP runtime),
`MSVCR120.dll`, and Windows timing/thread/file APIs. Its exports include
`IARCEngine`, `IARCEncoder`, `IARCJpegEncoder`, `IKurreStash`, `CNips3AAPI`,
`CNokiaAnalyzerAPI`, and Nokia image-algorithm interfaces. Embedded diagnostic
strings cover NIPS 3A statistics and NokiaAnalyzer; one field is named
`iRIStrengths`, whose meaning is unclear from the string alone. This establishes
that Icaros is a substantial Nokia imaging / analysis component with the API
surface used by `CameraAuthentication.dll`. It does not establish that
`IARCEngine` performs iris matching: there are no explicit iris enrollment,
template, or match method names in the inspected export names, and the opaque
engine's behavior still needs disassembly and call-flow analysis. The manifest
proves co-installation, not template ownership.

Additional internal diagnostic strings narrow the role of the ARC engine.
They name `CARCEngine::Initialize`, `LoadCameraTunigs` (spelling as stored),
`HasPipe`, `BeginTask`, `FeedImage`, output-buffer reservation/freeing,
`GetTaskSettings`, `EndTask`, and `ProcessInputFormat`. The same DLL contains
general ISP and image algorithms plus `CFrameAlgorithm_Run3AAECOnly::FindIrisTotalExposure`,
`IrisPct_P99/P95/P90`, and `EyeROI[0..1]` settings. This is consistent with a
camera image-processing engine that accepts frames and computes exposure from
iris-region statistics. The names do not establish iris identity matching.

In the Mobile authentication DLL disassembly, a setup path calls
`IARCEngine::New` at `0x1001014c`, then dispatches through the returned object's
vtable at offset `+4` at `0x100101c6`. It subsequently queries static
`IARCEngine::Release` and `Generation` functions, and a cleanup path calls
`IARCEngine::Delete`. The virtual method's name and arguments are not exposed
by the import table; the engine's `FeedImage` task path is the next useful
call-flow target. A later call at `0x10010290` dispatches through the same
object's vtable at offset `+0x14`, passing a pointer to a structure at
`this + 8` and the routine's second input argument. Since Icaros also contains the `CARCEngine::FeedImage` diagnostic name,
this is a plausible `FeedImage` slot mapping; it remains an inference until the object's vtable and the frame
structure are fully resolved. These addresses refer to the extracted Mobile
DLL, not to runtime measurements.

The embedded CodeView records also give stable PDB identities for future
symbol searches. `Icaros.dll` names
`D:\GIT\Camera_ImagingAlgorithms\IcarosDll\arm\Release\Icaros.pdb`
with GUID-age `e3d6b579-fa08-4042-829c-b2edf35ff7bf-2`. Both Mobile and WOA
`CameraAuthentication.dll` copies name the same PDB path
`e:\Build_e\st\1E708389_143\output\camera\camera_authentication\arm\fre\CameraAuthentication.pdb`
and share GUID-age `40cb8540-89f5-46c5-8990-22ddc9aeb932-2`. Neither PDB is
present in the extracted MainOS filesystem. Exact GUID-age lookups on
Microsoft's public symbol server returned HTTP 404 for both, so matching
private symbols are not currently available through that server.

Sources: [LumiaDB RM-1085 firmware listing](https://lumiadb.com/?model=RM-1085)
and [LumiaDB API documentation](https://lumiadb.com/developers). The original
sensor driver is cached under `/private/tmp/lumia-iris-notes/`.

## Evidence from the authentication component

The DLL imports Windows Media Foundation buffer functions, `DeviceIoControl`,
registry access, synchronization/threading APIs, `Icaros.dll` and `LUVCR120.dll`.
Its exported entry is `FxDriverEntryUm`; the ARM INF configures it as a UMDF 2.15
service with host-process sharing disabled, direct hardware access allowed,
and kernel-mode clients allowed. These are driver-package facts, not proof of
the exact Windows Hello runtime call order.

The PE contains these camera-connection and frame-handler names:

| Subsystem | Recovered names | Supported conclusion |
| --- | --- | --- |
| Camera lifecycle | `Open`, `Close`, `StartCapture`, `StopCapture`, `QueueForFrame`, `CancelQueuedFrame` | The authentication component opens a camera stack and manages asynchronous frame requests. |
| Stream setup | `GetSupportedCaptureFormats`, `SelectCaptureFormat`, `SetInitialVideoConfigToSensor` | The component negotiates a capture format and supplies an initial video configuration. Exact selected values and call sequence still need code/data-flow tracing. |
| Per-frame control | `SetExposureParameters`, `SetPulsingMode`, `SetIrLedCurrent`, `SetEyeCoordinates` | The component exposes controls for exposure, pulsing, IR current and eye coordinates. This supports a synchronized capture-control path; it does not establish safe current/timing values. |
| Frame processing | `CFrameHandler::Process`, `ParseAecResults`, `UpdateSensorExposureParameters`, `GetEmbeddedLineDetails`, `FormDebugTextToImageData` | It processes frames and updates exposure from frame/AEC data. Whether it performs iris recognition is not established by these names alone. |
| ARC adapter | `CArcHelper::InitializeController`, `CArcHelper::Process`, `CArcHelper::HandleArcResults` | There is an adapter between frame handling and a separately imported ARC engine. The acronym's expansion and algorithm are not established. |
| ARC API | Imports from `Icaros.dll`: `IARCEngine::New`, `IARCEngine::Generation`, `IARCEngine::Release`, `IARCEngine::Delete`, plus `IKurreStash`/`IKurreStashPool` allocation and deletion methods | `CArcHelper` calls into a separate ARC-related component. The function names and imports do not reveal whether it performs iris matching, camera image processing, or both. No enrollment, iris-template, or matching API is identified in this DLL alone. |
| Status/diagnostics | Event names include `TertiaryCameraRunning`, `TertiaryCameraInitializeStarted`, `TertiaryCameraInitializeDone`, `FirstFrameProvided`, `TertiaryCameraStart`, `FlashState`, `FlashPower`, `ExposureTimeUs`, and `PulseFlashFired` | The component tracks camera initialization, first-frame delivery and illumination/exposure state. These strings do not prove a particular event was emitted on this handset. |

The binary also contains registry/configuration names for `EyeROI[0..1]`,
`EyeROI.Count`, iris percentile statistics, `EyeStatsAecControl` thresholds and
slopes, `ExposureTime_Min/Max`, and `UseFlashOutOfFrame`. This points to a
frame-driven exposure controller using eye-region statistics, with external
eye coordinates supplied to the component. The meanings, units, defaults and
runtime values still require tracing the corresponding code and configuration
data. Do not copy those values into Android based only on their names.

The ARM32 Thumb disassembly of the extracted Windows Mobile copy
(`CameraAuthentication-mobile.dll`, SHA-256
`3f81977708e9907f043053037fef87f013cf9d9a2cf92b634e949bec45679e95`) also
resolves a narrow initialization boundary: the code path whose trace label is
`CCameraConnection::SetExposureParametersForInitialization`, beginning at
image address `0x10005dd0`, copies the first two 32-bit values from its input
structure into the connection's frame-state fields at offsets `+0x16c` and
`+0x170`. No
arithmetic or unit conversion occurs in that setter. This confirms that the
initial exposure/ISO pair is retained as supplied at this boundary, but does
not identify their units or how later AEC processing converts them into
sensor exposure and gain. In particular, `InitExposureTime=20000` must not yet
be interpreted as 20 ms from this evidence alone.

The same Mobile binary's `CCameraConnection::SetExposureParameters` method
(image address `0x10008e20`) copies five consecutive 32-bit input fields
unchanged into object offsets `+0x114` through `+0x124` and sets the byte at
`+0x128` to 1. There is no arithmetic in that setter before the copy. This
shows that the per-frame exposure update is queued as supplied at this API
boundary; it still does not identify the fields' units or establish which
later code turns them into sensor controls. A separate method named
`CFrameHandler::UpdateSensorExposureParameters` is present in the binary, but
the inspected portion at `0x1000c490` is dominated by property reads and
diagnostic logging; it does not yet expose that conversion path.

The illumination setters show how requests cross the capture component's
first boundary. `CCameraConnection::SetPulsingMode` (Thumb entry
`0x10005ab5`) forwards the mode through the `CFrameHandler` vtable at slot
`+0x18`; `CCameraConnection::SetIrLedCurrent` (`0x10005b75`) forwards its
value through slot `+0x20`. The receiving `CFrameHandler::SetPulsingMode`
(`0x10008f11`) stores the mode at object offset `+0xa8` and marks it valid at
`+0xac`. `CFrameHandler::SetIrLedCurrent` (`0x100090fd`) copies the supplied
32-bit value into `+0xb0`. These handlers cache frame/capture settings; they
do not issue `DeviceIoControl`, write PMIC registers, or toggle an LED.
Together with the `FlashCtrlPulseUs` and `UseFlashOutOfFrame` configuration
keys, this confirms the settings reach the frame handler. The later capture
worker submits the completed per-frame result record to the camera KMD as
described below. The KMD consumer and pulse edge relative to exposure remain
unresolved. Do not treat this as proof that the Android helper's “LED on until
buffer callback” timing matches Windows.

The frame-result construction path then consumes those cached values. At
`0x1000b98a`, pulsing mode `1` sets byte `+0x35` in its output record; the
other mode values clear it. The cached current is narrowed to one byte and
copied to record offset `+0x2c`, and the 0x88-byte result is passed onward.
This proves Windows carries the requested pulse state and current into its
per-frame camera-result path. It still does not identify the fields' units,
the receiver of that result, or the actual PMIC transition time relative to
exposure. See the capture-component observations in
[`windows-flash-driver-analysis-2026-11-05.json`](windows-flash-driver-analysis-2026-11-05.json).

The capture worker closes part of that gap. After forwarding a frame to the
frame handler, it calls a helper that invokes the handler vtable at `+0x08`
for a result pointer and byte count, then calls `DeviceIoControl` on the
camera connection's device handle (`+0x04`). The IOCTL is `0x0023432A`:
`FILE_DEVICE_VIDEO` (`0x23`), function `0x0CA`, `FILE_READ_ACCESS`, and
`METHOD_OUT_DIRECT`. The result pointer and length are the input buffer and
input length; the output buffer and length are null/zero. Thus the per-frame
record containing the pulse flag and current is submitted to the camera KMD
from the capture worker. The bytes returned by the call are logged on failure.
This confirms the host-to-camera-KMD handoff, but the receiving IOCTL handler
has not been located in the available binaries, so it does not prove that this
IOCTL directly switches the PMIC flash or establish pulse timing against
exposure. In particular, the separate KMD flash selector `0x26` is not proven
to be the receiver's implementation. Evidence and addresses are recorded in
the JSON analysis artifact.

The numeric `0xCA` match is weaker after tracing the qccamavs branch. Its
function at `0x40CC98` populates a property-result structure; selector `0xCA`
calls a vtable accessor at object offset `+0x78` to fill output. The unknown
selector trace resolves to `CCaptureFilter::PopulateNokiaCustomPropertyValue`.
The separate `SetNokiaCustomPropExt` path has inspected setter cases for
`0x65`–`0x69` and `0xCC`, but not `0xCA`. This does not match the DLL's
input-only frame-result submission. CTL_CODE function numbers and property
IDs are also distinct namespaces, so no link between these paths is
established. The remaining task is to locate the actual IOCTL receiver and
compare it with the DLL's `0x88`-byte input record. Details are in the JSON
analysis artifact.

The exact Windows Mobile FFU (`RM1085_1078.0053.10586.13169.12742.034EE8`,
OS version `8.15.13169.318`) was searched locally. Its `CameraAuthentication.dll`
matches the previously analyzed mobile binary by SHA-256, and its
`qccamflashtertiary8994.sys` matches the pinned tertiary driver by SHA-256.
The same MainOS partition contains `qccamavs8994.sys`, whose trace strings
identify `SetFlashPulses_Flash`, flash-result fields such as `FlashCtrlPulseUs`
and `UseHighPowerMode`, preflash start/completion callbacks, and frame dropping
while preflash is active. This is direct evidence that the original Mobile
camera KMD has a pulse/preflash scheduling surface. The embedded strings do
not identify whether that surface consumes the iris result record or establish
the pulse's phase relative to exposure; those links still need disassembly.
Hashes and the limits of this firmware inspection are in
[`windows-flash-driver-analysis-2026-11-05.json`](windows-flash-driver-analysis-2026-11-05.json).

The pinned tertiary-flash binary (`qccamflashtertiary8994.sys`, SHA-256
`58cf8c49d30756a5ddae896cf51aa1dd1ae2733217ee603aebacb44ce047c1c5`)
provides one more lower-stack boundary. Its ARM32 `CameraKMDFlashEvtIoControl`
dispatcher at image address `0x404c51` routes internal operation selector
`0x26` through the branch logged as `CameraFlashDriver_WhiteLED_SetFlash`.
That branch requires an associated configuration-size value of `0x2c`, copies
the flash configuration fields, and calls a registered function pointer. The
PMIC `Pmic_SetFlash` path at `0x4047b9` applies its own power validation, and
the binary contains separate flash callback and work-item timer/watchdog paths.
This confirms a camera-KMD callback route into the PMIC flash implementation;
it does not prove that `CameraAuthentication.dll` directly submits selector
`0x26`, identify the callback structure's field units, or show that the timer
edge is aligned with sensor exposure. The hashes, inspected instructions and
limits are captured in
[`windows-flash-driver-analysis-2026-11-05.json`](windows-flash-driver-analysis-2026-11-05.json).

Further disassembly of selector `0x26` shows that the dispatcher requires a
`0x2c`-byte request and forwards the seven 32-bit words beginning at request
offset `+0x10` as callback arguments. In the PMIC `Pmic_SetFlash` path, the
32-bit word at configuration offset `+0x0c` must be in the range 1 through
100. This is a structural bound only: its units and meaning are not recovered,
so it is not an LED-current or eye-safety setting that can be copied to
Android. The capture DLL-to-dispatcher link and the PMIC timer's phase against
sensor exposure remain the key unknowns.

The driver's indexed `FlashCallback` reads a signed schedule byte at entry
offset `+0x44` and reports `Turning Flash On`, `Turning Flash Off`, or
`Flash already ON, turning Flash Off`, while updating its internal ON/OFF
state and schedule index. This demonstrates a scheduled pulse-state machine
inside the flash driver. The callback body itself updates state and emits
diagnostics; it does not reveal the electrical LED edge, so exposure
synchronization still cannot be inferred from it.

The same binary includes per-LED and aggregate power-limit checks, watchdog
petting, accumulated heat-load accounting, and temperature/cooldown paths.
Those are PMIC/thermal fault protections in the driver; neither their values
nor the Windows driver's own current bounds are validated eye-safety limits.
Static presence also does not show which guard paths ran on this device.

The Mobile SOFTWARE hive also has `ExposureTargetAverage=70`, and the capture
DLL contains the same text. Static disassembly places that literal immediately
after the `Nips3A.Aec` trace category and shows it passed as a label through an
indirect trace-style call in frame/AEC code. This is evidence for an AEC
diagnostic field; it does not prove that the DLL reads the similarly named
registry value. The OEM viewport/exposure key names are not present as plain
strings in this DLL, so their consumer and units remain unlocated. Do not treat
the registry values as an Android tuning recipe until that data flow is found.

### The separate Icaros ESP kernel path

The open-source [`icaros_cam_esp` handler](https://github.com/WOA-Project/icaros_cam_esp/blob/73daf34734904dee9f27d7c5ed992353d92204bd/icaros_cam_esp/Icaros_KMD_ESP_Handler.c)
shows a camera-support interface for camera power, orientation, accelerometer/
gyroscope requests, focus-stat buffers, and per-frame temperature/orientation
sync. It forwards power and temperature notifications to a separate thermal
helper. The [`icaros_cam_esp_thermal` source](https://github.com/WOA-Project/icaros_cam_esp_thermal/blob/67cfbde380464867425d066bdf7fe9299f6aa18c/icaros_cam_esp_thermal/Icaros_KMD_ESP_TZ_Device.c)
implements a virtual thermal sensor that caches a supplied temperature and
notifies thermal clients when requested thresholds are crossed. Its INF labels
the configurable value “Simulated Machine Temperature” and specifies tenths of
kelvin. Here ESP means **Extra Sensory Perception**. This path may support
camera thermal policy, but it is separate from the sensor's MIPI stream and
does not provide validated IR emitter or eye exposure limits.

This source repo is named Icaros, but it is not the missing `Icaros.dll`.
No evidence so far proves that its ESP kernel driver performs iris matching or
that `IARCEngine` is a biometric matcher. The DLL import and the kernel ESP
driver must be treated as different components until a call/interface mapping
connects them.

## What the comparison changes

This clarifies the boundary between **capture** and **recognition**:

1. The sensor driver handles sensor discovery/configuration and stream control.
2. The WinBio sensor adapter provides the sensor interface, while the
   authentication UMDF and Icaros components handle camera/frame and ARC work.
3. `DeltaIrisEngineAdapter.dll` bridges Windows Biometric Framework to the
   distinct `iris_mobile_v2.WindowsPhone.dll` algorithm, whose API includes
   enrollment, identification, templates and liveness operations.
4. Windows Hello's enrollment storage, policy and final result path remain
   incompletely mapped. These binaries do not establish template protection or
   secure match-result transport.

The Windows image now gives us a concrete recognition API reference, but its
ARMv7 Windows DLLs cannot be loaded directly as Android libraries and do not
constitute an Android biometric implementation. Reverse-engineering the
adapter-to-engine data flow may guide a native design; recognition, template
storage, liveness and framework security still need independent implementation
and evaluation.

## Next offline reverse-engineering pass

1. Resolve the apparent `irm2_init_identification` stack-argument mismatch:
   verify the adapter/engine pair and calling convention, then trace the
   settings pointer and rotation field. Only after that, reconcile context
   rotation `+0x118` with Android `SENSOR_ORIENTATION`. Trace the BIR
   vendor-record fields from `AcceptSampleData` into `irm2_on_frame` and
   `split_frame` to identify the image bytes and validate whether the
   one-byte-per-pixel inference is correct before implementing the recovered
   overlapping two-view geometry in the Android diagnostic. Then map
   enrollment/identification call order, liveness decisions and template
   lifecycle. Keep analysis static; do not execute the Windows binaries.
2. Continue tracing the `IrisSensorAdapter.dll` registry values into sensor
   controls and frame callbacks to establish exposure-time units, viewport
   coordinate space, and their relationship to illumination requests. The
   installed exposure target is confirmed as 0.70 after normalization.
3. Compare Mobile `CameraAuthentication.dll` and `Icaros.dll` call paths with
   WOA builds, separately from the WinBio iris algorithm path.
4. Determine how the Windows adapters bind to kernel sensor/flash controls and
   which component owns template persistence and result protection.
5. Continue mapping `Origa2Auth.sys`'s WDF device callbacks, interface GUIDs,
   IOCTLs and package binding. KMDF 1.15 driver/device construction and object
   context use are confirmed; do not assign it a biometric or secure-match role
   without a consumer path.
6. Compare the recovered API contract with Android's camera path. Keep
   experimental matching outside Keyguard until matching, liveness, protected
   storage/result delivery, cancellation and lockout are evaluated.

## Upstream update: Windows-shaped RAW input and AE limits

The latest inspected `leojukic03/lumia-iris-notes` commit is
[`eb1fca3`](https://github.com/leojukic03/lumia-iris-notes/commit/eb1fca3cf9b9996595964153360089658f082255),
whose additions are static-analysis/experimental-code updates, not new phone
measurements. Its `android/tools/iris-capture/windows_frame.py` describes an
input approximation for the recovered engine: convert RAW10 to 8-bit by taking
the high eight bits, crop 300 columns from the left, then split into two
overlapping views (overlap up to 300 pixels), splitting across width for 0/180
and across height for 90/270, with the halves swapped for 180/270. The exact
Windows pixel normalization and Cityman rotation remain unknown.

The notes also add an opt-in sensor-plugin AE cap:

- maximum 667 sensor lines (about 20 ms),
- maximum 4× analog gain (ISO 400),
- no ISP digital gain.

The option is off by default. The commit describes this as matching Windows'
iris AE limits and notes that those limits were exercised off-device only.
These are exposure-policy settings, not safety limits and not a reason to
change the Camera2 diagnostic's exposure settings.

This repository has the independent offline converter
[`tools/iris-capture/windows_frame.py`](../tools/iris-capture/windows_frame.py)
for a captured RAW frame. Two explicitly saved IR-off RAW10 images were
retrieved and decoded at 1920×1088, row stride 2400, pixel stride 0, and
2,611,200 bytes. The manual init image spans 9–25 on the 8-bit scale. A later
AE image reports 75.004 ms / ISO 1042 (above the advertised 800 maximum) and
p95 52; it still shows only fine grain, with no eye detail. The converter's
0°/90° options select the engine's
orientation-dependent split axis/order; they do **not** rotate the pixel
array. The two cropped full-frame outputs were byte-identical, so those modes
do not establish Cityman's physical sensor orientation. Neither image
validates normalization, eye localization, or matcher input. Keep converter
outputs out of enrollment and matching. See
[`RAW10 orientation-mode review`](../android/iris-camera-probe/raw10-orientation-mode-review-2026-11-07.json).

The Mobile FFU, extracted ARM32 Icaros and WinBio iris components are available
outside Git. The main static-analysis gap is tracing the WinBio adapter-to-
algorithm buffers and call sequence, then matching Mobile capture/ARC
components to WOA counterparts. The WOA ESP source remains ancillary and does
not implement the recovered WinBio iris algorithm API.
