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
#define IRIS_STREAM_CSI_VIRTUAL_CHANNEL 0

struct iris_stream_register {
	const char *name;
	u16 address;
	unsigned int width;
};
/* Startup values read by the original Windows driver; read-only diagnostics. */
static const struct iris_stream_register iris_sensor_info_registers[] = {
	{ "gain_capability", 0x0080, 2 },
	{ "gain_code_min", 0x0084, 2 }, { "gain_code_max", 0x0086, 2 },
	{ "gain_code_step", 0x0088, 2 },
	{ "gain_code_reserved", 0x008a, 2 },
	{ "gain_m0", 0x008c, 2 }, { "gain_c0", 0x008e, 2 },
	{ "gain_m1", 0x0090, 2 }, { "gain_c1", 0x0092, 2 },
	{ "coarse_min", 0x1004, 2 }, { "coarse_max_margin", 0x1006, 2 },
	{ "black_level", 0x0008, 2 }, { "pixel_order", 0x0006, 1 },
	{ "pixel_order_control", 0x0101, 1 }, { "mono_capability", 0x11ca, 1 },
	{ "flash_capability_00", 0x1a00, 1 },
	{ "flash_capability_01", 0x1a01, 1 },
	{ "flash_capability_02", 0x1a02, 1 },
	{ "flash_capability_03", 0x1a03, 1 },
	{ "flash_capability_04", 0x1a04, 1 },
	{ "flash_capability_05", 0x1a05, 1 },
	{ "flash_capability_06", 0x1a06, 1 },
	{ "flash_capability_07", 0x1a07, 1 },
	{ "flash_capability_08", 0x1a08, 1 },
	{ "flash_capability_09", 0x1a09, 1 },
	{ "flash_capability_0a", 0x1a0a, 1 },
	{ "flash_capability_0b", 0x1a0b, 1 },
	{ "flash_capability_0c", 0x1a0c, 1 },
	{ "flash_capability_0d", 0x1a0d, 1 },
	{ "flash_capability_0e", 0x1a0e, 1 },
	{ "flash_capability_0f", 0x1a0f, 1 },
};
#define IRIS_SENSOR_INFO_COUNT (sizeof(iris_sensor_info_registers) / \
	 sizeof(iris_sensor_info_registers[0]))

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
	/* Already written by the exact mode program. Keep earlier indices stable.
	 * Raw latch evidence only: these reads do not measure PLL lock/MIPI rate. */
	{ "clk0130", 0x0130, 2 },
	{ "vt_pix", 0x0300, 2 }, { "vt_sys", 0x0302, 2 },
	{ "op_pix", 0x0308, 2 }, { "op_sys", 0x030a, 2 },
	{ "virtual_channel", 0x0110, 1 },
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
	bool loaded, requested, entered, select_csi2;
	bool override_requested;
	u16 override_address;
	u8 override_value, override_readback;
	bool override_readback_valid;
	u8 virtual_channel_before;
	bool virtual_channel_before_valid;
	u16 extclk_immediate;
	int extclk_immediate_errno;
	bool extclk_immediate_valid;
	u16 extclk_single, control_single, control_pair;
	int extclk_single_errno, control_single_errno, control_pair_errno;
	u8 first, last, counter_before;
	bool counter_before_valid;
	int counter_before_errno;
	u8 counter_after_stop;
	bool counter_after_stop_valid;
	int counter_after_stop_errno;
	unsigned int samples, changes, writes, transactions;
	u16 before[IRIS_READBACK_COUNT], after[IRIS_READBACK_COUNT];
	unsigned int before_valid, after_valid;
	u16 sensor_info_before[IRIS_SENSOR_INFO_COUNT];
	u16 sensor_info_after[IRIS_SENSOR_INFO_COUNT];
	u32 sensor_info_before_valid, sensor_info_after_valid;
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
	{
		u16 *info_values = after_start ? s->sensor_info_after :
			s->sensor_info_before;
		u32 *info_valid = after_start ? &s->sensor_info_after_valid :
			&s->sensor_info_before_valid;
		for (i = 0; i < IRIS_SENSOR_INFO_COUNT; i++) {
			u8 data[2] = { 0, 0 };
			const struct iris_stream_register *reg =
				&iris_sensor_info_registers[i];
			rc = io->read_bytes(io->context, reg->address, data,
				reg->width);
			if (rc) {
				s->readback_error = rc;
				return rc;
			}
			info_values[i] = reg->width == 2 ?
				(data[0] << 8) | data[1] : data[0];
			*info_valid |= 1U << i;
		}
	}
	return 0;
}

