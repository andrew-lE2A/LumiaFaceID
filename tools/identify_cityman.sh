#!/system/bin/sh
# Run on the phone: adb shell sh < tools/identify_cityman.sh
# Default: one ID attempt. stream-once: sensor counter; csi-once: CSI packets.
# csi2-once additionally selects the fixed CSI-2 interface comparison.
# Optional --observe-mclk or --observe-receiver-clocks samples debugfs clocks.
# No mode configures image DMA or IR controls.
set -u

operation=${1:-identify}
clock_option=${2:-}
streaming=0
receiver_test=0
case "$operation" in stream-once|csi-once|csi2-once) streaming=1 ;; esac
case "$operation" in csi-once|csi2-once) receiver_test=1 ;; esac
driver=/sys/bus/platform/drivers/cityman-iris-id
profile=/data/local/tmp/cityman-iris-stream-profile.hex
services='cameraserver vendor.camera-provider-2-4 qcamerasvr'
restore_services=
attempted=0
clock_root=/sys/kernel/debug/clk/camss_mclk1_clk
receiver_clock_root=/sys/kernel/debug/clk
clock_targets=$clock_root
clock_label=MCLK
clock_rounds='1 2 3 4 5 6 7 8 9 10 11 12'
clock_log_template=/data/local/tmp/cityman-iris-mclk.XXXXXX
clock_pid=
clock_log=

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
        status=ready\ *|status=identified\ *|status=sensor-streamed\ *|status=failed\ *|status=busy\ *|status=suspended\ *) return 0 ;;
        *) return 1 ;;
    esac
}

observe_clocks() {
    # The existing clock driver performs each hardware measurement (~15 ms).
    # Read software state on both sides to identify power/clock transitions.
    # Never write the debugfs rate/enable/parent controls.
    # Use one sampler for every target: they share the hardware debug mux.
    for sample in $clock_rounds; do
        for observed_clock in $clock_targets; do
            rate_before=$(cat "$observed_clock/rate") || return 1
            enable_before=$(cat "$observed_clock/enable") || return 1
            measured=$(cat "$observed_clock/measure") || {
                echo "$clock_label hardware measurement read failed: $observed_clock" >&2
                return 1
            }
            rate_after=$(cat "$observed_clock/rate") || return 1
            enable_after=$(cat "$observed_clock/enable") || return 1
            echo "$clock_label sample=$sample clock=${observed_clock##*/} rate_before_hz=$rate_before enable_before=$enable_before measured_hz=$measured rate_after_hz=$rate_after enable_after=$enable_after"
        done
    done
}

finish() {
    code=$?
    trap - 0 HUP INT TERM
    if [ -n "$clock_pid" ]; then
        if ! wait "$clock_pid"; then
            echo "${clock_label}_OBSERVATION_INCOMPLETE: the clock sampler failed." >&2
            [ "$code" -ne 0 ] || code=5
        fi
        echo "Saved $clock_label observations: $clock_log"
        cat "$clock_log" || {
            echo "$clock_label observations could not be read." >&2
            [ "$code" -ne 0 ] || code=5
        }
    fi
    if [ "$attempted" = 1 ]; then
        after=$(cat "$result") || after=unreadable
        echo "After: $after"
        stream_clean=1
        if [ "$streaming" = 1 ]; then
            stream_after=$(cat "$node/stream_result") || stream_after=unreadable
            echo "Stream after: $stream_after"
            if [ -r "$node/stream_readback" ]; then
                echo 'Saved register readback (before and after stream-on):'
                cat "$node/stream_readback" || echo 'Saved register readback unavailable.' >&2
            fi
            case " $stream_after " in *' stop_errno=0 '*) ;; *) stream_clean=0 ;; esac
        fi
        if [ "$receiver_test" = 1 ]; then
            csi_after=$(cat "$node/csi_result") || csi_after=unreadable
            echo "CSI after: $csi_after"
            if [ -r "$node/csi_readback" ]; then
                echo 'Saved receiver configuration/status (before and after start):'
                cat "$node/csi_readback" || echo 'Saved receiver readback unavailable.' >&2
            fi
            case " $csi_after " in *' cleanup_errno=0 '*) ;; *) stream_clean=0 ;; esac
        fi
        if ! clean_result "$after" || [ "$stream_clean" != 1 ]; then
            echo 'REBOOT_REQUIRED: cleanup is unconfirmed; leaving camera services stopped. Run adb reboot before using cameras or retrying.' >&2
            exit 3
        fi
        case "$operation: $after " in
            identify:*' status=identified stage=model-read errno=0 model=0x0861 cleanup_errno=0 attempts=1 blocked=0 '*) ;;
            stream-once:*' status=sensor-streamed stage=stream-test errno=0 model=0x0861 cleanup_errno=0 attempts=1 blocked=0 '*) ;;
            csi-once:*' status=sensor-streamed stage=stream-test errno=0 model=0x0861 cleanup_errno=0 attempts=1 blocked=0 '*) ;;
            csi2-once:*' status=sensor-streamed stage=stream-test errno=0 model=0x0861 cleanup_errno=0 attempts=1 blocked=0 '*) ;;
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
case "$operation" in identify|stream-once|csi-once|csi2-once) ;; *) fail 'Expected identify, stream-once, csi-once or csi2-once.' ;; esac
[ "$#" -le 2 ] || fail 'Unexpected extra arguments.'
case "$clock_option" in
    '') ;;
    --observe-mclk)
        [ "$streaming" = 1 ] || fail 'MCLK observation requires a stream diagnostic.'
        ;;
    --observe-receiver-clocks)
        [ "$receiver_test" = 1 ] || fail 'Receiver clock observation requires csi-once or csi2-once.'
        clock_targets="$receiver_clock_root/camss_csi3_clk $receiver_clock_root/camss_phy2_csi2phytimer_clk"
        clock_label=RXCLK
        clock_rounds='1 2 3 4 5 6'
        clock_log_template=/data/local/tmp/cityman-iris-rxclk.XXXXXX
        ;;
    *) fail 'Unknown option; expected --observe-mclk or --observe-receiver-clocks.' ;;
