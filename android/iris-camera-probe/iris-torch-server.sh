#!/system/bin/sh
# Run as root through adb shell. The app can only request one bounded pulse.
LED=/sys/class/leds/led:torch_0/brightness
PORT=18761

echo 0 > "$LED" || exit 1
while true; do
    /system/bin/toybox nc -l -s 127.0.0.1 -p "$PORT" /system/bin/sh -c '
        LED=/sys/class/leds/led:torch_0/brightness
        trap '\''echo 0 > "$LED" 2>/dev/null'\'' EXIT HUP INT TERM
        IFS= read -r request || exit 1
        if [ "$request" != PULSE ]; then
            echo REJECTED
            exit 0
        fi
        echo 14 > "$LED" || { echo ERROR; exit 1; }
        sleep 1
        echo 0 > "$LED" || { echo ERROR; exit 1; }
        echo OK
    '
done
