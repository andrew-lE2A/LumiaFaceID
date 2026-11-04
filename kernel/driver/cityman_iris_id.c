/*
 * Lumia 950 XL opt-in sensor identification and gated stream diagnostic.
 * No illuminator or image capture control. CSI listening is separately gated.
 * SPDX-License-Identifier: GPL-2.0-only
 */
#ifndef CITYMAN_IRIS_HOST_TEST
#include <linux/capability.h>
#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/gpio.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of_gpio.h>
#include <linux/pinctrl/consumer.h>
#include <linux/platform_device.h>
#include <linux/regulator/consumer.h>
#include <linux/slab.h>
#include "cci/msm_cci.h"
#ifdef CONFIG_CITYMAN_IRIS_STREAM
#include <crypto/hash.h>
#endif
#endif

#ifdef CONFIG_CITYMAN_IRIS_STREAM
#include "cityman_iris_stream.h"
#endif
#ifdef CONFIG_CITYMAN_IRIS_CSI
#include "cityman_iris_csi.h"
#endif

#define IRIS_MODEL 0x0861
#define IRIS_MCLK 9600000
#define IRIS_RAILS 4

static const char * const rail_names[IRIS_RAILS] = {
	"vana", "vio", "core", "vdig",
};
static const int rail_uv[IRIS_RAILS] = { 2800000, 0, 1300000, 1200000 };

struct cityman_iris {
	struct device *dev;
	struct mutex lock;
	struct regulator *rails[IRIS_RAILS];
	bool enabled[IRIS_RAILS];
	struct clk *source, *clock;
	struct pinctrl *pins;
	struct pinctrl_state *active, *sleep;
	struct msm_camera_cci_client client;
	int reset;
	bool gpio_owned, cci_on, source_on, clock_on, blocked, suspended;
	unsigned long old_rate;
	const char *status;
	const char *stage;
	int error, cleanup_error;
	int measured_uv;
	u16 model;
	unsigned int attempts;
#ifdef CONFIG_CITYMAN_IRIS_STREAM
	struct iris_stream stream;
	bool nvm_requested, nvm_transfer_active, nvm_valid, nvm_config_data, nvm_ready;
	u16 nvm_size;
	u8 nvm_pages, nvm_status;
	int nvm_error, nvm_cleanup_error;
#endif
#ifdef CONFIG_CITYMAN_IRIS_CSI
	struct iris_csi csi;
	struct iris_csi_tpg tpg;
#endif
};

#ifndef CITYMAN_IRIS_HOST_TEST
static int iris_cci_command(struct cityman_iris *iris, enum msm_cci_cmd_type cmd)
{
	struct msm_camera_cci_ctrl ctrl = { .cmd = cmd, .cci_info = &iris->client };
	int rc = v4l2_subdev_call(iris->client.cci_subdev, core, ioctl,
		VIDIOC_MSM_CCI_CFG, &ctrl);
	return rc < 0 ? rc : ctrl.status;
}

static int iris_read_model(struct cityman_iris *iris, u16 *model)
{
	u8 data[2] = { 0, 0 };
	struct msm_camera_cci_ctrl ctrl = {
		.cmd = MSM_CCI_I2C_READ, .cci_info = &iris->client,
	};
	int rc;
	ctrl.cfg.cci_i2c_read_cfg.addr = 0;
	ctrl.cfg.cci_i2c_read_cfg.addr_type = MSM_CAMERA_I2C_WORD_ADDR;
	ctrl.cfg.cci_i2c_read_cfg.data = data;
	ctrl.cfg.cci_i2c_read_cfg.num_byte = sizeof(data);
	rc = v4l2_subdev_call(iris->client.cci_subdev, core, ioctl,
		VIDIOC_MSM_CCI_CFG, &ctrl);
	if (rc < 0)
		return rc;
	if (ctrl.status < 0)
		return ctrl.status;
	*model = (data[0] << 8) | data[1];
	return 0;
}

#ifdef CONFIG_CITYMAN_IRIS_STREAM
static int iris_nvm_write_u8(struct cityman_iris *iris, u16 address, u8 value)
{
	struct msm_camera_i2c_reg_array reg = {
		.reg_addr = address, .reg_data = value,
	};
	struct msm_camera_cci_ctrl ctrl = {
		.cmd = MSM_CCI_I2C_WRITE, .cci_info = &iris->client,
	};
	int rc;
	ctrl.cfg.cci_i2c_write_cfg.reg_setting = &reg;
	ctrl.cfg.cci_i2c_write_cfg.size = 1;
	ctrl.cfg.cci_i2c_write_cfg.addr_type = MSM_CAMERA_I2C_WORD_ADDR;
	ctrl.cfg.cci_i2c_write_cfg.data_type = MSM_CAMERA_I2C_BYTE_DATA;
	rc = v4l2_subdev_call(iris->client.cci_subdev, core, ioctl,
		VIDIOC_MSM_CCI_CFG, &ctrl);
	return rc < 0 ? rc : ctrl.status;
}

static int iris_nvm_read_bytes(struct cityman_iris *iris, u16 address,
	u8 *data, unsigned int length)
{
	struct msm_camera_cci_ctrl ctrl = {
		.cmd = MSM_CCI_I2C_READ, .cci_info = &iris->client,
	};
	int rc;
	if (!length || length > 16)
		return -EINVAL;
	ctrl.cfg.cci_i2c_read_cfg.addr = address;
	ctrl.cfg.cci_i2c_read_cfg.addr_type = MSM_CAMERA_I2C_WORD_ADDR;
	ctrl.cfg.cci_i2c_read_cfg.data = data;
	ctrl.cfg.cci_i2c_read_cfg.num_byte = length;
	rc = v4l2_subdev_call(iris->client.cci_subdev, core, ioctl,
		VIDIOC_MSM_CCI_CFG, &ctrl);
	return rc < 0 ? rc : ctrl.status;
}

