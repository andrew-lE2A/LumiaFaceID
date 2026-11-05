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

The same FFU's `MainOS` image contains a complete iris path beyond the camera
and ARC components. The following extracted ARMv7 Thumb PE32 files remain
outside Git in `/private/tmp`:

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

The sensor adapter's strings name capture, export, push-to-engine, cancel,
reset and calibration operations. The engine adapter's strings name sample
acceptance, frame analysis, enrollment and identification workers, match-result
reporting, spoof reporting and eye-info reporting. Together, this supports a
component flow of sensor capture -> WinBio engine adapter -> `irm2_*` engine
calls -> biometric result reporting; it does not prove the exact threading or
buffer handoff sequence. The engine's validation strings require one or two
eyes and image dimensions of 640–10000 by 480–10000, and expose camera and
nominal resolution parameters. These are input constraints from compiled
assertions, not recommended capture settings. Pixel format, rotation values,
enrollment quality policy and match thresholds remain unresolved.

`LumiaSensorAlgorithmControl.dll` (SHA-256
`4b6983f5f4177d6b113c06cbea8cd78e1418dd20cb1a8054e39f4d27b28154d6`) exports
open/close/speed/speed-mode controls, but their semantics and connection to
iris processing are unknown. `Origa2Auth.sys` (SHA-256
`0b8fcbe9a420d660a69d9396fe49e0a565844ffba2c3f83208f36201ef851e4d`) is also
present; its exact role is unresolved. The adapter and engine PDB identities
were checked against Microsoft's public symbol server and returned 404; no
matching symbols or source were recovered.

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

1. Trace the WinBio adapter's `irm2_*` imports and frame/result buffers to map
enrollment and identification call order, pixel format, rotation, liveness
decisions and template lifecycle. Keep analysis static; do not execute the
Windows binaries.
2. Compare Mobile `CameraAuthentication.dll` and `Icaros.dll` call paths with
WOA builds, separately from the WinBio iris algorithm path.
3. Determine how the Windows adapters bind to kernel sensor/flash controls and
which component owns template persistence and result protection.
4. Compare the recovered API contract with Android's camera path. Keep
experimental matching outside Keyguard until matching, liveness, protected
storage/result delivery, cancellation and lockout are evaluated.

The Mobile FFU, extracted ARM32 Icaros and WinBio iris components are available
outside Git. The main static-analysis gap is tracing the WinBio adapter-to-
algorithm buffers and call sequence, then matching Mobile capture/ARC
components to WOA counterparts. The WOA ESP source remains ancillary and does
not implement the recovered WinBio iris algorithm API.
