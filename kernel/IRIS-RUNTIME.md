# Runtime iris experiments

Kernel #21 completed four clean trials on one temporary boot. Attempt 2
reapplied the existing profile byte `0x0307=0x92`, which read back `0x92`.
Attempts 3 and 4 then ran without an override, demonstrating reuse beyond the
previous three-attempt limit. All four had zero sensor-counter changes and zero
CSID packets, and each stopped and released cleanly. Both read methods returned
`0x0000` for `0x0136`, while the control at `0x0130` returned `0x099a` with
both methods. The result does not establish EXTCLK register semantics. See
[phone-result.json](builds/iris-runtime-01/phone-result.json) and the
[build manifest](builds/iris-runtime-01/manifest.json).

Kernel #21 then completed two more clean runtime trials at the allowed settle
range edges, 1 and 63. Both retained model `0x0861`, completed all 117 profile
writes and 16 counter samples, and returned `-110` with zero frame-counter
changes and zero CSID packets/ECC/CRC. The PHY configuration read back each
requested edge value. IRQ status words 3 and 6 remained `0x04` and `0x10`;
word 4 changed from the earlier `0x04` to `0x14` at both edges. Since packets
and the sensor counter remained zero, this edge-dependent status bit is a
receiver observation only; its bit meaning and relation to incoming lane
activity are not established. Cleanup returned zero and all three camera
services were running afterward. See
[edge trial evidence](builds/iris-csi-settle-edges-01/phone-result.json).

Kernel #22 tested the Windows Siiri 10 ms post-reset wait against the kernel
#21 20 ms baseline, with settle=22 and the same receiver/profile settings. The
sensor still read `0x0861`, but all 16 counter samples stayed zero; CSID
packets/ECC/CRC were also zero and the run returned `-110` at `stream-test`.
PHY IRQ words matched the 20 ms baseline. Cleanup succeeded and camera services
restored; the phone was rebooted to installed kernel #29. The timing difference
is therefore not the cause of the current no-frame result. See the
[kernel #22 build manifest](builds/iris-reset-10ms-01/manifest.json) and
[phone result](builds/iris-reset-10ms-01/phone-result.json).

The experimental kernel accepts up to 64 CSI trials per boot. Each trial powers
the sensor and receiver, runs the verified private profile, captures its result,
stops the sensor and releases the receiver before returning. It refuses another
trial after an unconfirmed cleanup. The phone can remain on the temporary boot
between successful clean trials.

Run the helper as root with a decimal PHY settle count from 1 to 63:

```sh
adb shell sh /data/local/tmp/identify_cityman.sh csi-trial 22
```

To try one byte after the profile and frame settings, append a four-digit hex
register address and a two-digit hex value. This example repeats the value
already in the current profile:

```sh
adb shell sh /data/local/tmp/identify_cityman.sh csi-trial 22 0307 92
```

The kernel accepts an override only when that address occurs in the loaded,
hash-verified profile. It excludes reset, stream and group-hold registers
`0x0100`–`0x0107` and NVM controls `0x0a00`–`0x0aff`. It reads the overridden
byte back and reports both the requested and returned value. The range accepted
by the interface is not evidence that every value is appropriate for this
sensor; choose experiments from driver or device evidence and record results.
The profile remains private and IR illumination is not enabled.

The result also compares a two-byte read of `0x0136` with separate reads of
`0x0136` and `0x0137` immediately after the existing EXTCLK write. It compares
the same two read methods on the profile-programmed `0x0130` and `0x0131` as
a control. Each observation has its own return code. A zero readback does not
alone establish that a write failed or that the physical clock is absent.

The helper stops and restores camera services around each attempt. A failed
cleanup blocks further trials and leaves services stopped until reboot. A
non-timeout test failure may also require a reboot before another trial. The
64-attempt limit bounds diagnostic operation; rebooting clears the counter and
returns a temporary boot to the installed kernel.