static int iris_nvm_finish(struct cityman_iris *iris)
{
	int rc;
	if (!iris->nvm_transfer_active)
		return 0;
	rc = iris_nvm_write_u8(iris, 0x0a00, 0x04);
	if (!rc)
		iris->nvm_transfer_active = false;
	else
		iris->nvm_cleanup_error = rc;
	return rc;
}

/* Read only the five-byte SMIA++ header. The Windows cache routine uses
 * these bytes to decide whether a full NVM cache and config parser are needed.
 * Never expose or retain calibration payload through sysfs. */
static int iris_nvm_probe(struct cityman_iris *iris)
{
	u8 header[5] = { 0 }, status = 0;
	unsigned int poll;
	u16 encoded_size;
	int rc, finish_rc;
	iris->nvm_valid = false;
	iris->nvm_error = iris->nvm_cleanup_error = 0;
	iris->nvm_size = 0;
	iris->nvm_pages = 0;
	iris->nvm_config_data = false;
	iris->nvm_ready = false;
	iris->nvm_status = 0;
	rc = iris_nvm_write_u8(iris, 0x0a02, 0x00);
	if (rc)
		goto out;
	/* A failed control write can still have reached the target. */
	iris->nvm_transfer_active = true;
	rc = iris_nvm_write_u8(iris, 0x0a00, 0x01);
	if (rc)
		goto out;
	for (poll = 0; poll < 50; poll++) {
		rc = iris_nvm_read_bytes(iris, 0x0a01, &status, 1);
		if (rc)
			goto out;
		iris->nvm_status = status;
		if (status & 0x01)
			break;
		msleep(1);
	}
	/* The Windows routine bounds its wait but proceeds with metadata reads
	 * when RD_READY stays low, provided the error bits are clear. */
	iris->nvm_ready = !!(status & 0x01);
	if (status & 0x0c) {
		rc = -EIO;
		goto out;
	}
	rc = iris_nvm_read_bytes(iris, 0x0a04, header, sizeof(header));
	if (rc)
		goto out;
	/* NVM size is encoded in 8-byte units, with the field shifted by 3. */
	if (header[1] & 0x08)
		encoded_size = ((u16)header[3] << 8) | header[4];
	else
		encoded_size = ((u16)header[2] << 8) | header[3];
	iris->nvm_size = encoded_size >> 3;
	if (iris->nvm_size > 8191) {
		rc = -EOVERFLOW;
		goto out;
	}
	iris->nvm_pages = DIV_ROUND_UP(iris->nvm_size, 64);
	iris->nvm_config_data = !!((header[1] & 0x08) && (header[2] & 0x10));
	iris->nvm_valid = true;
out:
	finish_rc = iris_nvm_finish(iris);
	if (!rc && finish_rc)
		rc = finish_rc;
	iris->nvm_error = rc;
	return rc;
}

static int iris_stream_read_bytes(void *context, u16 address, u8 *data,
	unsigned int length);

static int iris_stream_write_bytes(void *context, u16 address, const u8 *data,
	unsigned int length)
{
	struct cityman_iris *iris = context;
	struct msm_camera_i2c_reg_array regs[IRIS_STREAM_MAX_BURST] = { { 0 } };
	struct msm_camera_cci_ctrl ctrl = {
		.cmd = MSM_CCI_I2C_WRITE, .cci_info = &iris->client,
	};
	unsigned int i;
	int rc;
	if (!length || length > IRIS_STREAM_MAX_BURST)
		return -EINVAL;
	for (i = 0; i < length; i++) {
		regs[i].reg_addr = address + i;
		regs[i].reg_data = data[i];
	}
	if (length > 1)
		ctrl.cmd = MSM_CCI_I2C_WRITE_SEQ;
	ctrl.cfg.cci_i2c_write_cfg.reg_setting = regs;
	ctrl.cfg.cci_i2c_write_cfg.size = length;
	ctrl.cfg.cci_i2c_write_cfg.addr_type = MSM_CAMERA_I2C_WORD_ADDR;
	ctrl.cfg.cci_i2c_write_cfg.data_type = MSM_CAMERA_I2C_BYTE_DATA;
	rc = v4l2_subdev_call(iris->client.cci_subdev, core, ioctl,
		VIDIOC_MSM_CCI_CFG, &ctrl);
	rc = rc < 0 ? rc : ctrl.status;
	if (!rc && address == 0x0136 && length == 2) {
		u8 observed[2] = { 0, 0 };
		int read_rc = iris_stream_read_bytes(context, address, observed, 2);
		iris->stream.extclk_immediate_errno = read_rc;
		if (!read_rc) {
			iris->stream.extclk_immediate = (observed[0] << 8) | observed[1];
			iris->stream.extclk_immediate_valid = true;
		}
		read_rc = iris_stream_read_bytes(context, 0x0136, observed, 1);
		if (!read_rc)
			read_rc = iris_stream_read_bytes(context, 0x0137, observed + 1, 1);
		iris->stream.extclk_single_errno = read_rc;
		if (!read_rc)
			iris->stream.extclk_single = (observed[0] << 8) | observed[1];
		/* 0130 is compared after the profile has programmed it. */
	}
	return rc;
}

static int iris_stream_read_bytes(void *context, u16 address, u8 *data,
	unsigned int length)
{
	struct cityman_iris *iris = context;
	struct msm_camera_cci_ctrl ctrl = {
		.cmd = MSM_CCI_I2C_READ, .cci_info = &iris->client,
	};
	int rc;
	if (!length || length > 2)
		return -EINVAL;
	ctrl.cfg.cci_i2c_read_cfg.addr = address;
	ctrl.cfg.cci_i2c_read_cfg.addr_type = MSM_CAMERA_I2C_WORD_ADDR;
	ctrl.cfg.cci_i2c_read_cfg.data = data;
	ctrl.cfg.cci_i2c_read_cfg.num_byte = length;
	rc = v4l2_subdev_call(iris->client.cci_subdev, core, ioctl,
		VIDIOC_MSM_CCI_CFG, &ctrl);
	rc = rc < 0 ? rc : ctrl.status;
	if (address == 0x0130 && length == 2) {
		u8 observed[2] = { 0, 0 };
		int read_rc;
		iris->stream.control_pair_errno = rc;
		if (!rc)
			iris->stream.control_pair = (data[0] << 8) | data[1];
		read_rc = iris_stream_read_bytes(context, address, observed, 1);
		if (!read_rc)
			read_rc = iris_stream_read_bytes(context, address + 1, observed + 1, 1);
		iris->stream.control_single_errno = read_rc;
		if (!read_rc)
			iris->stream.control_single = (observed[0] << 8) | observed[1];
	}
	return rc;
}

