/*
 * Lumia 950 XL opt-in sensor identification. No stream or illuminator control.
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
#endif

static void iris_cleanup(struct cityman_iris *iris)
{
	int i, rc;
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
done:
	iris->error = rc;
	iris_cleanup(iris);
	iris->status = iris->cleanup_error ? "cleanup-error" :
		(rc ? "failed" : "identified");
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
	rc = iris_identify(iris);
	mutex_unlock(&iris->lock);
	return rc < 0 ? rc : count;
}

static DEVICE_ATTR(result, 0444, result_show, NULL);
static DEVICE_ATTR(identify, 0200, NULL, identify_store);
static struct attribute *iris_attrs[] = {
	&dev_attr_result.attr, &dev_attr_identify.attr, NULL,
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
	if (!rc)
		dev_info(dev, "idle; explicit root identification required; no IR or stream control\n");
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
MODULE_DESCRIPTION("Opt-in Lumia 950 XL sensor ID diagnostic, without IR or streaming");
#endif
