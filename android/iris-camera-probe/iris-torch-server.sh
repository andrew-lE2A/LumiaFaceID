#!/system/bin/sh
# Root-only localhost service. --connection is its single-client transaction.
DEFAULT_LED=/sys/class/leds/led:torch_0/brightness

if [ "${1:-}" = "--connection" ]; then
    LED=${2:-$DEFAULT_LED}
    trap 'exit 0' HUP INT TERM
    trap 'echo 0 > "$LED" 2>/dev/null' EXIT
    IFS= read -r request || exit 1
    if [ "$request" = ARM ]; then
        echo ARMED
        IFS= read -r -t 1 request || request=TIMEOUT
        if [ "$request" = PULSE ]; then
            echo 14 > "$LED" || { echo ERROR; exit 1; }
            echo ON
            # Bound the exposure-start-triggered pulse independently of the app.
            sleep 0.08
            echo 0 > "$LED" 2>/dev/null || { echo ERROR; exit 1; }
            echo OFF
        elif [ "$request" = STOP ] || [ "$request" = TIMEOUT ]; then
            echo 0 > "$LED" 2>/dev/null || true
            echo OFF
        else
            echo REJECTED
        fi
        exit 0
    fi
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
PID_FILE=/data/local/tmp/lumia-iris-torch-demo.pid
NC_PID=
cleanup_server() {
    echo 0 > "$LED" 2>/dev/null || true
    if [ -n "$NC_PID" ]; then
        kill "$NC_PID" 2>/dev/null || true
        wait "$NC_PID" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
}
trap cleanup_server EXIT
trap 'exit 0' HUP INT TERM
echo $$ > "$PID_FILE"
while true; do
    /system/bin/toybox nc -l -s 127.0.0.1 -p 18761 \
        /system/bin/sh "$0" --connection "$LED" &
    NC_PID=$!
    wait "$NC_PID" || true
    NC_PID=
done
