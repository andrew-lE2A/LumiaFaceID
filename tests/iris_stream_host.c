/* Exercise the actual stream sequence integrated with actual power cleanup.
 * Synthetic program bytes are injected only as a sequencing fixture; no
 * synthetic input is presented as passing the genuine SHA-256 gate. */
#define CONFIG_CITYMAN_IRIS_STREAM
#define main legacy_sequence_main
#include "iris_sequence_host.c"
#undef main

#define ARRAY_COUNT(a) (sizeof(a) / sizeof((a)[0]))
#define SNAPSHOT_ALL ((1U << IRIS_READBACK_COUNT) - 1)

struct transaction {
    u16 address;
    unsigned int length;
    u8 data[8];
};
static int write_calls, fail_write, read_calls, fail_read, counter_kind;
static unsigned int counter_reads, delay_total;
static bool held_release;
static u8 sensor_registers[65536];
static struct transaction write_log[256], read_log[256];
static const struct {
    u16 address;
    unsigned int length;
} expected_readback[] = {
    {0x0000, 2}, {0x0100, 1}, {0x0103, 1}, {0x0104, 1},
    {0x0106, 1}, {0x0138, 1}, {0x0136, 2}, {0x0111, 1},
    {0x0112, 2}, {0x0114, 1}, {0x0304, 2}, {0x0306, 2},
    {0x0340, 2}, {0x0342, 2}, {0x034c, 2}, {0x034e, 2},
    {0x0202, 2}, {0x0204, 2}, {0x0a06, 1}, {0x0a0a, 1},
    {0x0130, 2}, {0x0300, 2}, {0x0302, 2}, {0x0308, 2}, {0x030a, 2},
    {0x0110, 1},
};

