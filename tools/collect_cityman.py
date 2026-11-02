#!/usr/bin/env python3
"""Read selected cityman bring-up metadata through ADB; never drive hardware."""

import argparse
import datetime
import json
from pathlib import PurePosixPath
import shlex
import subprocess
import sys


PROPERTIES = (
    "ro.product.device", "ro.product.board", "ro.board.platform",
    "ro.build.version.release", "ro.build.version.sdk", "ro.lineage.version",
    "ro.build.fingerprint",
)
DT_PROPERTIES = (
    "compatible", "status", "reg", "cell-index", "qcom,sensor-name",
    "qcom,cci-master", "qcom,slave-id", "qcom,sensor-slave-addr",
    "qcom,csiphy-sd-index", "qcom,csid-sd-index",
    "qcom,csi-lane-assign", "qcom,csi-lane-mask", "qcom,cam-vreg-name",
    "qcom,cam-vreg-min-voltage", "qcom,cam-vreg-max-voltage",
    "gpios", "qcom,gpio-reset", "qcom,gpio-standby", "clock-names",
)
STRING_PROPERTIES = {"compatible", "status", "qcom,sensor-name",
                     "qcom,cam-vreg-name", "clock-names"}
DT_ROOTS = ("/sys/firmware/devicetree/base", "/proc/device-tree")
FIND_TREE = """for base in /sys/firmware/devicetree/base /proc/device-tree; do
    if [ -d "$base" ]; then
        find -H "$base" -type d
        exit $?
    fi
done
echo 'No readable live device-tree directory' >&2
exit 66"""
DEVICE_NAMES = """found=0
for entry in /sys/class/video4linux/* /sys/class/media/*; do
    [ -d "$entry" ] || continue
    found=1
    printf '%s: ' "$entry"
    if [ -r "$entry/name" ]; then
        cat "$entry/name" || exit $?
    elif [ -r "$entry/model" ]; then
        cat "$entry/model" || exit $?
    else
        printf '(name/model unavailable)\\n'
    fi
done
if [ "$found" -eq 0 ]; then echo '(no visible media/video class entries)'; fi"""
PLATFORM_DEVICES = """found=0
failed=0
for entry in /sys/bus/platform/devices/*; do
    [ -d "$entry" ] || continue
    case "${entry##*/}" in
        *camera*|*cci*|*csid*|*csiphy*|*actuator*|*flash*|*vfe*|*ispif*) ;;
        *) continue ;;
    esac
    found=1
    printf 'DEVICE %s\\n' "$entry"
    cat "$entry/uevent"
    result=$?
    [ "$result" -eq 0 ] || failed=1
    printf '\\nEND %s\\n' "$result"
done
if [ "$found" -eq 0 ]; then
    echo 'No visible matching platform devices' >&2
    exit 67
fi
exit "$failed"
"""


class Adb:
    def __init__(self, executable="adb", serial=None, timeout=15):
        self.prefix = [executable] + (["-s", serial] if serial else [])
        self.serial = serial
        self.timeout = timeout

    def run(self, *args):
        try:
            result = subprocess.run(self.prefix + list(args), capture_output=True,
                                    text=True, timeout=self.timeout, check=False,
                                    encoding="utf-8", errors="replace")
        except (OSError, subprocess.TimeoutExpired) as exc:
            # TimeoutExpired's command can contain the serial; do not print it.
            return {"status": "error", "exit_code": None, "stdout": "",
                    "stderr": "ADB command timed out" if isinstance(exc, subprocess.TimeoutExpired)
                    else f"Cannot run ADB: {exc.strerror}"}
        stdout, stderr = result.stdout, result.stderr
        # ADB errors can echo the explicit device selector. Successful property
        # data must remain unchanged, even if a short selector matches it.
        if self.serial:
            stderr = stderr.replace(self.serial, "[REDACTED]")
            if result.returncode:
                stdout = stdout.replace(self.serial, "[REDACTED]")
        too_large = len(stdout) > 262144 or len(stderr) > 16384
        return {"status": "ok" if result.returncode == 0 and not too_large else "error",
                "exit_code": result.returncode, "stdout": stdout[:262144],
                "stderr": stderr[:16384], "truncated": too_large}

    def shell(self, command):
        return self.run("shell", command)


def camera_nodes(text):
    """Select only canonical camera/CCI paths below a known live DT root."""
    selected = set()
    for line in text.splitlines():
        path = PurePosixPath(line)
        if str(path) != line or ".." in path.parts:
            continue
        if not any(line.startswith(root + "/") for root in DT_ROOTS):
            continue
        name = path.name.lower()
        if "camera" in name or "cci" in name:
            selected.add(line)
    return sorted(selected)


def read_node_command(node):
    # The path comes from device output and must remain shell-quoted.
    return f"node={shlex.quote(node)}\n" + """for prop in """ + " ".join(DT_PROPERTIES) + """; do
    file="$node/$prop"
    [ -f "$file" ] || continue
    printf 'PROPERTY %s\\n' "$prop"
    od -An -v -tx1 "$file"
    result=$?
    printf '\\nEND %s\\n' "$result"
done"""


