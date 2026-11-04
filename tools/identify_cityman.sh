#!/system/bin/sh
# Run on the phone: adb shell sh < tools/identify_cityman.sh
# Default: one ID attempt. nvm-once reads five NVM header bytes only.
# stream-once: sensor counter; csi-once: CSI packets.
# csi2-once additionally selects the fixed CSI-2 interface comparison.
# csi-trial accepts a PHY settle value from 1 to 63.
# Optional --observe-mclk or --observe-receiver-clocks samples debugfs clocks.
# No mode configures image DMA or IR controls.
set -u

operation=${1:-identify}
clock_option=
trial_settle=
trial_register=
trial_value=
trial_clock=
load_option=0
boost_option=0
misc_option=0
miscfull_option=0
regulator_option=
regulator_log_template=/data/local/tmp/cityman-iris-regulators.XXXXXX
regulator_pid=
regulator_log=
if [ "$operation" = csi-trial ]; then
    trial_settle=${2:-}
    arg3=${3:-}
    arg4=${4:-}
    arg5=${5:-}
    case "$arg3" in
        --observe-mclk|--observe-receiver-clocks)
            clock_option=$arg3
            trial_register=
            trial_value=
            ;;
        --observe-regulators)
            regulator_option=$arg3
            ;;
        load)
            load_option=1
            clock_option=$arg4
            case "$clock_option" in
                misc) misc_option=1; clock_option=$arg5 ;;
                miscfull) miscfull_option=1; clock_option=$arg5 ;;
            esac
            if [ "$clock_option" = --observe-regulators ]; then
                regulator_option=$clock_option
                clock_option=
            fi
            ;;
        boost)
            boost_option=1
            clock_option=$arg4
            if [ "$clock_option" = --observe-regulators ]; then
                regulator_option=$clock_option
                clock_option=
            fi
            ;;
        misc|miscfull|load)
            case "$arg3" in load) load_option=1 ;; misc) misc_option=1 ;; miscfull) miscfull_option=1 ;; esac
            next_arg=$arg4
            case "$next_arg" in
                load) load_option=1; next_arg=$arg5 ;;
                misc) misc_option=1; next_arg=$arg5 ;;
                miscfull) miscfull_option=1; next_arg=$arg5 ;;
            esac
            if [ "$next_arg" = --observe-regulators ]; then
                regulator_option=$next_arg
            elif [ "$next_arg" = --observe-mclk ] || [ "$next_arg" = --observe-receiver-clocks ]; then
                clock_option=$next_arg
            fi
            ;;
        clock=csi2|clock=csi0)
            trial_clock=${arg3#clock=}
            clock_option=$arg4
            trial_register=
            trial_value=
            ;;
        *)
            trial_register=$arg3
            trial_value=$arg4
            clock_option=$arg5
            ;;
    esac
else
    clock_option=${2:-}
fi
streaming=0
receiver_test=0
tpg_test=0
nvm_test=0
route_before=
case "$operation" in stream-once|csi-once|csi2-once|csi-trial) streaming=1 ;; esac
case "$operation" in csi-once|csi2-once|csi-trial) receiver_test=1 ;; esac
case "$operation" in tpg-once) tpg_test=1 ;; esac
case "$operation" in nvm-once) nvm_test=1 ;; esac
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