static void iris_stream_delay(unsigned int value) { msleep(value); }

static struct iris_stream_io iris_stream_io(struct cityman_iris *iris)
{
	struct iris_stream_io io = { .context = iris, .write_bytes = iris_stream_write_bytes,
		.read_bytes = iris_stream_read_bytes, .delay_ms = iris_stream_delay };
	return io;
}
#endif
#endif

static void iris_cleanup(struct cityman_iris *iris)
{
	int i, rc;
#ifdef CONFIG_CITYMAN_IRIS_STREAM
	if (iris->nvm_transfer_active && iris->cci_on) {
		rc = iris_nvm_finish(iris);
		if (rc)
			iris->cleanup_error = rc;
	}
	if (iris->stream.entered && iris->cci_on) {
		struct iris_stream_io io = iris_stream_io(iris);
		rc = iris_stream_stop(&iris->stream, &io);
		if (rc)
			iris->cleanup_error = rc;
	}
#endif
#ifdef CONFIG_CITYMAN_IRIS_CSI
	if (iris->csi.requested) {
		rc = cityman_iris_csi_end(&iris->csi);
		if (rc || iris->csi.cleanup_error)
			iris->cleanup_error = rc ? rc : iris->csi.cleanup_error;
	}
#endif
	if (iris->gpio_owned) {
		gpio_set_value_cansleep(iris->reset, 0);
		usleep_range(1000, 1500);
	}
	if (iris->cci_on) {
		rc = iris_cci_command(iris, MSM_CCI_RELEASE);
		if (rc < 0)
			iris->cleanup_error = rc;
		else
			iris->cci_on = false;
	}
	if (iris->clock_on) {
		clk_disable_unprepare(iris->clock);
		iris->clock_on = false;
	}
	if (iris->source_on) {
		clk_disable_unprepare(iris->source);
		iris->source_on = false;
	}
	if (iris->gpio_owned) {
		rc = pinctrl_select_state(iris->pins, iris->sleep);
		if (rc < 0)
			iris->cleanup_error = rc;
	}
	for (i = IRIS_RAILS - 1; i >= 0; i--) {
		if (!iris->enabled[i])
			continue;
		rc = regulator_disable(iris->rails[i]);
		if (rc < 0)
			iris->cleanup_error = rc;
		else
			iris->enabled[i] = false;
	}
	if (iris->old_rate) {
		rc = clk_set_rate(iris->source, iris->old_rate);
		if (rc < 0)
			iris->cleanup_error = rc;
		iris->old_rate = 0;
	}
	if (iris->gpio_owned) {
		gpio_free(iris->reset);
		iris->gpio_owned = false;
	}
	if (iris->cleanup_error)
		iris->blocked = true;
}

/* Called only by an explicit root write, never by platform probe or boot. */
static int iris_identify(struct cityman_iris *iris)
{
	struct cci_device *cci = v4l2_get_subdevdata(iris->client.cci_subdev);
	int i, rc;
	if (iris->blocked)
		return -EBUSY;
	if (iris->suspended) {
		iris->status = "suspended";
		iris->error = -EBUSY;
		return -EBUSY;
	}
	/* Camera services must be stopped: the legacy CCI lifecycle is not a
	 * session-ownership API. Refuse an already-open controller as well. */
	if (!cci || cci->ref_count) {
		iris->status = "busy";
		iris->stage = "cci-in-use";
		iris->error = -EBUSY;
		return -EBUSY;
	}
	iris->attempts++;
	iris->model = 0;
	iris->error = iris->cleanup_error = 0;
	iris->measured_uv = 0;
	iris->status = "running";
	iris->stage = "reset-request";
	rc = gpio_request(iris->reset, "cityman-iris-reset");
	if (rc)
		goto done;
	iris->gpio_owned = true;
	rc = gpio_direction_output(iris->reset, 0);
	if (rc)
		goto done;
	iris->stage = "pinctrl";
	rc = pinctrl_select_state(iris->pins, iris->active);
	if (rc)
		goto done;
	for (i = 0; i < IRIS_RAILS; i++) {
		iris->stage = rail_names[i];
		rc = regulator_enable(iris->rails[i]);
		if (rc)
			goto done;
		iris->enabled[i] = true;
		/* Fixed board constraints select these voltages. No voltage votes
		 * are changed here; vio is the existing shared LVS1 switch. */
		if (rail_uv[i]) {
			iris->measured_uv = regulator_get_voltage(iris->rails[i]);
			if (iris->measured_uv != rail_uv[i]) {
				rc = iris->measured_uv < 0 ? iris->measured_uv : -ERANGE;
				goto done;
			}
		}
		usleep_range(1000, 1500);
	}
	iris->stage = "mclk";
	iris->old_rate = clk_get_rate(iris->source);
	rc = clk_set_rate(iris->source, IRIS_MCLK);
	if (rc)
		goto done;
	rc = clk_prepare_enable(iris->source);
	if (rc)
		goto done;
	iris->source_on = true;
	rc = clk_prepare_enable(iris->clock);
	if (rc)
		goto done;
	iris->clock_on = true;
	usleep_range(1000, 1500);
	iris->stage = "cci-init";
	rc = iris_cci_command(iris, MSM_CCI_INIT);
	if (rc)
		goto done;
	iris->cci_on = true;
	iris->stage = "reset-release";
	gpio_set_value_cansleep(iris->reset, 1);
	usleep_range(3000, 4000);
	iris->stage = "model-read";
	rc = iris_read_model(iris, &iris->model);
	if (rc) {
		usleep_range(1000, 1500);
		rc = iris_read_model(iris, &iris->model);
	}
	if (!rc && iris->model != IRIS_MODEL)
		rc = -ENODEV;
#ifdef CONFIG_CITYMAN_IRIS_STREAM
	if (!rc && iris->nvm_requested) {
		iris->stage = "nvm-test";
		rc = iris_nvm_probe(iris);
	}
	if (!rc && iris->stream.requested) {
		struct iris_stream_io io = iris_stream_io(iris);
		iris->stage = "stream-test";
#ifdef CONFIG_CITYMAN_IRIS_CSI
		if (iris->csi.requested) {
			rc = iris_stream_program(&iris->stream, &io);
			if (!rc)
				rc = cityman_iris_csi_begin(&iris->csi);
			if (!rc) {
				rc = iris_stream_start(&iris->stream, &io);
				cityman_iris_csi_sample(&iris->csi);
			}
		} else
#endif
		rc = iris_stream_run(&iris->stream, &io);
	}
#endif
done:
	iris->error = rc;
	iris_cleanup(iris);
	iris->status = iris->cleanup_error ? "cleanup-error" :
		(rc ? "failed" : "identified");
#ifdef CONFIG_CITYMAN_IRIS_STREAM
	if (!rc && !iris->cleanup_error && iris->stream.requested)
		iris->status = "sensor-streamed";
#endif
	dev_info(iris->dev, "%s stage=%s rc=%d model=0x%04x cleanup=%d\n",
		iris->status, iris->stage, rc, iris->model, iris->cleanup_error);
	return iris->cleanup_error ? iris->cleanup_error : rc;
}