static int stream_write(void *context, u16 address, const u8 *data,
                        unsigned int length)
{
    struct cityman_iris *iris = context;
    struct transaction *log;
    assert(iris->cci_on && iris->clock_on && iris->gpio_owned);
    assert(length && length <= 8 && (unsigned int)address + length <= 65536);
    assert((unsigned int)write_calls < ARRAY_COUNT(write_log));
    log = &write_log[write_calls++];
    log->address = address; log->length = length;
    memcpy(log->data, data, length);
    /* Model a lost hold release to ensure readbacks survive power cleanup. */
    if (counter_kind == 5 && address == 0x0104 && !data[0] && !held_release)
        held_release = true;
    else
        memcpy(sensor_registers + address, data, length);
    /* A negative result need not mean that the sensor ignored the write. */
    return write_calls == fail_write ? -EIO : 0;
}
static int stream_read(void *context, u16 address, u8 *data,
                       unsigned int length)
{
    struct cityman_iris *iris = context;
    struct transaction *log;
    assert(iris->cci_on && iris->clock_on && iris->gpio_owned);
    assert(length && length <= 2 && (unsigned int)address + length <= 65536);
    assert((unsigned int)read_calls < ARRAY_COUNT(read_log));
    log = &read_log[read_calls++];
    log->address = address; log->length = length;
    if (read_calls == fail_read) return -EIO;
    if (address == 5) {
        assert(length == 1);
        counter_reads++;
        if (counter_kind == 1) *data = 7;
        else if (counter_kind == 2) *data = 0xff;
        else if (counter_kind == 3) *data = counter_reads % 2 ? 7 : 0xff;
        else *data = (250 + counter_reads) % 255;
    } else {
        memcpy(data, sensor_registers + address, length);
        if (address == 0x0100 && counter_kind == 4) *data = 0;
        if (address == 0x0111 && counter_kind == 6) *data = 0;
    }
    memcpy(log->data, data, length);
    return 0;
}
static void stream_delay(unsigned int value)
{
    assert(value == 10 || value == 20 || value == 40);
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
    counter_reads = delay_total = 0; held_release = false;
    memset(sensor_registers, 0, sizeof(sensor_registers));
    memset(write_log, 0, sizeof(write_log)); memset(read_log, 0, sizeof(read_log));
    sensor_registers[0] = IRIS_MODEL >> 8; sensor_registers[1] = IRIS_MODEL & 0xff;
    /* Distinct fixture values exercise big-endian clock snapshots even after
     * a stalled counter. These are not a real sensor program or clock model. */
    sensor_registers[0x0130] = 0x12; sensor_registers[0x0131] = 0x34;
    sensor_registers[0x0300] = 0x23; sensor_registers[0x0301] = 0x45;
    sensor_registers[0x0302] = 0x34; sensor_registers[0x0303] = 0x56;
    sensor_registers[0x0308] = 0x45; sensor_registers[0x0309] = 0x67;
    sensor_registers[0x030a] = 0x56; sensor_registers[0x030b] = 0x78;
    state.stream.loaded = state.stream.requested = true;
    /* Adjacent addresses across the block boundary must stay separate bursts. */
    for (i = 0; i < IRIS_PROGRAM_BYTES; i += 3) {
        unsigned int address = 0x3000 + i / 3;
        state.stream.program[i] = address >> 8;
        state.stream.program[i + 1] = address;
        state.stream.program[i + 2] = i;
    }
}
static void stopped(void)
{
    static const u16 addresses[] = {0x0104, 0x0138, 0x0106, 0x0100};
    unsigned int i;
    assert(write_calls >= 4);
    for (i = 0; i < ARRAY_COUNT(addresses); i++) {
        const struct transaction *log = &write_log[write_calls - 4 + i];
        assert(log->address == addresses[i] && log->length == 1 && !log->data[0]);
    }
    assert(!sensor_registers[0x0100] && !sensor_registers[0x0104]);
    assert(!sensor_registers[0x0138] && !sensor_registers[0x0106]);
    assert(!state.stream.entered && !state.stream.stop_error);
    assert(delay_total <= 20 + IRIS_STREAM_SAMPLES * IRIS_STREAM_POLL_MS + 40);
    balanced();
}
static unsigned int check_program_transactions(void)
{
    unsigned int i, next = 0, bursts = 0;
    for (i = 0; i < (unsigned int)write_calls; i++) {
        const struct transaction *log = &write_log[i];
        unsigned int j, expected_length, block_end;
        if (log->address < 0x3000 || log->address >= 0x3000 + IRIS_PROGRAM_BYTES / 3)
            continue;
        block_end = next < IRIS_IDLE_RECORDS ? IRIS_IDLE_RECORDS : IRIS_PROGRAM_BYTES / 3;
        expected_length = block_end - next;
        if (expected_length > 8) expected_length = 8;
        assert(log->address == 0x3000 + next && log->length == expected_length);
        for (j = 0; j < log->length; j++)
            assert(log->data[j] == state.stream.program[(next + j) * 3 + 2]);
        next += log->length; bursts++;
    }
    assert(next == IRIS_PROGRAM_BYTES / 3);
    assert(state.stream.transactions == bursts);
    return bursts;
}
static void check_word_transaction(u16 address, u16 value)
{
    unsigned int i, found = 0;
    for (i = 0; i < (unsigned int)write_calls; i++) {
        const struct transaction *log = &write_log[i];
        if (log->address == address) {
            assert(log->length == 2);
            assert(log->data[0] == value >> 8 && log->data[1] == (value & 0xff));
            found++;
        }
        assert(log->address != address + 1);
    }
    assert(found == 1);
}
static void check_snapshot_transactions(void)
{
    unsigned int i, before_info = 1 + IRIS_READBACK_COUNT;
    unsigned int counter_before = before_info + IRIS_SENSOR_INFO_COUNT;
    unsigned int sample_start = counter_before + 1;
    unsigned int after_snapshot = sample_start + IRIS_STREAM_SAMPLES;
    assert(IRIS_READBACK_COUNT == ARRAY_COUNT(expected_readback));
    assert(read_calls == after_snapshot + IRIS_READBACK_COUNT + IRIS_SENSOR_INFO_COUNT + 1);
    assert(read_log[0].address == 0 && read_log[0].length == 2);
    for (i = 0; i < IRIS_READBACK_COUNT; i++) {
        const struct transaction *before = &read_log[1 + i];
        const struct transaction *after = &read_log[after_snapshot + i];
        assert(before->address == expected_readback[i].address);
        assert(after->address == expected_readback[i].address);
        assert(before->length == expected_readback[i].length);
        assert(after->length == expected_readback[i].length);
    }
    for (i = 0; i < IRIS_SENSOR_INFO_COUNT; i++) {
        const struct transaction *before = &read_log[before_info + i];
        const struct transaction *after = &read_log[after_snapshot + IRIS_READBACK_COUNT + i];
        assert(before->address == iris_sensor_info_registers[i].address);
        assert(after->address == iris_sensor_info_registers[i].address);
        assert(before->length == iris_sensor_info_registers[i].width);
        assert(after->length == iris_sensor_info_registers[i].width);
    }
    assert(read_log[counter_before].address == 5 && read_log[counter_before].length == 1);
    for (i = sample_start; i < sample_start + IRIS_STREAM_SAMPLES; i++)
        assert(read_log[i].address == 5 && read_log[i].length == 1);
    assert(read_log[after_snapshot + IRIS_READBACK_COUNT + IRIS_SENSOR_INFO_COUNT].address == 5);
    assert(state.stream.before_valid == SNAPSHOT_ALL && state.stream.after_valid == SNAPSHOT_ALL);
    assert(state.stream.sensor_info_before_valid == ((1U << IRIS_SENSOR_INFO_COUNT) - 1));
    assert(state.stream.sensor_info_after_valid == ((1U << IRIS_SENSOR_INFO_COUNT) - 1));
    assert(state.stream.before[0] == IRIS_MODEL && state.stream.after[0] == IRIS_MODEL);
    assert(state.stream.before[1] == 0 && state.stream.after[1] == (counter_kind == 4 ? 0 : 1));
    assert(state.stream.before[5] == 0 && state.stream.after[5] == 1);
    assert(state.stream.before[6] == 0x099a && state.stream.after[6] == 0x099a);
    assert(state.stream.before[12] == 1116 && state.stream.after[12] == 1116);
    assert(state.stream.before[16] == 12 && state.stream.after[16] == 12);
    assert(state.stream.before[17] == 56 && state.stream.after[17] == 56);
    assert(state.stream.before[20] == 0x1234 && state.stream.after[20] == 0x1234);
    assert(state.stream.before[21] == 0x2345 && state.stream.after[21] == 0x2345);
    assert(state.stream.before[22] == 0x3456 && state.stream.after[22] == 0x3456);
    assert(state.stream.before[23] == 0x4567 && state.stream.after[23] == 0x4567);
    assert(state.stream.before[24] == 0x5678 && state.stream.after[24] == 0x5678);
    assert(state.stream.before[25] == 0 && state.stream.after[25] == 0);
    assert(!state.stream.readback_error);
}
#ifndef IRIS_STREAM_MAIN
#define IRIS_STREAM_MAIN main
#endif
int IRIS_STREAM_MAIN(void)
{
    int i, baseline_writes, startup_writes, baseline_reads, count = 0;
    unsigned int baseline_bursts;
    u8 invalid_hash[32] = {0};
    legacy_sequence_main();
    reset_stream(); assert(!iris_identify(&state));
    assert(!strcmp(state.status, "sensor-streamed"));
    assert(state.stream.changes == 15 && state.stream.samples == IRIS_STREAM_SAMPLES);
    assert(state.stream.counter_before == 251 && state.stream.first == 252 && state.stream.last == 12);
    assert(state.stream.writes == IRIS_PROGRAM_BYTES / 3);
    assert(!strcmp(state.stream.stage, "mode-readback"));
    baseline_writes = write_calls; startup_writes = baseline_writes - 4;
    baseline_reads = read_calls; baseline_bursts = check_program_transactions();
    check_word_transaction(0x0136, 0x099a); check_word_transaction(0x0340, 1116);
    check_word_transaction(0x0202, 12); check_word_transaction(0x0204, 56);
    check_snapshot_transactions(); stopped(); count++;
    /* Every startup/program/on transaction may fail after being applied. */
    for (i = 1; i <= startup_writes; i++) {
        reset_stream(); fail_write = i;
        assert(iris_identify(&state) == -EIO);
        assert(write_calls == i + 4);
        stopped(); count++;
    }
    /* Cover the post-reset identity, both snapshots, and every counter read. */
    for (i = 1; i <= baseline_reads; i++) {
        reset_stream(); fail_read = i;
        if (i == baseline_reads) {
            assert(!iris_identify(&state));
            assert(state.stream.counter_after_stop_errno == -EIO);
            assert(!state.stream.counter_after_stop_valid);
            stopped(); count++;
            continue;
        }
        assert(iris_identify(&state) == -EIO && read_calls >= i && read_calls <= i + 1);
        if (i == 1) {
            assert(!state.stream.before_valid && !state.stream.after_valid);
            assert(counter_reads == 1 && !state.stream.samples && !state.stream.writes);
            assert(state.stream.counter_after_stop_valid);
            assert(!state.stream.readback_error);
            assert(!strcmp(state.stream.stage, "reset-model"));
        } else if ((unsigned int)i <= 1 + IRIS_READBACK_COUNT) {
            assert(state.stream.before_valid == (1U << (i - 2)) - 1);
            assert(!state.stream.after_valid && counter_reads == 1 && !state.stream.samples);
            assert(state.stream.readback_error == -EIO);
        } else if ((unsigned int)i <= 1 + IRIS_READBACK_COUNT + IRIS_SENSOR_INFO_COUNT) {
            unsigned int info_read = i - IRIS_READBACK_COUNT - 2;
            assert(state.stream.before_valid == SNAPSHOT_ALL && !state.stream.after_valid);
            assert(state.stream.sensor_info_before_valid == ((1U << info_read) - 1));
            assert(counter_reads == 1 && !state.stream.samples && state.stream.readback_error == -EIO);
        } else if ((unsigned int)i == 2 + IRIS_READBACK_COUNT + IRIS_SENSOR_INFO_COUNT) {
            assert(state.stream.before_valid == SNAPSHOT_ALL);
            assert(state.stream.sensor_info_before_valid == ((1U << IRIS_SENSOR_INFO_COUNT) - 1));
            assert(counter_reads == 1 && state.stream.samples == 0);
            assert(state.stream.counter_before_errno == -EIO);
        } else if ((unsigned int)i <= 2 + IRIS_READBACK_COUNT + IRIS_SENSOR_INFO_COUNT + IRIS_STREAM_SAMPLES) {
            assert(state.stream.before_valid == SNAPSHOT_ALL && !state.stream.after_valid);
            assert(state.stream.sensor_info_before_valid == ((1U << IRIS_SENSOR_INFO_COUNT) - 1));
            assert(state.stream.samples == (unsigned int)i - IRIS_READBACK_COUNT - IRIS_SENSOR_INFO_COUNT - 3);
            assert(counter_reads == state.stream.samples + 2);
            assert(!state.stream.readback_error);
        } else {
            unsigned int position = i - IRIS_READBACK_COUNT - IRIS_SENSOR_INFO_COUNT - IRIS_STREAM_SAMPLES - 3;
            assert(state.stream.before_valid == SNAPSHOT_ALL);
            assert(state.stream.sensor_info_before_valid == ((1U << IRIS_SENSOR_INFO_COUNT) - 1));
            assert(counter_reads == IRIS_STREAM_SAMPLES + 2);
            if (position < IRIS_READBACK_COUNT) {
                assert(state.stream.after_valid == (1U << position) - 1);
                assert(!state.stream.sensor_info_after_valid);
            } else {
                assert(state.stream.after_valid == SNAPSHOT_ALL);
                assert(state.stream.sensor_info_after_valid == (1U << (position - IRIS_READBACK_COUNT)) - 1);
            }
            assert(state.stream.readback_error == -EIO);
        }
        stopped(); count++;
    }
    for (i = 1; i <= 3; i++) {
        reset_stream(); counter_kind = i;
        assert(iris_identify(&state) == -ETIMEDOUT);
        assert(!state.stream.changes && state.stream.samples == IRIS_STREAM_SAMPLES);
        assert(!strcmp(state.stream.stage, "frame-counter"));
        check_snapshot_transactions(); stopped(); count++;
    }
    /* A failed post snapshot never erases the primary stalled-counter error. */
    for (i = 0; (unsigned int)i < IRIS_READBACK_COUNT + IRIS_SENSOR_INFO_COUNT; i++) {
        reset_stream(); counter_kind = 1;
        fail_read = 3 + IRIS_READBACK_COUNT + IRIS_SENSOR_INFO_COUNT + IRIS_STREAM_SAMPLES + i;
        assert(iris_identify(&state) == -ETIMEDOUT);
        assert(!state.stream.changes && state.stream.samples == IRIS_STREAM_SAMPLES);
        assert(!strcmp(state.stream.stage, "frame-counter"));
        assert(state.stream.before_valid == SNAPSHOT_ALL);
        assert(state.stream.sensor_info_before_valid == ((1U << IRIS_SENSOR_INFO_COUNT) - 1));
        if ((unsigned int)i < IRIS_READBACK_COUNT) {
            assert(state.stream.after_valid == (1U << i) - 1);
            assert(!state.stream.sensor_info_after_valid);
        } else {
            assert(state.stream.after_valid == SNAPSHOT_ALL);
            assert(state.stream.sensor_info_after_valid == (1U << (i - IRIS_READBACK_COUNT)) - 1);
        }
        assert(state.stream.readback_error == -EIO && read_calls == fail_read + 1);
        stopped(); count++;
    }
    reset_stream();
    fail_read = 3 + 2 * (IRIS_READBACK_COUNT + IRIS_SENSOR_INFO_COUNT) + IRIS_STREAM_SAMPLES;
    assert(!iris_identify(&state));
    assert(state.stream.counter_after_stop_errno == -EIO && !state.stream.counter_after_stop_valid);
    stopped(); count++;
    reset_stream(); counter_kind = 4;
    assert(iris_identify(&state) == -EIO);
    check_snapshot_transactions(); stopped(); count++;
    reset_stream(); counter_kind = 5;
    assert(!iris_identify(&state));
    assert(state.stream.before[3] == 1 && state.stream.after[3] == 1);
    check_snapshot_transactions(); stopped(); count++;
    for (i = startup_writes + 1; i <= baseline_writes; i++) {
        int before;
        reset_stream(); fail_write = i;
        assert(iris_identify(&state) == -EIO);
        assert(state.blocked && state.cleanup_error == -EIO);
        assert(state.stream.stop_error == -EIO && write_calls == baseline_writes);
        assert(!gpio_owned && !cci.ref_count && !clock_refs[0] && !clock_refs[1]);
        assert(!enables[0] && !enables[1] && !enables[2] && !enables[3]);
        before = write_calls;
        assert(iris_identify(&state) == -EBUSY && write_calls == before);
        count++;
    }
    reset_stream(); sensor_registers[0] = 0x12; sensor_registers[1] = 0x34;
    assert(iris_identify(&state) == -ENODEV);
    assert(write_calls == 6 && read_calls == 2);
    assert(write_log[0].address == 0x0103 && write_log[1].address == 0x0136);
    assert(!state.stream.writes && !state.stream.transactions);
    assert(!state.stream.before_valid && !state.stream.after_valid);
    assert(!state.stream.counter_before_valid && state.stream.counter_after_stop_valid);
    assert(!strcmp(state.stream.stage, "reset-model"));
    stopped(); count++;
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
    reset_stream();
    state.stream.override_requested = true;
    state.stream.override_address = 0x3000;
    state.stream.override_value = 0x5a;
    assert(!iris_identify(&state));
    assert(sensor_registers[0x3000] == 0x5a);
    assert(state.stream.override_readback_valid && state.stream.override_readback == 0x5a);
    stopped(); count++;
    printf("Baseline: %d startup transactions, %u profile bursts, %d read transactions\n",
           startup_writes, baseline_bursts, baseline_reads);
    printf("%d actual integrated stream scenarios passed\n", count);
    return 0;
}
