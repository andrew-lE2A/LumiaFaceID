#!/bin/sh
set -eu

ADB_BIN=${ADB_BIN:-adb}
SERIAL=${1:-}
REMOTE_PID=/data/local/tmp/lumia-iris-torch-demo.pid
REMOTE_HELPER=/data/local/tmp/lumia-iris-torch-demo.sh
REMOTE_LOG=/data/local/tmp/lumia-iris-torch-demo.log

adb_cmd() {
    if [ -n "$SERIAL" ]; then
        "$ADB_BIN" -s "$SERIAL" "$@"
    else
        "$ADB_BIN" "$@"
    fi
}

adb_cmd get-state >/dev/null
adb_cmd root >/dev/null
adb_cmd wait-for-device
adb_cmd shell am force-stop com.lumia.irisprobe.demo 2>/dev/null || true
adb_cmd shell am force-stop com.lumia.irisprobe.feedback 2>/dev/null || true
adb_cmd shell "if [ -f '$REMOTE_PID' ]; then kill -TERM \"\$(cat '$REMOTE_PID')\" 2>/dev/null || true; fi"
sleep 1
adb_cmd shell "for f in /sys/class/leds/led:torch_0/brightness /sys/class/leds/led:torch_1/brightness /sys/class/leds/led:flash_0/brightness /sys/class/leds/led:flash_1/brightness; do echo 0 > \"\$f\" 2>/dev/null || true; done; rm -f '$REMOTE_PID' '$REMOTE_HELPER' '$REMOTE_LOG'"
adb_cmd forward --remove tcp:18761 >/dev/null 2>&1 || true

echo "LED brightness after cleanup:"
adb_cmd shell "for f in /sys/class/leds/led:torch_0/brightness /sys/class/leds/led:torch_1/brightness /sys/class/leds/led:flash_0/brightness /sys/class/leds/led:flash_1/brightness; do printf '%s=' \"\${f##*/}\"; cat \"\$f\"; done"
echo "Demo app stopped and temporary helper/forward removed."