#ifndef CITYMAN_IRIS_HOST_TEST
static DEFINE_MUTEX(iris_probe_lock);
static char iris_probe_text[96] = "not-probed";

static int iris_probe_status_get(char *buf, const struct kernel_param *kp)
{
	int size;
	mutex_lock(&iris_probe_lock);
	size = scnprintf(buf, PAGE_SIZE, "%s\n", iris_probe_text);
	mutex_unlock(&iris_probe_lock);
	return size;
}

static int iris_probe_status_set(const char *value, const struct kernel_param *kp)
{
	/* Also reject boot-command-line assignment: this is diagnostic output. */
	return -EPERM;
}

static const struct kernel_param_ops iris_probe_status_ops = {
	.get = iris_probe_status_get, .set = iris_probe_status_set,
};
module_param_cb(probe_status, &iris_probe_status_ops, NULL, 0444);
MODULE_PARM_DESC(probe_status, "Read-only last platform probe stage and error");

static int iris_probe_report(struct device *dev, const char *stage, int rc)
{
	mutex_lock(&iris_probe_lock);
	scnprintf(iris_probe_text, sizeof(iris_probe_text), "stage=%s errno=%d", stage, rc);
	mutex_unlock(&iris_probe_lock);
	if (rc)
		dev_warn_ratelimited(dev, "probe stage=%s rc=%d\n", stage, rc);
	return rc;
}

static ssize_t result_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct cityman_iris *iris = dev_get_drvdata(dev);
	ssize_t size;
	mutex_lock(&iris->lock);
	size = scnprintf(buf, PAGE_SIZE,
		"status=%s stage=%s errno=%d model=0x%04x cleanup_errno=%d attempts=%u blocked=%u rail_uv=%d\n",
		iris->status, iris->stage, iris->error, iris->model,
		iris->cleanup_error, iris->attempts, iris->blocked, iris->measured_uv);
	mutex_unlock(&iris->lock);
	return size;
}

static ssize_t identify_store(struct device *dev, struct device_attribute *attr,
	const char *buf, size_t count)
{
	struct cityman_iris *iris = dev_get_drvdata(dev);
	int rc;
	if (!capable(CAP_SYS_RAWIO))
		return -EPERM;
	if (!sysfs_streq(buf, "identify"))
		return -EINVAL;
	if (!mutex_trylock(&iris->lock))
		return -EBUSY;
#ifdef CONFIG_CITYMAN_IRIS_STREAM
	iris->stream.requested = false;
#endif
#ifdef CONFIG_CITYMAN_IRIS_CSI
	iris->csi.requested = false;
#endif
	rc = iris_identify(iris);
	mutex_unlock(&iris->lock);
	return rc < 0 ? rc : count;
}

static DEVICE_ATTR(result, 0444, result_show, NULL);
static DEVICE_ATTR(identify, 0200, NULL, identify_store);
#ifdef CONFIG_CITYMAN_IRIS_STREAM
static ssize_t stream_result_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct cityman_iris *iris = dev_get_drvdata(dev);
	struct iris_stream *s = &iris->stream;
	ssize_t size;
	mutex_lock(&iris->lock);
	size = scnprintf(buf, PAGE_SIZE,
		"profile_loaded=%u stage=%s first=0x%02x last=0x%02x changes=%u samples=%u program_writes=%u stop_errno=%d program_transactions=%u readback_errno=%d interface_csi2_requested=%u vc_before=0x%02x vc_before_valid=%u extclk_immediate=0x%04x extclk_immediate_valid=%u extclk_immediate_errno=%d extclk_single=0x%04x extclk_single_errno=%d control_pair=0x%04x control_pair_errno=%d control_single=0x%04x control_single_errno=%d override_requested=%u override_address=0x%04x override_value=0x%02x override_readback=0x%02x override_readback_valid=%u\n",
		s->loaded, s->stage, s->first, s->last, s->changes,
		s->samples, s->writes, s->stop_error, s->transactions,
		s->readback_error, s->select_csi2, s->virtual_channel_before,
		s->virtual_channel_before_valid, s->extclk_immediate,
		s->extclk_immediate_valid, s->extclk_immediate_errno,
		s->extclk_single, s->extclk_single_errno, s->control_pair,
		s->control_pair_errno, s->control_single, s->control_single_errno,
		s->override_requested, s->override_address, s->override_value,
		s->override_readback, s->override_readback_valid);
	mutex_unlock(&iris->lock);
	return size;
}