static int iris_stream_program(struct iris_stream *s, const struct iris_stream_io *io)
{
	unsigned int i;
	u8 reset_model[2] = { 0, 0 };
	int rc;
	if (!s->loaded)
		return -ENODATA;
	s->samples = s->changes = s->writes = s->transactions = 0;
	s->before_valid = s->after_valid = 0;
	s->sensor_info_before_valid = s->sensor_info_after_valid = 0;
	s->readback_error = 0;
	s->virtual_channel_before = 0xff;
	s->virtual_channel_before_valid = false;
	s->extclk_immediate = 0;
	s->extclk_immediate_errno = 0;
	s->extclk_immediate_valid = false;
	s->extclk_single = s->control_single = s->control_pair = 0;
	s->extclk_single_errno = s->control_single_errno = s->control_pair_errno = -ENODATA;
	s->override_readback_valid = false;
	memset(s->before, 0xff, sizeof(s->before));
	memset(s->after, 0xff, sizeof(s->after));
	s->first = s->last = 0xff;
	s->counter_before = 0xff;
	s->counter_before_valid = false;
	s->counter_before_errno = 0;
	s->stop_error = 0;
	/* Even a failed write can have reached the sensor: always attempt stop. */
	s->entered = true;
	s->stage = "software-reset";
	rc = iris_stream_byte(io, 0x0103, 1);
	if (rc)
		return rc;
	/* Match the Windows Siiri startup delay after software reset. */
	io->delay_ms(10);
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
#ifdef CONFIG_CITYMAN_IRIS_CSI
	/* Optional comparison only: the original sensor_config path explicitly
	 * selects CSI-2. Its order relative to the mode's 0111=0 is unresolved. */
	if (s->select_csi2) {
		u8 virtual_channel = 0xff;
		s->stage = "csi2-interface";
		rc = iris_stream_byte(io, 0x0111, 2);
		if (rc)
			return rc;
		/* Windows sensor_config supplies the VC to match its CSID route.
		 * This bring-up configures CID/VC 0, so set the sensor to VC 0 too. */
		rc = io->read_bytes(io->context, 0x0110, &virtual_channel, 1);
		if (rc)
			return rc;
		s->virtual_channel_before = virtual_channel;
		s->virtual_channel_before_valid = true;
		rc = iris_stream_byte(io, 0x0110, IRIS_STREAM_CSI_VIRTUAL_CHANNEL);
		if (rc)
			return rc;
	}
#endif
	if (s->override_requested) {
		s->stage = "runtime-override";
		rc = iris_stream_byte(io, s->override_address, s->override_value);
		if (rc)
			return rc;
		rc = io->read_bytes(io->context, s->override_address,
			&s->override_readback, 1);
		if (rc)
			return rc;
		s->override_readback_valid = true;
	}
	s->stage = "config-readback";
	rc = iris_stream_snapshot(s, io, false);
	if (rc)
		return rc;
#ifdef CONFIG_CITYMAN_IRIS_CSI
	if (s->select_csi2 &&
	    (s->before[7] != 2 ||
	     s->before[IRIS_READBACK_COUNT - 1] != IRIS_STREAM_CSI_VIRTUAL_CHANNEL)) {
		s->stage = "csi2-interface";
		return -EIO;
	}
#endif
	return 0;
}

static int iris_stream_start(struct iris_stream *s, const struct iris_stream_io *io)
{
	unsigned int i;
	u8 value, previous = 0xff;
	int rc, snapshot_rc;
	/* Capture the standby/frame-counter state just before the start write. */
	s->stage = "pre-stream-counter";
	rc = io->read_bytes(io->context, 0x0005, &s->counter_before, 1);
	s->counter_before_errno = rc;
	if (rc)
		return rc;
	s->counter_before_valid = true;
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

static int iris_stream_run(struct iris_stream *s, const struct iris_stream_io *io)
{
	int rc = iris_stream_program(s, io);
	return rc ? rc : iris_stream_start(s, io);
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
	/* Ancillary evidence only: the original driver's idle sentinel is 0xff,
	 * and this counter has already read 0 in standby on this hardware. */
	s->counter_after_stop_errno = io->read_bytes(io->context, 0x0005,
		&s->counter_after_stop, 1);
	s->counter_after_stop_valid = !s->counter_after_stop_errno;
	if (!s->stop_error)
		s->entered = false;
	return s->stop_error;
}
#endif
