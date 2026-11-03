/* SPDX-License-Identifier: GPL-2.0-only */
/* Bounded sensor-only stream diagnostic. No CSI, DMA, flash or IR control. */
#ifndef CITYMAN_IRIS_STREAM_H
#define CITYMAN_IRIS_STREAM_H

#define IRIS_IDLE_RECORDS 87
#define IRIS_MODE_RECORDS 30
#define IRIS_PROGRAM_BYTES ((IRIS_IDLE_RECORDS + IRIS_MODE_RECORDS) * 3)
#define IRIS_STREAM_SAMPLES 16
#define IRIS_STREAM_POLL_MS 20
#define IRIS_STREAM_MAX_BURST 8

struct iris_stream_register {
	const char *name;
	u16 address;
	unsigned int width;
};

/* Only fixed identity/control and already-programmed fields; no NVM/image data. */
static const struct iris_stream_register iris_stream_registers[] = {
	{ "model", 0x0000, 2 }, { "mode", 0x0100, 1 },
	{ "reset", 0x0103, 1 }, { "hold", 0x0104, 1 },
	{ "fast", 0x0106, 1 }, { "ctrl", 0x0138, 1 },
	{ "ext", 0x0136, 2 }, { "signal", 0x0111, 1 },
	{ "format", 0x0112, 2 }, { "lanes", 0x0114, 1 },
	{ "pre", 0x0304, 2 }, { "mult", 0x0306, 2 },
	{ "frame", 0x0340, 2 }, { "line", 0x0342, 2 },
	{ "width", 0x034c, 2 }, { "height", 0x034e, 2 },
	{ "coarse", 0x0202, 2 }, { "gain", 0x0204, 2 },
	{ "a06", 0x0a06, 1 }, { "a0a", 0x0a0a, 1 },
};
#define IRIS_READBACK_COUNT (sizeof(iris_stream_registers) / sizeof(iris_stream_registers[0]))

/* Exact concatenation of pinned DCC blocks 0 and ff00, without terminators.
 * Register data is supplied locally, not embedded in the public kernel. */
static const u8 iris_program_sha256[32] = {
	0x75, 0x47, 0x86, 0x97, 0x39, 0x8a, 0xbf, 0x8b,
	0x21, 0x79, 0x6d, 0x40, 0x88, 0x44, 0x24, 0x9a,
	0xf5, 0x4e, 0x05, 0xae, 0x7a, 0x39, 0x9a, 0xff,
	0xfc, 0x33, 0xd5, 0x1d, 0xd8, 0x3e, 0x8e, 0xb5,
};

struct iris_stream {
	u8 program[IRIS_PROGRAM_BYTES];
	bool loaded, requested, entered;
	u8 first, last;
	unsigned int samples, changes, writes, transactions;
	u16 before[IRIS_READBACK_COUNT], after[IRIS_READBACK_COUNT];
	unsigned int before_valid, after_valid;
	int stop_error, readback_error;
	const char *stage;
};

struct iris_stream_io {
	void *context;
	int (*write_bytes)(void *context, u16 address, const u8 *data, unsigned int length);
	int (*read_bytes)(void *context, u16 address, u8 *data, unsigned int length);
	void (*delay_ms)(unsigned int value);
};

static int iris_stream_accept(struct iris_stream *s, const u8 *program,
	size_t length, const u8 digest[32])
{
	s->loaded = false;
	if (length != IRIS_PROGRAM_BYTES ||
		memcmp(digest, iris_program_sha256, sizeof(iris_program_sha256)))
		return -EINVAL;
	memcpy(s->program, program, IRIS_PROGRAM_BYTES);
	s->loaded = true;
	return 0;
}

static int iris_stream_word(const struct iris_stream_io *io, u16 address, u16 value)
{
	u8 data[2] = { value >> 8, value & 0xff };
	/* Original write16 uses one MSB-first transaction, not separate writes. */
	return io->write_bytes(io->context, address, data, sizeof(data));
}

static int iris_stream_byte(const struct iris_stream_io *io, u16 address, u8 value)
{
	return io->write_bytes(io->context, address, &value, 1);
}

static int iris_stream_snapshot(struct iris_stream *s, const struct iris_stream_io *io,
	bool after_start)
{
	u16 *values = after_start ? s->after : s->before;
	unsigned int *valid = after_start ? &s->after_valid : &s->before_valid;
	unsigned int i;
	int rc;
	for (i = 0; i < IRIS_READBACK_COUNT; i++) {
		u8 data[2] = { 0, 0 };
		const struct iris_stream_register *reg = &iris_stream_registers[i];
		rc = io->read_bytes(io->context, reg->address, data, reg->width);
		if (rc) {
			s->readback_error = rc;
			return rc;
		}
		values[i] = reg->width == 2 ? (data[0] << 8) | data[1] : data[0];
		*valid |= 1U << i;
	}
	return 0;
}