static ssize_t stream_readback_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct cityman_iris *iris = dev_get_drvdata(dev);
	struct iris_stream *s = &iris->stream;
	ssize_t size = 0;
	unsigned int i;
	mutex_lock(&iris->lock);
	for (i = 0; i < IRIS_READBACK_COUNT; i++) {
		const struct iris_stream_register *reg = &iris_stream_registers[i];
		size += scnprintf(buf + size, PAGE_SIZE - size,
			"%s addr=0x%04x width=%u before=0x%04x before_valid=%u after=0x%04x after_valid=%u\n",
			reg->name, reg->address, reg->width, s->before[i],
			!!(s->before_valid & (1U << i)), s->after[i],
			!!(s->after_valid & (1U << i)));
	}
	mutex_unlock(&iris->lock);
	return size;
}

static ssize_t stream_profile_store(struct device *dev, struct device_attribute *attr,
	const char *buf, size_t count)
{
	struct cityman_iris *iris = dev_get_drvdata(dev);
	struct crypto_shash *tfm;
	struct shash_desc *desc;
	u8 program[IRIS_PROGRAM_BYTES], digest[32];
	size_t length = count;
	int rc = -EINVAL;
	if (!capable(CAP_SYS_RAWIO))
		return -EPERM;
	if (!mutex_trylock(&iris->lock))
		return -EBUSY;
	if (iris->attempts || iris->blocked || iris->suspended) {
		rc = -EBUSY;
		goto out;
	}
	iris->stream.loaded = false;
	if (length && buf[length - 1] == '\n')
		length--;
	if (length != IRIS_PROGRAM_BYTES * 2 || hex2bin(program, buf, IRIS_PROGRAM_BYTES))
		goto out;
	tfm = crypto_alloc_shash("sha256", 0, 0);
	if (IS_ERR(tfm)) {
		rc = PTR_ERR(tfm);
		goto out;
	}
	desc = kmalloc(sizeof(*desc) + crypto_shash_descsize(tfm), GFP_KERNEL);
	if (!desc) {
		rc = -ENOMEM;
		goto free_hash;
	}
	desc->tfm = tfm;
	desc->flags = 0;
	rc = crypto_shash_digest(desc, program, sizeof(program), digest);
	if (!rc)
		rc = iris_stream_accept(&iris->stream, program, sizeof(program), digest);
	kfree(desc);
free_hash:
	crypto_free_shash(tfm);
out:
	mutex_unlock(&iris->lock);
	return rc ? rc : count;
}

static ssize_t stream_once_store(struct device *dev, struct device_attribute *attr,
	const char *buf, size_t count)
{
	struct cityman_iris *iris = dev_get_drvdata(dev);
	int rc;
	if (!capable(CAP_SYS_RAWIO))
		return -EPERM;
	if (!sysfs_streq(buf, "stream-once")
#ifdef CONFIG_CITYMAN_IRIS_CSI
	    && !sysfs_streq(buf, "csi-once")
	    && !sysfs_streq(buf, "csi2-once")
#endif
	)
		return -EINVAL;
	if (!mutex_trylock(&iris->lock))
		return -EBUSY;
	if (!iris->stream.loaded) {
		rc = -ENODATA;
		goto out;
	}
	if (iris->attempts || strcmp(iris->status, "ready")) {
		rc = -EBUSY;
		goto out;
	}
	iris->stream.requested = true;
	iris->stream.override_requested = false;
#ifdef CONFIG_CITYMAN_IRIS_CSI
	memset(&iris->csi, 0, sizeof(iris->csi));
	iris->csi.settle = IRIS_CSI_SETTLE;
	iris->stream.select_csi2 = sysfs_streq(buf, "csi2-once");
	iris->csi.requested = sysfs_streq(buf, "csi-once") || iris->stream.select_csi2;
#endif
	rc = iris_identify(iris);
out:
	mutex_unlock(&iris->lock);
	return rc < 0 ? rc : count;
}

static DEVICE_ATTR(stream_result, 0444, stream_result_show, NULL);
static DEVICE_ATTR(stream_readback, 0444, stream_readback_show, NULL);
static DEVICE_ATTR(stream_profile, 0200, NULL, stream_profile_store);
static DEVICE_ATTR(stream_once, 0200, NULL, stream_once_store);

static ssize_t nvm_result_show(struct device *dev,
	struct device_attribute *attr, char *buf)
{
	struct cityman_iris *iris = dev_get_drvdata(dev);
	ssize_t size;
	mutex_lock(&iris->lock);
	size = scnprintf(buf, PAGE_SIZE,
		"requested=%u valid=%u errno=%d cleanup_errno=%d ready=%u status=0x%02x size_bytes=%u pages=%u config_flags=%u sensor_config_entries_present=%u raw_payload_exported=0\n",
		iris->nvm_requested, iris->nvm_valid, iris->nvm_error,
		iris->nvm_cleanup_error, iris->nvm_ready, iris->nvm_status,
		iris->nvm_size, iris->nvm_pages,
		iris->nvm_config_data, iris->nvm_config_data);
	mutex_unlock(&iris->lock);
	return size;
}

static ssize_t nvm_once_store(struct device *dev,
	struct device_attribute *attr, const char *buf, size_t count)
{
	struct cityman_iris *iris = dev_get_drvdata(dev);
	int rc;
	if (!capable(CAP_SYS_RAWIO))
		return -EPERM;
	if (!sysfs_streq(buf, "nvm-once"))
		return -EINVAL;
	if (!mutex_trylock(&iris->lock))
		return -EBUSY;
	if (iris->attempts || iris->blocked || iris->suspended ||
	    strcmp(iris->status, "ready")) {
		rc = -EBUSY;
		goto out;
	}
	iris->nvm_requested = true;
	rc = iris_identify(iris);
out:
	mutex_unlock(&iris->lock);
	return rc < 0 ? rc : count;
}

