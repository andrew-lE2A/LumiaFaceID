/* SPDX-License-Identifier: GPL-2.0-only */
/* Bounded sensor-only stream diagnostic. No CSI, DMA, flash or IR control. */
#ifndef CITYMAN_IRIS_STREAM_H
#define CITYMAN_IRIS_STREAM_H

#define IRIS_IDLE_RECORDS 87
#define IRIS_MODE_RECORDS 30
#define IRIS_PROGRAM_BYTES ((IRIS_IDLE_RECORDS + IRIS_MODE_RECORDS) * 3)
#define IRIS_STREAM_SAMPLES 16
#define IRIS_STREAM_POLL_MS 20

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
	unsigned int samples, changes, writes;
	int stop_error;
	const char *stage;
};

struct iris_stream_io {
	void *context;
	int (*write8)(void *context, u16 address, u8 value);
	int (*read8)(void *context, u16 address, u8 *value);
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
	int rc = io->write8(io->context, address, value >> 8);
	return rc ? rc : io->write8(io->context, address + 1, value & 0xff);
}

static int iris_stream_run(struct iris_stream *s, const struct iris_stream_io *io)
{
	unsigned int i;
	u8 value, previous = 0xff;
	int rc;
	if (!s->loaded)
		return -ENODATA;
	s->samples = s->changes = s->writes = 0;
	s->first = s->last = 0xff;
	s->stop_error = 0;
	/* Even a failed write can have reached the sensor: always attempt stop. */
	s->entered = true;
	s->stage = "software-reset";
	rc = io->write8(io->context, 0x0103, 1);
	if (rc)
		return rc;
	io->delay_ms(20);
	s->stage = "external-clock";
	/* 9.6 MHz in rounded 8.8 MHz units, matching the original conversion. */
	rc = iris_stream_word(io, 0x0136, 0x099a);
	if (rc)
		return rc;
	for (i = 0; i < IRIS_PROGRAM_BYTES; i += 3) {
		s->stage = i < IRIS_IDLE_RECORDS * 3 ? "idle-program" : "mode-program";
		rc = io->write8(io->context, (s->program[i] << 8) | s->program[i + 1],
			s->program[i + 2]);
		if (rc)
			return rc;
		s->writes++;
	}
	s->stage = "frame-settings";
	rc = io->write8(io->context, 0x0104, 1);
	if (!rc)
		rc = iris_stream_word(io, 0x0340, 1116);
	/* 12 lines at 70.08 MHz / 2100 clocks: about 360 us, IR remains off. */
	if (!rc)
		rc = iris_stream_word(io, 0x0202, 12);
	if (!rc)
		rc = iris_stream_word(io, 0x0204, 56);
	if (!rc)
		rc = io->write8(io->context, 0x0104, 0);
	if (rc)
		return rc;
	s->stage = "stream-on";
	rc = io->write8(io->context, 0x0100, 1);
	/* The original unpause path also writes 0138 after mode select. */
	if (!rc)
		rc = io->write8(io->context, 0x0138, 1);
	if (rc)
		return rc;
	s->stage = "frame-counter";
	for (i = 0; i < IRIS_STREAM_SAMPLES; i++) {
		io->delay_ms(IRIS_STREAM_POLL_MS);
		rc = io->read8(io->context, 0x0005, &value);
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
	if (!s->changes)
		return -ETIMEDOUT;
	s->stage = "mode-readback";
	rc = io->read8(io->context, 0x0100, &value);
	return rc ? rc : (value == 1 ? 0 : -EIO);
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
		rc = io->write8(io->context, addresses[i], 0);
		if (rc && !s->stop_error)
			s->stop_error = rc;
	}
	io->delay_ms(40);
	if (!s->stop_error)
		s->entered = false;
	return s->stop_error;
}
#endif