static int iris_stream_run(struct iris_stream *s, const struct iris_stream_io *io)
{
	unsigned int i;
	u8 value, previous = 0xff;
	u8 reset_model[2] = { 0, 0 };
	int rc, snapshot_rc;
	if (!s->loaded)
		return -ENODATA;
	s->samples = s->changes = s->writes = s->transactions = 0;
	s->before_valid = s->after_valid = 0;
	s->readback_error = 0;
	memset(s->before, 0xff, sizeof(s->before));
	memset(s->after, 0xff, sizeof(s->after));
	s->first = s->last = 0xff;
	s->stop_error = 0;
	/* Even a failed write can have reached the sensor: always attempt stop. */
	s->entered = true;
	s->stage = "software-reset";
	rc = iris_stream_byte(io, 0x0103, 1);
	if (rc)
		return rc;
	io->delay_ms(20);
	s->stage = "external-clock";
	/* 9.6 MHz in rounded 8.8 MHz units, matching the original conversion. */
	rc = iris_stream_word(io, 0x0136, 0x099a);
	if (rc)
		return rc;
	/* Original Siiri startup rechecks the model after reset and EXTCLK. */
	s->stage = "reset-model";
	rc = io->read_bytes(io->context, 0x0000, reset_model, sizeof(reset_model));
	if (rc)
		return rc;
	if (((reset_model[0] << 8) | reset_model[1]) != 0x0861)
		return -ENODEV;
	for (i = 0; i < IRIS_PROGRAM_BYTES;) {
		u8 data[IRIS_STREAM_MAX_BURST];
		unsigned int length = 1;
		unsigned int end = i < IRIS_IDLE_RECORDS * 3 ?
			IRIS_IDLE_RECORDS * 3 : IRIS_PROGRAM_BYTES;
		u16 address = (s->program[i] << 8) | s->program[i + 1];
		s->stage = i < IRIS_IDLE_RECORDS * 3 ? "idle-program" : "mode-program";
		data[0] = s->program[i + 2];
		/* Match original <=8-byte contiguous bursts, preserving block bounds. */
		while (length < IRIS_STREAM_MAX_BURST && i + length * 3 < end) {
			unsigned int next = i + length * 3;
			u16 next_address = (s->program[next] << 8) | s->program[next + 1];
			if (next_address != (unsigned int)address + length)
				break;
			data[length++] = s->program[next + 2];
		}
		rc = io->write_bytes(io->context, address, data, length);
		if (rc)
			return rc;
		s->writes += length;
		s->transactions++;
		i += length * 3;
	}
	s->stage = "frame-settings";
	rc = iris_stream_byte(io, 0x0104, 1);
	if (!rc)
		rc = iris_stream_word(io, 0x0340, 1116);
	/* 12 lines at 70.08 MHz / 2100 clocks: about 360 us, IR remains off. */
	if (!rc)
		rc = iris_stream_word(io, 0x0202, 12);
	if (!rc)
		rc = iris_stream_word(io, 0x0204, 56);
	if (!rc)
		rc = iris_stream_byte(io, 0x0104, 0);
	if (rc)
		return rc;
	s->stage = "config-readback";
	rc = iris_stream_snapshot(s, io, false);
	if (rc)
		return rc;
	s->stage = "stream-on";
	rc = iris_stream_byte(io, 0x0100, 1);
	/* The original unpause path also writes 0138 after mode select. */
	if (!rc)
		rc = iris_stream_byte(io, 0x0138, 1);
	if (rc)
		return rc;
	s->stage = "frame-counter";
	for (i = 0; i < IRIS_STREAM_SAMPLES; i++) {
		io->delay_ms(IRIS_STREAM_POLL_MS);
		rc = io->read_bytes(io->context, 0x0005, &value, 1);
		if (rc)
			return rc;
		s->samples++;
		/* ff is the original driver's standby sentinel, not a frame. */
		if (value == 0xff)
			continue;
		if (s->first == 0xff)
			s->first = value;
		if (previous != 0xff && previous != value)
			s->changes++;
		previous = s->last = value;
	}
	/* Always save mode/configuration on a completed counter loop, including
	 * a stall. A constant counter alone does not establish absence of packets. */
	rc = s->changes ? 0 : -ETIMEDOUT;
	snapshot_rc = iris_stream_snapshot(s, io, true);
	if (rc)
		return rc;
	if (snapshot_rc)
		return snapshot_rc;
	s->stage = "mode-readback";
	return s->after[1] == 1 ? 0 : -EIO;
}

static int iris_stream_stop(struct iris_stream *s, const struct iris_stream_io *io)
{
	/* Best effort through every stop write, even if an earlier one fails. */
	static const u16 addresses[] = { 0x0104, 0x0138, 0x0106, 0x0100 };
	unsigned int i;
	int rc;
	if (!s->entered)
		return 0;
	for (i = 0; i < sizeof(addresses) / sizeof(addresses[0]); i++) {
		rc = iris_stream_byte(io, addresses[i], 0);
		if (rc && !s->stop_error)
			s->stop_error = rc;
	}
	io->delay_ms(40);
	if (!s->stop_error)
		s->entered = false;
	return s->stop_error;
}
#endif
