/* Exercise the actual stream sequence integrated with actual power cleanup.
 * Synthetic program bytes are injected only as a sequencing fixture; no
 * synthetic input is presented as passing the genuine SHA-256 gate. */
#define CONFIG_CITYMAN_IRIS_STREAM
#define main legacy_sequence_main
#include "iris_sequence_host.c"
#undef main

static int write_calls, fail_write, read_calls, fail_read, counter_kind;
static unsigned int delay_total;
static u8 sensor_registers[65536];
static unsigned int last_addresses[4];

static int stream_write(void *context, u16 address, u8 value)
{
    struct cityman_iris *iris = context;
    assert(iris->cci_on && iris->clock_on && iris->gpio_owned);
    last_addresses[write_calls % 4] = address;
    write_calls++;
    /* A negative result need not mean that the sensor ignored the write. */
    sensor_registers[address] = value;
    return write_calls == fail_write ? -EIO : 0;
}
static int stream_read(void *context, u16 address, u8 *value)
{
    struct cityman_iris *iris = context;
    assert(iris->cci_on && iris->clock_on && iris->gpio_owned);
    read_calls++;
    if (read_calls == fail_read) return -EIO;
    if (address == 5) {
        if (counter_kind == 1) *value = 7;
        else if (counter_kind == 2) *value = 0xff;
        else if (counter_kind == 3) *value = read_calls % 2 ? 7 : 0xff;
        else *value = (250 + read_calls) % 255;
    } else {
        assert(address == 0x0100);
        *value = counter_kind == 4 ? 0 : sensor_registers[address];
    }
    return 0;
}
static void stream_delay(unsigned int value)
{
    assert(value == 20 || value == 40);
    delay_total += value;
}
static struct iris_stream_io iris_stream_io(struct cityman_iris *iris)
{
    struct iris_stream_io io = {iris, stream_write, stream_read, stream_delay};
    return io;
}
static void reset_stream(void)
{
    unsigned int i;
    reset(NULL, 0);
    write_calls = fail_write = read_calls = fail_read = counter_kind = 0;
    delay_total = 0;
    memset(sensor_registers, 0, sizeof(sensor_registers));
    state.stream.loaded = state.stream.requested = true;
    for (i = 0; i < IRIS_PROGRAM_BYTES; i += 3) {
        unsigned int address = 0x3000 + i / 3;
        state.stream.program[i] = address >> 8;
        state.stream.program[i + 1] = address;
        state.stream.program[i + 2] = i;
    }
}
static void stopped(void)
{
    assert(!sensor_registers[0x0100] && !sensor_registers[0x0104]);
    assert(!sensor_registers[0x0138] && !sensor_registers[0x0106]);
    assert(!state.stream.entered && !state.stream.stop_error);
    assert(!state.stream.stop_error && delay_total <= 380);
    balanced();
}
int main(void)
{
    int i, count = 0;
    u8 invalid_hash[32] = {0};
    legacy_sequence_main();
    reset_stream(); assert(!iris_identify(&state));
    assert(!strcmp(state.status, "sensor-streamed"));
    assert(state.stream.changes == 15 && state.stream.samples == 16);
    assert(state.stream.first == 251 && state.stream.last == 11);
    assert(state.stream.writes == 117 && write_calls == 134);
    assert(sensor_registers[0x0340] == 4 && sensor_registers[0x0341] == 0x5c);
    assert(sensor_registers[0x0202] == 0 && sensor_registers[0x0203] == 12);
    assert(sensor_registers[0x0204] == 0 && sensor_registers[0x0205] == 56);
    stopped(); count++;
    /* Every startup/program/on write may fail after being applied. */
    for (i = 1; i <= 130; i++) {
        reset_stream(); fail_write = i;
        assert(iris_identify(&state) == -EIO);
        stopped(); count++;
    }
    for (i = 1; i <= 17; i++) {
        reset_stream(); fail_read = i;
        assert(iris_identify(&state) == -EIO);
        stopped(); count++;
    }
    for (i = 1; i <= 3; i++) {
        reset_stream(); counter_kind = i;
        assert(iris_identify(&state) == -ETIMEDOUT);
        assert(!state.stream.changes && state.stream.samples == 16);
        stopped(); count++;
    }
    reset_stream(); counter_kind = 4;
    assert(iris_identify(&state) == -EIO); stopped(); count++;
    for (i = 131; i <= 134; i++) {
        int before;
        reset_stream(); fail_write = i;
        assert(iris_identify(&state) == -EIO);
        assert(state.blocked && state.cleanup_error == -EIO);
        assert(state.stream.stop_error == -EIO && write_calls == 134);
        assert(!gpio_owned && !cci.ref_count && !clock_refs[0] && !clock_refs[1]);
        assert(!enables[0] && !enables[1] && !enables[2] && !enables[3]);
        before = write_calls;
        assert(iris_identify(&state) == -EBUSY && write_calls == before);
        count++;
    }
    reset_stream(); returned_model = 0x1234;
    assert(iris_identify(&state) == -ENODEV && !write_calls);
    balanced(); count++;
    reset_stream(); state.stream.requested = false;
    assert(!iris_identify(&state) && !write_calls);
    assert(!strcmp(state.status, "identified")); balanced(); count++;
    reset_stream(); state.stream.loaded = false;
    assert(iris_identify(&state) == -ENODATA && !write_calls);
    balanced(); count++;
    reset_stream();
    assert(iris_stream_accept(&state.stream, state.stream.program,
           IRIS_PROGRAM_BYTES, invalid_hash) == -EINVAL && !state.stream.loaded);
    assert(iris_stream_accept(&state.stream, state.stream.program,
           IRIS_PROGRAM_BYTES - 1, iris_program_sha256) == -EINVAL);
    count++;
    printf("%d actual integrated stream scenarios passed\n", count);
    return 0;
}
