/* Verify actual power/program/receiver/start/stop/unwind ordering. */
#define CONFIG_CITYMAN_IRIS_CSI
#define IRIS_STREAM_MAIN stream_regression_main
#include "iris_stream_host.c"
static int receiver_begin, receiver_end, receiver_samples, receiver_failure, receiver_cleanup_failure;
int cityman_iris_csi_begin(struct iris_csi *s) {
    assert(sensor_registers[0x0100]==0 && sensor_registers[0x0104]==0);
    assert(state.stream.before_valid==SNAPSHOT_ALL);
    assert(state.stream.writes==117 && state.cci_on);
    receiver_begin++; s->error=receiver_failure;
    return receiver_failure;
}
int cityman_iris_csi_end(struct iris_csi *s) {
    assert(!sensor_registers[0x0100] && !sensor_registers[0x0104]);
    receiver_end++;
    s->cleanup_error=receiver_cleanup_failure;
    return receiver_cleanup_failure;
}
void cityman_iris_csi_sample(struct iris_csi *s) {
    assert(s==&state.csi && sensor_registers[0x0100]==1 && state.cci_on);
    assert(receiver_begin==1 && !receiver_end);
    receiver_samples++;
}
int main(void) {
    unsigned int n, selection_write = 0, baseline_writes = 0;
    struct transaction baseline_log[256];
    assert(!stream_regression_main()); /* all previous stream tests, CSI disabled */
    for(n=0;n<10;n++) {
        reset_stream(); state.csi.requested=true;
        receiver_begin=receiver_end=receiver_samples=receiver_failure=receiver_cleanup_failure=0;
        if(n==1) receiver_failure=-EBUSY;
        if(n==2) receiver_cleanup_failure=-EIO;
        if(n==3) counter_kind=1;
        if(n==4) fail_write=1;
        if(n>=5) state.stream.select_csi2=true;
        if(n==6) counter_kind=1;
        if(n==7) counter_kind=6;
        if(n==8) { assert(selection_write); fail_write=selection_write; }
        if(n==9) { assert(selection_write); fail_write=selection_write+1; }
        assert(iris_identify(&state)==((n==0 || n==5) ? 0 : n==1 ? -EBUSY : (n==3 || n==6) ? -ETIMEDOUT : -EIO));
        assert(receiver_begin==((n==4 || n==7 || n==8 || n==9) ? 0 : 1) && receiver_end==1);
        assert(receiver_samples==((n==1 || n==4 || n==7 || n==8 || n==9) ? 0 : 1));
        assert(state.blocked==(n==2));
        assert(state.cleanup_error==(n==2 ? -EIO : 0));
        if(n==0) {
            baseline_writes=write_calls;
            memcpy(baseline_log,write_log,sizeof(baseline_log));
        }
        if(n==5 || n==6) {
            unsigned int i, j=0, overrides=0;
            assert((unsigned int)write_calls==baseline_writes+2);
            assert(state.stream.before[7]==2 && state.stream.after[7]==2);
            assert(state.stream.before[25]==0 && state.stream.after[25]==0);
            assert(state.stream.virtual_channel_before_valid &&
                   state.stream.virtual_channel_before==0);
            assert(state.stream.before_valid==SNAPSHOT_ALL && state.stream.after_valid==SNAPSHOT_ALL);
            for(i=0;i<(unsigned int)write_calls;i++) {
                if(write_log[i].address==0x0111 && write_log[i].data[0]==2) {
                    selection_write=i+1; overrides++; continue;
                }
                if(write_log[i].address==0x0110 && write_log[i].data[0]==0) {
                    assert(selection_write==i);
                    overrides++; continue;
                }
                assert(j<baseline_writes && write_log[i].address==baseline_log[j].address);
                assert(write_log[i].length==baseline_log[j].length);
                assert(!memcmp(write_log[i].data,baseline_log[j].data,write_log[i].length)); j++;
            }
            assert(overrides==2 && j==baseline_writes);
        }
        if(n==7) assert(!strcmp(state.stream.stage,"csi2-interface"));
        if(n!=2) stopped();
        else {
            unsigned int i;
            for(i=0;i<4;i++) assert(!enables[i] && !state.enabled[i]);
            assert(!gpio_owned && !state.gpio_owned && !cci.ref_count && !state.cci_on);
            assert(!clock_refs[0] && !clock_refs[1] && source.rate==24000000);
        }
    }
    puts("9 production sensor/receiver integration scenarios passed");
    return 0;
}