observe_regulators() {
    # Read-only debugfs snapshots. Poll quickly during the bounded active window.
    for sample in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40; do
        for rail in pm8994_l17 pm8994_l3 pm8994_s3 pmi8994_boostbypass; do
            root=/sys/kernel/debug/regulator/$rail
            mode=$(cat "$root/mode" 2>/dev/null) || mode=unavailable
            optimum=$(cat "$root/optimum_mode" 2>/dev/null) || optimum=unavailable
            enable=$(cat "$root/enable" 2>/dev/null) || enable=unavailable
            use=$(cat "$root/use_count" 2>/dev/null) || use=unavailable
            echo "sample=$sample rail=$rail mode=$mode optimum_mode=$optimum enable=$enable use_count=$use"
        done
        sleep 0.01
    done
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

retryable_trial_state() {
    case "$1" in
        'status=ready stage=idle errno=0 model=0x0000 cleanup_errno=0 attempts=0 blocked=0 rail_uv=0') return 0 ;;
        'status=ready stage=idle errno=0 model=0x0000 cleanup_errno=0 attempts=0 blocked=0 rail_uv=0 load_trial=0 '*) return 0 ;;
        'status=failed stage=stream-test errno=-110 model=0x0861 cleanup_errno=0 attempts='*' blocked=0 rail_uv=1200000 '*|\
        'status=sensor-streamed stage=stream-test errno=0 model=0x0861 cleanup_errno=0 attempts='*' blocked=0 rail_uv=1200000 '*)
            trial_attempts=${1#* attempts=}; trial_attempts=${trial_attempts%% *}
            case "$trial_attempts" in ''|*[!0-9]*) return 1 ;; esac
            [ "$trial_attempts" -ge 1 ] && [ "$trial_attempts" -lt 64 ]; return $? ;;
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
    if [ -n "$regulator_pid" ]; then
        if ! wait "$regulator_pid"; then
            echo 'REGULATOR_OBSERVATION_INCOMPLETE: the debugfs sampler failed.' >&2
            [ "$code" -ne 0 ] || code=5
        fi
        echo "Saved regulator observations: $regulator_log"
        cat "$regulator_log" || {
            echo 'Regulator observations could not be read.' >&2
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
            route_after=$(cat "$node/csi_top_result") || route_after=unreadable
            echo "CAMSS TOP after receiver test: $route_after"
            if [ -r "$node/csi_readback" ]; then
                echo 'Saved receiver configuration/status (before and after start):'
                cat "$node/csi_readback" || echo 'Saved receiver readback unavailable.' >&2
            fi
            case " $csi_after " in *' cleanup_errno=0 '*) ;; *) stream_clean=0 ;; esac
        fi
        if [ "$tpg_test" = 1 ]; then
            tpg_after=$(cat "$node/csi_tpg_result") || tpg_after=unreadable
            echo "CSID TPG after: $tpg_after"
            case " $tpg_after " in
                *' requested=1 stage=released '*' cleanup_errno=0 '*) ;;
                *) stream_clean=0 ;;
            esac
        fi
        if [ "$nvm_test" = 1 ]; then
            nvm_after=$(cat "$node/nvm_result") || nvm_after=unreadable
            echo "NVM after: $nvm_after"
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
            csi-trial:*' status=failed stage=stream-test errno=-110 model=0x0861 cleanup_errno=0 attempts='*' blocked=0 rail_uv=1200000'*) ;;
            csi-trial:*' status=sensor-streamed stage=stream-test errno=0 model=0x0861 cleanup_errno=0 attempts='*' blocked=0 rail_uv=1200000'*) ;;
            tpg-once:*' status=ready stage=idle errno=0 model=0x0000 cleanup_errno=0 attempts=0 blocked=0 rail_uv=0 '*) ;;
            nvm-once:*' status=identified stage=nvm-test errno=0 model=0x0861 cleanup_errno=0 attempts=1 blocked=0 '*) ;;
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
case "$operation" in identify|nvm-once|stream-once|csi-once|csi2-once|csi-trial|tpg-once) ;; *) fail 'Expected identify, nvm-once, stream-once, csi-once, csi2-once, csi-trial or tpg-once.' ;; esac
if [ "$operation" = csi-trial ]; then
    [ "$#" -le 5 ] || fail 'Unexpected extra arguments.'
    case "$trial_settle" in ''|*[!0-9]*|0*) fail 'csi-trial requires a decimal settle value from 1 to 63.' ;; esac
    [ "$trial_settle" -ge 1 ] && [ "$trial_settle" -le 63 ] || fail 'csi-trial settle must be from 1 to 63.'
    [ "$load_option" != 1 ] || [ "$boost_option" != 1 ] || fail 'Load and boost selectors must be run as separate trials.'
    if [ -n "$trial_register$trial_value" ]; then
        case "$trial_register" in [0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]) ;; *) fail 'Register must be four hex digits.' ;; esac
        case "$trial_value" in [0-9a-fA-F][0-9a-fA-F]) ;; *) fail 'Value must be two hex digits.' ;; esac
    fi