static DEVICE_ATTR(nvm_result, 0444, nvm_result_show, NULL);
static DEVICE_ATTR(nvm_once, 0200, NULL, nvm_once_store);
#endif
#ifdef CONFIG_CITYMAN_IRIS_CSI
static ssize_t csi_top_result_show(struct device *dev,
	struct device_attribute *attr, char *buf)
{
	struct cityman_iris *iris = dev_get_drvdata(dev);
	struct iris_csi *s = &iris->csi;
	u32 mux40, mux44;
	int rc;
	ssize_t size;
	mutex_lock(&iris->lock);
	rc = cityman_iris_phy_mux_read_live(&mux40, &mux44);
	if (!rc) {
		size = scnprintf(buf, PAGE_SIZE,
			"source=live camss_top_40=0x%08x camss_top_44=0x%08x\n",
			mux40, mux44);
	} else if (s->top_after_valid) {
		size = scnprintf(buf, PAGE_SIZE,
			"source=iris-snapshot camss_top_40_before=0x%08x camss_top_40_after=0x%08x camss_top_44_before=0x%08x camss_top_44_after=0x%08x\n",
			s->top40_before, s->top40_after,
			s->top44_before, s->top44_after);
	} else {
		size = scnprintf(buf, PAGE_SIZE,
			"source=unavailable errno=%d; read only while PHY2 is powered\n", rc);
	}
	mutex_unlock(&iris->lock);
	return size;
}
static DEVICE_ATTR(csi_top_result, 0444, csi_top_result_show, NULL);

static ssize_t csi_phy_result_show(struct device *dev,
	struct device_attribute *attr, char *buf)
{
	u32 status[IRIS_CSI_PHY_IRQ_WORDS];
	int rc = cityman_iris_phy_irq_read_live(status,
		ARRAY_SIZE(status));
	if (rc)
		return scnprintf(buf, PAGE_SIZE,
			"source=unavailable errno=%d; read only while PHY2 is powered\n",
			rc);
	return scnprintf(buf, PAGE_SIZE,
		"source=live phy=2 irq0=0x%08x irq1=0x%08x irq2=0x%08x irq3=0x%08x irq4=0x%08x irq5=0x%08x irq6=0x%08x irq7=0x%08x\n",
		status[0], status[1], status[2], status[3],
		status[4], status[5], status[6], status[7]);
}
static DEVICE_ATTR(csi_phy_result, 0444, csi_phy_result_show, NULL);

static ssize_t csi_result_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct cityman_iris *iris = dev_get_drvdata(dev);
	struct iris_csi *s = &iris->csi;
	ssize_t size;
	mutex_lock(&iris->lock);
	size = scnprintf(buf, PAGE_SIZE,
		"requested=%u stage=%s errno=%d cleanup_errno=%d phy=2 csid=3 combo=1 lane_mask=0x18 lane_assign=0x0004 settle=%u before_valid=%u after_valid=%u packets_before=%u packets_after=%u ecc_before=%u ecc_after=%u crc_before=%u crc_after=%u version=0x%08x\n",
		s->requested, s->stage ? s->stage : "idle", s->error, s->cleanup_error,
		s->settle ? s->settle : IRIS_CSI_SETTLE,
		s->before_valid, s->after_valid,
		s->before.packets, s->after.packets,
		s->before.ecc, s->after.ecc, s->before.crc, s->after.crc, s->version);
	mutex_unlock(&iris->lock);
	return size;
}
static DEVICE_ATTR(csi_result, 0444, csi_result_show, NULL);
static ssize_t csi_tpg_result_show(struct device *dev,
	struct device_attribute *attr, char *buf)
{
	struct cityman_iris *iris = dev_get_drvdata(dev);
	struct iris_csi_tpg *t = &iris->tpg;
	ssize_t size;
	mutex_lock(&iris->lock);
	size = scnprintf(buf, PAGE_SIZE,
		"requested=%u stage=%s errno=%d cleanup_errno=%d version=0x%08x before_valid=%u after_valid=%u packets_before=%u packets_after=%u ecc_before=%u ecc_after=%u crc_before=%u crc_after=%u irq_before=0x%08x irq_after=0x%08x ctrl_before=0x%08x ctrl_after=0x%08x vc_before=0x%08x vc_after=0x%08x dt0_before=0x%08x dt0_after=0x%08x dt1_before=0x%08x dt1_after=0x%08x dt2_before=0x%08x dt2_after=0x%08x\n",
		t->requested, t->stage ? t->stage : "idle", t->error,
		t->cleanup_error, t->version, t->before_valid, t->after_valid,
		t->before.packets, t->after.packets, t->before.ecc, t->after.ecc,
		t->before.crc, t->after.crc, t->irq_before, t->irq_after,
		t->regs_before[0], t->regs_after[0], t->regs_before[1],
		t->regs_after[1], t->regs_before[2], t->regs_after[2],
		t->regs_before[3], t->regs_after[3], t->regs_before[4],
		t->regs_after[4]);
	mutex_unlock(&iris->lock);
	return size;
}

static ssize_t csi_tpg_once_store(struct device *dev,
	struct device_attribute *attr, const char *buf, size_t count)
{
	struct cityman_iris *iris = dev_get_drvdata(dev);
	int rc;
	if (!capable(CAP_SYS_RAWIO))
		return -EPERM;
	if (!sysfs_streq(buf, "run"))
		return -EINVAL;
	if (!mutex_trylock(&iris->lock))
		return -EBUSY;
	if (iris->tpg.requested || iris->attempts || iris->blocked ||
	    iris->suspended || strcmp(iris->status, "ready")) {
		rc = -EBUSY;
		goto out;
	}
	iris->tpg.requested = true;
	rc = cityman_iris_csid_tpg_run(&iris->tpg);
	if (iris->tpg.cleanup_error) {
		iris->blocked = true;
		iris->status = "failed";
		iris->stage = "tpg-cleanup";
		iris->error = rc ? rc : iris->tpg.cleanup_error;
	}
out:
	mutex_unlock(&iris->lock);
	return rc < 0 ? rc : count;
}

