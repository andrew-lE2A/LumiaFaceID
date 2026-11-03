/* SPDX-License-Identifier: GPL-2.0-only */
/* Included by the owning CSIPHY driver, after its ordinary lifecycle helpers. */
#ifndef CITYMAN_IRIS_CSI_H
#include "../cityman_iris_csi.h"
#endif

/* Built-in platform device, published only at the end of successful probe.
 * The pinned driver has no remove callback and does not free this object. */
static struct csiphy_device *cityman_iris_phy_device;

int cityman_iris_phy_lock(struct iris_csi *s)
{
	struct csiphy_device *p = cityman_iris_phy_device;
	unsigned int i;
	if (!p || p->pdev->id != 2 || p->mem->start != 0xfda0b400)
		return -ENODEV;
	if (!mutex_trylock(&p->mutex))
		return -EBUSY;
	if (p->ref_count || p->csiphy_state != CSIPHY_POWER_DOWN || p->base) {
		mutex_unlock(&p->mutex);
		return -EBUSY;
	}
	for (i = 0; i < MAX_CSIPHY; i++) {
		if (p->lane_mask[i]) {
			mutex_unlock(&p->mutex);
			return -EBUSY;
		}
	}
	s->phy = p;
	p->cityman_iris_exclusive = true;
	return 0;
}

int cityman_iris_phy_init(struct iris_csi *s)
{
	struct csiphy_device *p = s->phy;
	int rc = msm_csiphy_init(p);
	if (p->csiphy_state == CSIPHY_POWER_UP && p->base && p->ref_count == 1) {
		s->phy_initialized = true;
		if (p->clk_mux_base) {
			s->phy_mux_before = msm_camera_io_r(p->clk_mux_base);
			s->phy_mux_valid = true;
		}
	}
	if (!rc && (!s->phy_initialized || !s->phy_mux_valid))
		rc = -EIO;
	/* Some legacy init failures do not fully unwind their votes. Never
	 * report clean recovery or restart services when that state is dirty. */
	if (rc && !s->phy_initialized && (p->base || p->ref_count))
		s->cleanup_error = -EIO;
	return rc;
}

int cityman_iris_phy_config(struct iris_csi *s)
{
	struct msm_camera_csiphy_params params = {
		.lane_cnt = 1, .settle_cnt = IRIS_CSI_SETTLE,
		.lane_mask = IRIS_CSI_LANE_MASK, .combo_mode = 1,
		.csid_core = 3, .csiphy_clk = 200000000,
	};
	return msm_csiphy_lane_config(s->phy, &params);
}

void cityman_iris_phy_sample(struct iris_csi *s, bool after)
{
	struct csiphy_device *p = s->phy;
	struct csiphy_reg_parms_t *r = &p->ctrl_reg->csiphy_reg;
	u32 *values = after ? s->phy_after : s->phy_before;
	unsigned int i;
	values[0] = msm_camera_io_r(p->clk_mux_base);
	values[1] = msm_camera_io_r(p->base + r->mipi_csiphy_glbl_pwr_cfg_addr);
	values[2] = msm_camera_io_r(p->base + r->mipi_csiphy_glbl_reset_addr);
	values[3] = msm_camera_io_r(p->base + r->mipi_csiphy_lnn_cfg2_addr + 0x40 * 3);
	values[4] = msm_camera_io_r(p->base + r->mipi_csiphy_lnn_cfg3_addr + 0x40 * 3);
	values[5] = msm_camera_io_r(p->base + r->mipi_csiphy_lnn_misc1_addr + 0x40 * 3);
	values[6] = msm_camera_io_r(p->base + r->mipi_csiphy_lnn_cfg2_addr + 0x40 * 4);
	values[7] = msm_camera_io_r(p->base + r->mipi_csiphy_lnn_cfg3_addr + 0x40 * 4);
	values[8] = msm_camera_io_r(p->base + r->mipi_csiphy_lnn_misc1_addr + 0x40 * 4);
	/* These are the same eight status registers read by the owner's IRQ
	 * handler. Do not clear them or enable additional interrupts here. */
	for (i = 0; i < 8; i++)
		values[9 + i] = msm_camera_io_r(p->base +
			r->mipi_csiphy_interrupt_status0_addr + i * 4);
}

int cityman_iris_phy_end(struct iris_csi *s)
{
	struct csiphy_device *p = s->phy;
	struct msm_camera_csi_lane_params lanes = {
		.csi_lane_assign = IRIS_CSI_LANE_ASSIGN,
		.csi_lane_mask = IRIS_CSI_LANE_MASK,
	};
	int rc = 0;
	if (!p)
		return 0;
	if (s->phy_initialized) {
		if (s->phy_mux_valid)
			msm_camera_io_w(s->phy_mux_before, p->clk_mux_base);
		rc = msm_csiphy_release(p, &lanes);
		if (!rc && (p->ref_count || p->csiphy_state != CSIPHY_POWER_DOWN || p->base))
			rc = -EIO;
	}
	s->phy_initialized = false;
	s->phy_mux_valid = false;
	s->phy = NULL;
	p->cityman_iris_exclusive = false;
	mutex_unlock(&p->mutex);
	return rc;
}
