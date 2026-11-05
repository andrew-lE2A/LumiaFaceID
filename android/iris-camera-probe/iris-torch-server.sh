#!/system/bin/sh
# Root-only localhost service. --connection is its single-client transaction.
DEFAULT_LED=/sys/class/leds/led:torch_0/brightness

if [ "${1:-}" = "--connection" ]; then
    LED=${2:-$DEFAULT_LED}
    watchdog_pid=
    trap 'exit 0' HUP INT TERM
    trap 'echo 0 > "$LED" 2>/dev/null; if [ -n "$watchdog_pid" ]; then kill "$watchdog_pid" 2>/dev/null; wait "$watchdog_pid" 2>/dev/null; fi' EXIT
    IFS= read -r request || exit 1
    if [ "$request" != PULSE ]; then
        echo REJECTED
        exit 0
    fi
    echo 14 > "$LED" || { echo ERROR; exit 1; }
    echo ON
    ( sleep 1; echo 0 > "$LED" 2>/dev/null ) &
    watchdog_pid=$!
    IFS= read -r completion || completion=CANCEL
    echo 0 > "$LED" || { echo ERROR; exit 1; }
    kill "$watchdog_pid" 2>/dev/null
    wait "$watchdog_pid" 2>/dev/null
    echo OFF
    exit 0
fi

LED=$DEFAULT_LED
echo 0 > "$LED" || exit 1
while true; do
    /system/bin/toybox nc -l -s 127.0.0.1 -p 18761 \
        /system/bin/sh "$0" --connection "$LED"
done