static DEVICE_ATTR(csi_tpg_result, 0444, csi_tpg_result_show, NULL);
static DEVICE_ATTR(csi_tpg_once, 0200, NULL, csi_tpg_once_store);
static ssize_t csi_readback_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	static const char * const csid_names[IRIS_CSI_CSID_REGS] = {
		"control0", "control1", "vc0_lut", "cid0_config", "irq_status",
	};
	static const char * const phy_names[IRIS_CSI_PHY_REGS] = {
		"clock_mux", "power", "mode", "clock_cfg2", "clock_settle", "clock_misc",
		"data_cfg2", "data_settle", "data_misc", "irq_status0", "irq_status1",
		"irq_status2", "irq_status3", "irq_status4", "irq_status5", "irq_status6", "irq_status7",
	};
	struct cityman_iris *iris = dev_get_drvdata(dev);
	struct iris_csi *s = &iris->csi;
	ssize_t size = 0;
	unsigned int i;
	mutex_lock(&iris->lock);
	for (i = 0; i < IRIS_CSI_CSID_REGS; i++)
		size += scnprintf(buf + size, PAGE_SIZE - size,
			"csid_%s before=0x%08x before_valid=%u after=0x%08x after_valid=%u\n",
			csid_names[i], s->csid_before[i], s->before_valid, s->csid_after[i], s->after_valid);
	for (i = 0; i < IRIS_CSI_PHY_REGS; i++)
		size += scnprintf(buf + size, PAGE_SIZE - size,
			"phy_%s before=0x%08x before_valid=%u after=0x%08x after_valid=%u\n",
			phy_names[i], s->phy_before[i], s->before_valid, s->phy_after[i], s->after_valid);
	mutex_unlock(&iris->lock);
	return size;
}
static DEVICE_ATTR(csi_readback, 0444, csi_readback_show, NULL);
static DEVICE_ATTR(csi_once, 0200, NULL, stream_once_store);
static DEVICE_ATTR(csi2_once, 0200, NULL, stream_once_store);

/* Bounded PHY settle value, fixed CSI-2 and VC0; no raw register API. */
static ssize_t csi_trial_store(struct device *dev,
	struct device_attribute *attr, const char *buf, size_t count)
{
	struct cityman_iris *iris = dev_get_drvdata(dev);
	unsigned int settle, address = 0, value = 0, i;
	bool override = false, found = false;
	char extra;
	int rc;
	if (!capable(CAP_SYS_RAWIO))
		return -EPERM;
	if (strncmp(buf, "settle=", 7))
		return -EINVAL;
	if (kstrtouint(buf + 7, 10, &settle)) {
		if (sscanf(buf, "settle=%u reg=%x value=%x %c", &settle,
			   &address, &value, &extra) != 3 || address > 0xffff || value > 0xff)
			return -EINVAL;
		override = true;
	}
	if (settle < 1 || settle > 63)
		return -EINVAL;
	if (!mutex_trylock(&iris->lock))
		return -EBUSY;
	if (!iris->stream.loaded) {
		rc = -ENODATA;
		goto out;
	}
	if (override) {
		/* Limit writes to bytes already present in the authenticated profile.
		 * Do not let a trial replace mode, reset, group hold or NVM controls. */
		if ((address >= 0x0100 && address <= 0x0107) ||
		    (address >= 0x0a00 && address <= 0x0aff)) {
			rc = -EPERM;
			goto out;
		}
		for (i = 0; i < IRIS_PROGRAM_BYTES; i += 3)
			if (((iris->stream.program[i] << 8) | iris->stream.program[i + 1]) == address)
				found = true;
		if (!found) {
			rc = -EPERM;
			goto out;
		}
	}
	if (iris->blocked || iris->suspended ||
	    iris->attempts >= IRIS_CSI_TRIAL_LIMIT ||
	    !((!iris->attempts && !strcmp(iris->status, "ready")) ||
	      (iris->attempts && !iris->cleanup_error &&
	       !iris->stream.stop_error && !iris->csi.cleanup_error &&
	       iris->csi.stage && !strcmp(iris->csi.stage, "released") &&
	       !strcmp(iris->stage, "stream-test") &&
	       ((iris->error == -ETIMEDOUT && !strcmp(iris->status, "failed")) ||
		(!iris->error && !strcmp(iris->status, "sensor-streamed")))))) {
		rc = -EBUSY;
		goto out;
	}
	memset(&iris->csi, 0, sizeof(iris->csi));
	iris->csi.requested = true;
	iris->csi.settle = settle;
	iris->stream.requested = true;
	iris->stream.select_csi2 = true;
	iris->stream.override_requested = override;
	iris->stream.override_address = address;
	iris->stream.override_value = value;
	rc = iris_identify(iris);
	/* A clean counter stall is a completed observation, not a retry trigger. */
	if (rc == -ETIMEDOUT && iris->stream.samples == IRIS_STREAM_SAMPLES &&
	    !iris->stream.changes && !iris->stream.stop_error &&
	    !iris->cleanup_error && !iris->csi.cleanup_error && !iris->blocked)
		rc = 0;
out:
	mutex_unlock(&iris->lock);
	return rc ? rc : count;
}
static DEVICE_ATTR(csi_trial, 0200, NULL, csi_trial_store);
#endif
static struct attribute *iris_attrs[] = {
	&dev_attr_result.attr, &dev_attr_identify.attr,
#ifdef CONFIG_CITYMAN_IRIS_STREAM
	&dev_attr_stream_result.attr, &dev_attr_stream_profile.attr, &dev_attr_stream_once.attr,
	&dev_attr_stream_readback.attr,
	&dev_attr_nvm_result.attr, &dev_attr_nvm_once.attr,
#endif
#ifdef CONFIG_CITYMAN_IRIS_CSI
	&dev_attr_csi_top_result.attr, &dev_attr_csi_phy_result.attr,
	&dev_attr_csi_result.attr,
	&dev_attr_csi_readback.attr, &dev_attr_csi_once.attr,
	&dev_attr_csi2_once.attr, &dev_attr_csi_tpg_result.attr,
	&dev_attr_csi_tpg_once.attr,
	&dev_attr_csi_trial.attr,
#endif
	NULL,
};
static const struct attribute_group iris_group = { .attrs = iris_attrs };

