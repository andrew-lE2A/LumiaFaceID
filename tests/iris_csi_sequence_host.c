/* Verify actual power/program/receiver/start/stop/unwind ordering. */
#define CONFIG_CITYMAN_IRIS_CSI
#define IRIS_STREAM_MAIN stream_regression_main
#include "iris_stream_host.c"
static int receiver_begin, receiver_end, receiver_failure, receiver_cleanup_failure;
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
int main(void) {
    unsigned int n;
    assert(!stream_regression_main()); /* all previous stream tests, CSI disabled */
    for(n=0;n<5;n++) {
        reset_stream(); state.csi.requested=true;
        receiver_begin=receiver_end=receiver_failure=receiver_cleanup_failure=0;
        if(n==1) receiver_failure=-EBUSY;
        if(n==2) receiver_cleanup_failure=-EIO;
        if(n==3) counter_kind=1;
        if(n==4) fail_write=1;
        assert(iris_identify(&state)==(n==0 ? 0 : n==1 ? -EBUSY : n==3 ? -ETIMEDOUT : -EIO));
        assert(receiver_begin==(n==4 ? 0 : 1) && receiver_end==1);
        assert(state.blocked==(n==2));
        assert(state.cleanup_error==(n==2 ? -EIO : 0));
        if(n!=2) stopped();
        else {
            unsigned int i;
            for(i=0;i<4;i++) assert(!enables[i] && !state.enabled[i]);
            assert(!gpio_owned && !state.gpio_owned && !cci.ref_count && !state.cci_on);
            assert(!clock_refs[0] && !clock_refs[1] && source.rate==24000000);
        }
    }
    puts("5 production sensor/receiver integration scenarios passed");
    return 0;
}