esac
if [ -n "$clock_option" ]; then
    for observed_clock in $clock_targets; do
        for clock_file in measure rate enable; do
            [ -r "$observed_clock/$clock_file" ] || fail "$clock_label observation unavailable: $observed_clock/$clock_file; no hardware action performed."
        done
    done
fi
set -- "$driver"/*/result
[ "$#" = 1 ] && [ -r "$1" ] || fail 'Expected exactly one bound iris-ID device.'
result=$1
node=${result%/result}
control=$node/identify
if [ "$streaming" = 1 ]; then
    control=$node/stream_once
    [ -r "$node/stream_result" ] && [ -w "$node/stream_profile" ] && [ -r "$profile" ] ||
        fail 'Stream build and /data/local/tmp/cityman-iris-stream-profile.hex are required.'
fi
if [ "$receiver_test" = 1 ]; then
    control=$node/csi_once
    [ "$operation" != csi2-once ] || control=$node/csi2_once
    [ -r "$node/csi_result" ] || fail 'The CSI diagnostic build is required.'
    csi_before=$(cat "$node/csi_result") || fail 'Cannot read CSI status.'
    echo "CSI before: $csi_before"
    case "$csi_before" in requested=0\ stage=idle\ *) ;; *) fail 'Expected untouched CSI state.' ;; esac
fi
[ -w "$control" ] || fail 'The requested diagnostic control is not writable.'
initial='status=ready stage=idle errno=0 model=0x0000 cleanup_errno=0 attempts=0 blocked=0 rail_uv=0'
before=$(cat "$result") || fail 'Cannot read the diagnostic result.'
echo "Before: $before"
[ "$before" = "$initial" ] || fail 'Refusing: expected an untouched, ready diagnostic. Do not retry; share this status first.'
if [ "$streaming" = 1 ]; then
    # Upload changes memory only; the kernel verifies the exact program SHA.
    cat "$profile" > "$node/stream_profile" || fail 'The kernel rejected the stream profile; no hardware action performed.'
    stream_before=$(cat "$node/stream_result") || fail 'Cannot read stream status.'
    echo "Stream before: $stream_before"
    case "$stream_before" in profile_loaded=1\ *) ;; *) fail 'Stream profile was not accepted.' ;; esac
fi

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
if [ -n "$clock_option" ]; then
    clock_log=$(mktemp "$clock_log_template") || fail 'Cannot create clock observation log; no sensor test performed.'
    observe_clocks > "$clock_log" 2>&1 &
    clock_pid=$!
fi
echo "Performing one $operation attempt."
attempted=1
printf '%s\n' "$operation" > "$control"
exit "$?"