else
    [ "$#" -le 2 ] || fail 'Unexpected extra arguments.'
fi
case "$clock_option" in
    '') ;;
    --observe-mclk)
        [ "$streaming" = 1 ] || fail 'MCLK observation requires a stream diagnostic.'
        ;;
    --observe-receiver-clocks)
        [ "$receiver_test" = 1 ] || fail 'Receiver clock observation requires csi-once or csi2-once.'
        clock_targets="$receiver_clock_root/camss_csi3phy_clk $receiver_clock_root/camss_csi2_clk $receiver_clock_root/camss_csi0_clk $receiver_clock_root/camss_csi3_clk $receiver_clock_root/camss_phy2_csi2phytimer_clk"
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
if [ -n "$regulator_option" ]; then
    for regulator in pm8994_l17 pm8994_l3 pm8994_s3 pmi8994_boostbypass; do
        for regulator_file in mode optimum_mode enable use_count; do
            [ -r "/sys/kernel/debug/regulator/$regulator/$regulator_file" ] ||
                fail "Regulator observation unavailable: /sys/kernel/debug/regulator/$regulator/$regulator_file; no hardware action performed."
        done
    done
fi
set -- "$driver"/*/result
[ "$#" = 1 ] && [ -r "$1" ] || fail 'Expected exactly one bound iris-ID device.'
result=$1
node=${result%/result}
control=$node/identify
if [ "$nvm_test" = 1 ]; then
    control=$node/nvm_once
    [ -r "$node/nvm_result" ] || fail 'The NVM header diagnostic build is required.'
fi
if [ "$streaming" = 1 ]; then
    control=$node/stream_once
    [ -r "$node/stream_result" ] && [ -w "$node/stream_profile" ] && [ -r "$profile" ] ||
        fail 'Stream build and /data/local/tmp/cityman-iris-stream-profile.hex are required.'
fi
if [ "$receiver_test" = 1 ]; then
    control=$node/csi_once
    [ "$operation" != csi2-once ] || control=$node/csi2_once
    [ "$operation" != csi-trial ] || control=$node/csi_trial
    [ -r "$node/csi_result" ] || fail 'The CSI diagnostic build is required.'
    csi_before=$(cat "$node/csi_result") || fail 'Cannot read CSI status.'
    echo "CSI before: $csi_before"
    if [ "$operation" = csi-trial ]; then
        case "$csi_before" in
            requested=0\ stage=idle\ *|requested=1\ stage=released\ errno=0\ cleanup_errno=0\ *) ;;
            *) fail 'Expected idle or cleanly released CSI state.' ;;
        esac
    else
        case "$csi_before" in requested=0\ stage=idle\ *) ;; *) fail 'Expected untouched CSI state.' ;; esac
    fi
    [ -r "$node/csi_top_result" ] || fail 'Read-only CAMSS TOP observation is unavailable.'
    route_before=$(cat "$node/csi_top_result") || fail 'Cannot read CAMSS TOP mux state.'
    echo "CAMSS TOP before receiver test: $route_before"
fi
if [ "$tpg_test" = 1 ]; then
    control=$node/csi_tpg_once
    tpg_result=$node/csi_tpg_result
    [ -r "$tpg_result" ] || fail 'The CSID TPG diagnostic build is required.'
    tpg_before=$(cat "$tpg_result") || fail 'Cannot read CSID TPG status.'
    echo "CSID TPG before: $tpg_before"
    case "$tpg_before" in requested=0\ stage=idle\ *) ;; *) fail 'Expected untouched CSID TPG state.' ;; esac
fi
[ -w "$control" ] || fail 'The requested diagnostic control is not writable.'
initial='status=ready stage=idle errno=0 model=0x0000 cleanup_errno=0 attempts=0 blocked=0 rail_uv=0 load_trial=0 load_vote=0,0,0,0 load_reset=0,0,0,0 boost_trial=0 boost_enable=0 boost_disable=0 boost_uv_before=0 boost_uv_active=0 boost_uv_after=0'
before=$(cat "$result") || fail 'Cannot read the diagnostic result.'
echo "Before: $before"
if [ "$operation" = csi-trial ]; then
    retryable_trial_state "$before" || fail 'Refusing: prior trial did not finish cleanly or the trial limit was reached.'
else
    [ "$before" = "$initial" ] || fail 'Refusing: expected an untouched, ready diagnostic. Do not retry; share this status first.'
fi
if [ "$streaming" = 1 ]; then
    stream_before=$(cat "$node/stream_result") || fail 'Cannot read stream status.'
    echo "Stream before: $stream_before"
    case "$stream_before" in
        profile_loaded=1\ *) ;;
        profile_loaded=0\ *)
            cat "$profile" > "$node/stream_profile" || fail 'The kernel rejected the stream profile; no hardware action performed.'
            stream_before=$(cat "$node/stream_result") || fail 'Cannot verify stream profile.'
            case "$stream_before" in profile_loaded=1\ *) ;; *) fail 'Stream profile was not accepted.' ;; esac
            ;;
        *) fail 'Unexpected stream profile status.' ;;
    esac
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
[ "$(cat "$result")" = "$before" ] || fail 'Diagnostic state changed; no identification performed.'
if [ -n "$clock_option" ]; then
    clock_log=$(mktemp "$clock_log_template") || fail 'Cannot create clock observation log; no sensor test performed.'
    observe_clocks > "$clock_log" 2>&1 &
    clock_pid=$!
fi
if [ -n "$regulator_option" ]; then
    regulator_log=$(mktemp "$regulator_log_template") || fail 'Cannot create regulator observation log; no sensor test performed.'
    observe_regulators > "$regulator_log" 2>&1 &
    regulator_pid=$!
fi
if [ "$operation" = csi-trial ]; then
    if [ "$boost_option" = 1 ]; then
        echo "Performing one CSI-2 trial at settle=$trial_settle (VC0) with boost-bypass enable at the existing board voltage."
    elif [ -n "$trial_clock" ]; then
        echo "Performing one CSI-2 trial at settle=$trial_settle (VC0) with extra gate $trial_clock."
    else
        echo "Performing one CSI-2 trial at settle=$trial_settle (VC0)."
    fi
else
    echo "Performing one $operation attempt."
fi
attempted=1
write_value=$operation
[ "$tpg_test" != 1 ] || write_value=run
[ "$operation" != csi-trial ] || write_value="settle=$trial_settle"
[ "$operation" != csi-trial ] || [ "$load_option" != 1 ] || write_value="$write_value load"
[ "$operation" != csi-trial ] || [ "$boost_option" != 1 ] || write_value="$write_value boost"
[ "$operation" != csi-trial ] || [ "$misc_option" != 1 ] || write_value="$write_value misc"
[ "$operation" != csi-trial ] || [ "$miscfull_option" != 1 ] || write_value="$write_value miscfull"
if [ "$operation" = csi-trial ] && [ -n "$trial_register" ]; then
    write_value="$write_value reg=$trial_register value=$trial_value"
fi
if [ "$operation" = csi-trial ] && [ -n "$trial_clock" ]; then
    write_value="$write_value clock=$trial_clock"
fi
printf '%s\n' "$write_value" > "$control"
exit "$?"
