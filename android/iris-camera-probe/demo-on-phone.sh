#!/bin/sh
set -eu

APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ADB_BIN=${ADB_BIN:-adb}
APK="$APP_DIR/build/LumiaIrisProbe.apk"
REMOTE_HELPER=/data/local/tmp/lumia-iris-torch-demo.sh
REMOTE_PID=/data/local/tmp/lumia-iris-torch-demo.pid
REMOTE_LOG=/data/local/tmp/lumia-iris-torch-demo.log
HELPER="$APP_DIR/iris-torch-server.sh"
SERIAL=${1:-}

adb_cmd() {
    if [ -n "$SERIAL" ]; then
        "$ADB_BIN" -s "$SERIAL" "$@"
    else
        "$ADB_BIN" "$@"
    fi
}

if [ ! -f "$APK" ]; then
    echo "Missing $APK. Build the feedback manifest variant first." >&2
    exit 1
fi
if [ ! -f "$HELPER" ]; then
    echo "Missing $HELPER." >&2
    exit 1
fi

adb_cmd get-state >/dev/null
adb_cmd root >/dev/null
adb_cmd wait-for-device
DEVICE_UID=$(adb_cmd shell id)
case "$DEVICE_UID" in
    *"uid=0(root)"*) ;;
    *) echo "ADB root is required to control torch_0; helper not started." >&2; exit 1 ;;
esac

ACTIVE_CLIENTS=$(adb_cmd shell dumpsys media.camera \
    | sed -n '/Active Camera Clients:/,/Active Client listener PIDs:/p' \
    | tr -d '\r')
if printf '%s\n' "$ACTIVE_CLIENTS" | grep -q '(Camera ID:'; then
    echo "A camera is already active. Close it before starting the iris demo." >&2
    exit 1
fi

adb_cmd shell "if [ -f '$REMOTE_PID' ]; then kill -TERM \"\$(cat '$REMOTE_PID')\" 2>/dev/null || true; sleep 1; fi"
adb_cmd shell "for f in /sys/class/leds/led:torch_0/brightness /sys/class/leds/led:torch_1/brightness /sys/class/leds/led:flash_0/brightness /sys/class/leds/led:flash_1/brightness; do echo 0 > \"\$f\"; done"
adb_cmd shell "rm -f '$REMOTE_PID' '$REMOTE_HELPER' '$REMOTE_LOG'"
# Keep the pulse service on device loopback; do not create an ADB forward.
adb_cmd forward --remove tcp:18761 >/dev/null 2>&1 || true
adb_cmd push "$HELPER" "$REMOTE_HELPER" >/dev/null
adb_cmd shell "chmod 700 '$REMOTE_HELPER'; nohup /system/bin/sh '$REMOTE_HELPER' >'$REMOTE_LOG' 2>&1 </dev/null &"
adb_cmd shell "for n in 1 2 3 4 5; do [ -f '$REMOTE_PID' ] && break; sleep 1; done; test -f '$REMOTE_PID'"
adb_cmd install -r "$APK"
adb_cmd shell am force-stop com.lumia.irisprobe.demo 2>/dev/null || true
adb_cmd shell am force-stop com.lumia.irisprobe.feedback 2>/dev/null || true
adb_cmd shell am start -n com.lumia.irisprobe.demo/com.lumia.irisprobe.IrisProbeActivity

echo "Demo ready. Enrollment/comparison remain IR-off. The confirmed diffuse-target diagnostic requests minimum IR at Camera2 capture start; helper cutoff is 80 ms."
echo "The helper is reachable only on phone loopback; no ADB port forward is created."
echo "To close the demo and clean up, run: $APP_DIR/demo-off-phone.sh${SERIAL:+ $SERIAL}"
