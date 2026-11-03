#!/system/bin/sh
# Run on the phone: adb shell sh < tools/identify_cityman.sh
# One power/reset and model-read attempt; no IR or streaming controls.
set -u

driver=/sys/bus/platform/drivers/cityman-iris-id
services='cameraserver vendor.camera-provider-2-4 qcamerasvr'
restore_services=
attempted=0

fail() {
    echo "$*" >&2
    exit 1
}

wait_service() {
    for poll in 1 2 3 4 5; do
        [ "$(getprop "init.svc.$1")" = "$2" ] && return 0
        sleep 1
    done
    return 1
}

clean_result() {
    case " $1 " in *' cleanup_errno=0 '*) ;; *) return 1 ;; esac
    case " $1 " in *' blocked=0 '*) ;; *) return 1 ;; esac
    case "$1" in
        status=ready\ *|status=identified\ *|status=failed\ *|status=busy\ *|status=suspended\ *) return 0 ;;
        *) return 1 ;;
    esac
}

finish() {
    code=$?
    trap - 0 HUP INT TERM
    if [ "$attempted" = 1 ]; then
        after=$(cat "$result") || after=unreadable
        echo "After: $after"
        if ! clean_result "$after"; then
            echo 'REBOOT_REQUIRED: cleanup is unconfirmed; leaving camera services stopped. Run adb reboot before using cameras or retrying.' >&2
            exit 3
        fi
        case " $after " in
            *' status=identified stage=model-read errno=0 model=0x0861 cleanup_errno=0 attempts=1 blocked=0 '*) ;;
            *) [ "$code" -ne 0 ] || code=1 ;;
        esac
    fi
    # Restore only services this invocation stopped, in dependency order.
    for service in $restore_services; do
        if start "$service" && wait_service "$service" running; then
            echo "Restored: $service"
        else
            echo "SERVICE_RESTORE_FAILED: $service; run adb reboot before using cameras." >&2
            code=4
        fi
    done
    exit "$code"
}

[ "$(id -u)" = 0 ] || fail 'Root ADB is required: run adb root, then adb wait-for-device.'
set -- "$driver"/*/result
[ "$#" = 1 ] && [ -r "$1" ] || fail 'Expected exactly one bound iris-ID device.'
result=$1
identify=${result%/result}/identify
[ -w "$identify" ] || fail 'The identify control is not writable.'
initial='status=ready stage=idle errno=0 model=0x0000 cleanup_errno=0 attempts=0 blocked=0 rail_uv=0'
before=$(cat "$result") || fail 'Cannot read the diagnostic result.'
echo "Before: $before"
[ "$before" = "$initial" ] || fail 'Refusing: expected an untouched, ready diagnostic. Do not retry; share this status first.'

# Validate every service before changing anything. These names come from the
# cityman and LineageOS init definitions linked in kernel/IRIS-ID.md.
for service in $services; do
    state=$(getprop "init.svc.$service")
    case "$state" in
        running|stopped) ;;
        *) fail "Unexpected camera service state: $service=$state; no identification performed." ;;
    esac
done

trap finish 0
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
for service in $services; do
    state=$(getprop "init.svc.$service")
    case "$state" in
        running)
            restore_services="$service $restore_services"
            stop "$service" || fail "Cannot stop $service; no identification performed."
            wait_service "$service" stopped || fail "$service did not stop; no identification performed."
            echo "Stopped: $service"
            ;;
        stopped) ;;
        *) fail "$service changed state; no identification performed." ;;
    esac
done
# Recheck immediately before the write. A busy CCI controller is also refused
# independently by the driver. No retry is issued by this helper.
for service in $services; do
    [ "$(getprop "init.svc.$service")" = stopped ] || fail "$service restarted; no identification performed."
done
[ "$(cat "$result")" = "$initial" ] || fail 'Diagnostic state changed; no identification performed.'
echo 'Performing one sensor model-read attempt.'
attempted=1
printf '%s\n' identify > "$identify"
exit "$?"