def decode_node(text):
    """Parse od bytes without guessing sensor identities or phandle meanings."""
    properties = {}
    lines = iter(text.splitlines())
    for line in lines:
        if not line.strip():
            continue
        if not line.startswith("PROPERTY "):
            raise ValueError("Unexpected property record")
        key = line.removeprefix("PROPERTY ")
        if key not in DT_PROPERTIES or key in properties:
            raise ValueError("Unexpected or duplicate property")
        payload = []
        for line in lines:
            if line.startswith("END "):
                exit_code = int(line.removeprefix("END "))
                break
            payload.extend(line.split())
        else:
            raise ValueError("Unterminated property record")
        if exit_code:
            properties[key] = {"status": "error", "exit_code": exit_code}
            continue
        if any(len(word) != 2 or any(c not in "0123456789abcdefABCDEF" for c in word)
               for word in payload):
            raise ValueError("Malformed hexadecimal property")
        raw = bytes.fromhex(" ".join(payload))
        value = {"status": "ok", "hex": raw.hex()}
        if key in STRING_PROPERTIES:
            value["strings"] = raw.rstrip(b"\0").decode("utf-8", errors="replace").split("\0")
        elif len(raw) % 4 == 0:
            value["cells_be32"] = [int.from_bytes(raw[i:i+4], "big")
                                  for i in range(0, len(raw), 4)]
        properties[key] = value
    return properties


def collect(adb):
    report = {"schema_version": 1,
              "collector_version": "0.2.0",
              "collected_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "purpose": "read-only bring-up metadata; not a sensor or biometric test",
              "status": "incomplete", "identity": {}, "device_tree": {}}
    state = adb.run("get-state")
    report["adb"] = state
    if state["status"] != "ok" or state["stdout"].strip() != "device":
        return report, 2
    for key in PROPERTIES:
        report["identity"][key] = adb.shell("getprop " + key)
    identity = report["identity"]
    if any(value["status"] != "ok" for value in identity.values()):
        return report, 1
    if (identity["ro.product.device"]["stdout"].strip() != "cityman" or
            identity["ro.build.version.sdk"]["stdout"].strip() != "36"):
        report["status"] = "target_mismatch"
        return report, 3
    report["kernel"] = adb.shell("uname -r")
    report["media_devices"] = adb.shell(DEVICE_NAMES)
    tree = adb.shell(FIND_TREE)
    report["device_tree"]["discovery"] = tree
    incomplete = any(record["status"] != "ok" for record in
                     (report["kernel"], report["media_devices"], tree))
    report["device_tree"]["nodes"] = {}
    if tree["status"] == "ok":
        nodes = camera_nodes(tree["stdout"])
        report["device_tree"]["node_limit_reached"] = len(nodes) > 64
        incomplete |= len(nodes) > 64
        for node in nodes[:64]:
            result = adb.shell(read_node_command(node))
            try:
                props = decode_node(result["stdout"])
            except ValueError as exc:
                props = {}
                result["status"] = "error"
                result["parse_error"] = str(exc)
            result["properties"] = props
            if not props or any(p["status"] != "ok" for p in props.values()):
                result["status"] = "error"
            report["device_tree"]["nodes"][node] = result
            incomplete |= result["status"] != "ok"
        # No visible nodes is an observation, not proof that a driver is absent.
        report["device_tree"]["camera_nodes_visible"] = bool(nodes)
    if tree["status"] != "ok" or not report["device_tree"].get("camera_nodes_visible"):
        # The selected Linux 3.10 kernel disables PROC_DEVICETREE and lacks
        # the newer sysfs export. Registered platform uevents remain readable.
        # Retain the original failure: these expose identities, not DT properties.
        report["platform_devices"] = adb.shell(PLATFORM_DEVICES)
        report["device_tree"]["fallback"] = "platform_uevents"
        report["device_tree"]["fallback_scope"] = "registered-node identities only; not full DT properties"
        report["limitations"] = [
            "Full camera device-tree properties were not collected. The pinned cityman Linux 3.10 "
            "kernel disables /proc/device-tree and lacks the modern sysfs tree export. "
            "Platform uevents provide registered-node metadata only."
        ]
        incomplete |= report["platform_devices"]["status"] != "ok"
    report["status"] = "incomplete" if incomplete else "collected"
    return report, 1 if incomplete else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb", help="path to the adb executable")
    parser.add_argument("--serial", help="select one connected device")
    parser.add_argument("--timeout", type=float, default=15, help="per-command timeout in seconds")
    parser.add_argument("--output", required=True, help="new JSON report file; never overwritten")
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 120:
        parser.error("--timeout must be greater than 0 and at most 120 seconds")
    try:
        # Reserve the output before making any ADB requests.
        with open(args.output, "x", encoding="utf-8") as output:
            report, exit_code = collect(Adb(args.adb, args.serial, args.timeout))
            json.dump(report, output, indent=2)
            output.write("\n")
    except OSError as exc:
        print(f"Cannot write report: {exc.strerror}", file=sys.stderr)
        return 2
    print(f"{report['status']}: {args.output}", file=sys.stderr)
    for limitation in report.get("limitations", []):
        print(limitation, file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