static int cityman_iris_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct cityman_iris *iris;
	int i, rc;
	char stage[32];
	iris_probe_report(dev, "probing", 0);
	if (!of_machine_is_compatible("mmo,cityman"))
		return iris_probe_report(dev, "board-compatibility", -ENODEV);
	iris = devm_kzalloc(dev, sizeof(*iris), GFP_KERNEL);
	if (!iris)
		return iris_probe_report(dev, "allocation", -ENOMEM);
	iris->dev = dev;
	iris->status = "ready";
	iris->stage = "idle";
#ifdef CONFIG_CITYMAN_IRIS_STREAM
	iris->stream.stage = "idle";
	iris->stream.first = iris->stream.last = 0xff;
#endif
#ifdef CONFIG_CITYMAN_IRIS_CSI
	iris->tpg.stage = "idle";
#endif
	mutex_init(&iris->lock);
	iris->client.cci_subdev = msm_cci_get_subdev();
	if (!iris->client.cci_subdev)
		return iris_probe_report(dev, "cci-subdevice", -EPROBE_DEFER);
	iris->client.cci_i2c_master = MASTER_0;
	iris->client.sid = 0x6c >> 1;
	iris->client.i2c_freq_mode = I2C_STANDARD_MODE;
	iris->client.retries = 0;
	iris->reset = of_get_named_gpio(dev->of_node, "reset-gpios", 0);
	if (!gpio_is_valid(iris->reset))
		return iris_probe_report(dev, "reset-gpio", iris->reset < 0 ? iris->reset : -EINVAL);
	for (i = 0; i < IRIS_RAILS; i++) {
		iris->rails[i] = devm_regulator_get(dev, rail_names[i]);
		if (IS_ERR(iris->rails[i])) {
			scnprintf(stage, sizeof(stage), "regulator-%s", rail_names[i]);
			return iris_probe_report(dev, stage, PTR_ERR(iris->rails[i]));
		}
	}
	iris->source = devm_clk_get(dev, "cam_src_clk");
	if (IS_ERR(iris->source))
		return iris_probe_report(dev, "mclk-source", PTR_ERR(iris->source));
	iris->clock = devm_clk_get(dev, "cam_clk");
	if (IS_ERR(iris->clock))
		return iris_probe_report(dev, "mclk-gate", PTR_ERR(iris->clock));
	iris->pins = devm_pinctrl_get(dev);
	if (IS_ERR(iris->pins))
		return iris_probe_report(dev, "pinctrl-handle", PTR_ERR(iris->pins));
	iris->active = pinctrl_lookup_state(iris->pins, "iris_active");
	if (IS_ERR(iris->active))
		return iris_probe_report(dev, "pinctrl-active", PTR_ERR(iris->active));
	iris->sleep = pinctrl_lookup_state(iris->pins, "iris_sleep");
	if (IS_ERR(iris->sleep))
		return iris_probe_report(dev, "pinctrl-sleep", PTR_ERR(iris->sleep));
	platform_set_drvdata(pdev, iris);
	rc = sysfs_create_group(&dev->kobj, &iris_group);
	if (!rc) {
#ifdef CONFIG_CITYMAN_IRIS_STREAM
		dev_info(dev, "idle; explicit root sensor-stream test available; no IR or CSI control\n");
#else
		dev_info(dev, "idle; explicit root identification required; no IR or stream control\n");
#endif
	}
	return iris_probe_report(dev, rc ? "status-sysfs" : "ready", rc);
}

static int cityman_iris_remove(struct platform_device *pdev)
{
	struct cityman_iris *iris = platform_get_drvdata(pdev);
	sysfs_remove_group(&pdev->dev.kobj, &iris_group);
	mutex_lock(&iris->lock);
	iris->cleanup_error = 0;
	iris_cleanup(iris);
	mutex_unlock(&iris->lock);
	return 0;
}

static int cityman_iris_suspend(struct device *dev)
{
	struct cityman_iris *iris = dev_get_drvdata(dev);
	mutex_lock(&iris->lock);
	if (iris->blocked) {
		mutex_unlock(&iris->lock);
		return -EBUSY;
	}
	iris->suspended = true;
	mutex_unlock(&iris->lock);
	return 0;
}

static int cityman_iris_resume(struct device *dev)
{
	struct cityman_iris *iris = dev_get_drvdata(dev);
	mutex_lock(&iris->lock);
	iris->suspended = false;
	mutex_unlock(&iris->lock);
	return 0;
}

static const struct dev_pm_ops cityman_iris_pm = {
	.suspend = cityman_iris_suspend, .resume = cityman_iris_resume,
};
static const struct of_device_id cityman_iris_match[] = {
	{ .compatible = "microsoft,cityman-iris-id" }, { },
};
MODULE_DEVICE_TABLE(of, cityman_iris_match);
static struct platform_driver cityman_iris_driver = {
	.probe = cityman_iris_probe, .remove = cityman_iris_remove,
	.driver = {
		.name = "cityman-iris-id", .owner = THIS_MODULE,
		.of_match_table = cityman_iris_match, .pm = &cityman_iris_pm,
	},
};
module_platform_driver(cityman_iris_driver);
MODULE_LICENSE("GPL v2");
MODULE_DESCRIPTION("Opt-in Lumia 950 XL sensor diagnostics, without IR or image capture");
#endif
