#!/system/bin/sh
# Root-only localhost service. --connection is its single-client transaction.
DEFAULT_LED=/sys/class/leds/led:torch_0/brightness

if [ "${1:-}" = "--connection" ]; then
    LED=${2:-$DEFAULT_LED}
    trap 'exit 0' HUP INT TERM
    trap 'echo 0 > "$LED" 2>/dev/null' EXIT
    IFS= read -r request || exit 1
    if [ "$request" != PULSE ]; then
        echo REJECTED
        exit 0
    fi
    echo 14 > "$LED" || { echo ERROR; exit 1; }
    echo ON
    IFS= read -r -t 1 completion || completion=TIMEOUT
    echo 0 > "$LED" || { echo ERROR; exit 1; }
    echo OFF
    exit 0
fi

LED=$DEFAULT_LED
echo 0 > "$LED" || exit 1
while true; do
    /system/bin/toybox nc -l -s 127.0.0.1 -p 18761 \
        /system/bin/sh "$0" --connection "$LED"
done
