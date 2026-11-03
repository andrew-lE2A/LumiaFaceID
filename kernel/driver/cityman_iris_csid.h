/* SPDX-License-Identifier: GPL-2.0-only */
/* Included by the owning CSID driver, after its ordinary lifecycle helpers. */
#ifndef CITYMAN_IRIS_CSI_H
#include "../cityman_iris_csi.h"
#endif

static struct csid_device *cityman_iris_csid_device;

static void cityman_iris_csi_counts(struct csid_device *d, struct iris_csi_counts *c)
{
	c->packets = msm_camera_io_r(d->base + d->ctrl_reg->csid_reg.csid_stats_total_pkts_rcvd_addr);
	c->ecc = msm_camera_io_r(d->base + d->ctrl_reg->csid_reg.csid_stats_ecc_addr);
	c->crc = msm_camera_io_r(d->base + d->ctrl_reg->csid_reg.csid_stats_crc_addr);
}

int cityman_iris_csi_end(struct iris_csi *s)
{
	struct csid_device *d = s->csid;
	int rc = 0, phy_rc;
	if (d) {
		if (s->csid_initialized) {
			cityman_iris_csi_counts(d, &s->after);
			s->after_valid = true;
			rc = msm_csid_release(d);
			if (!rc && (d->csid_state != CSID_POWER_DOWN || d->base))
				rc = -EIO;
		}
		d->cityman_iris_exclusive = false;
		s->csid_initialized = false;
		s->csid = NULL;
		mutex_unlock(&d->mutex);
	}
	phy_rc = cityman_iris_phy_end(s);
	if (!rc)
		rc = phy_rc;
	if (rc && !s->cleanup_error)
		s->cleanup_error = rc;
	if (s->before_valid && !s->cleanup_error)
		s->stage = "released";
	return rc;
}

int cityman_iris_csi_begin(struct iris_csi *s)
{
	struct csid_device *d = cityman_iris_csid_device;
	struct msm_camera_csid_vc_cfg vc = { .cid = 0, .dt = 0x2b, .decode_format = CSI_DECODE_10BIT };
	struct msm_camera_csid_params params = {
		.lane_cnt = 1, .lane_assign = IRIS_CSI_LANE_ASSIGN,
		.phy_sel = 2, .csi_clk = 200000000,
	};
	int rc;
	s->stage = "phy-lock";
	rc = cityman_iris_phy_lock(s);
	if (rc)
		goto failed;
	s->stage = "csid-lock";
	if (!d || d->pdev->id != 3 || d->mem->start != 0xfda08c00) {
		rc = -ENODEV;
		goto failed;
	}
	if (!mutex_trylock(&d->mutex)) {
		rc = -EBUSY;
		goto failed;
	}
	s->csid = d;
	if (d->csid_state != CSID_POWER_DOWN || d->base ||
	    (d->lane_assign_override && d->lane_assign_override != IRIS_CSI_LANE_ASSIGN)) {
		rc = -EBUSY;
		goto failed;
	}
	d->cityman_iris_exclusive = true;
	s->stage = "phy-init";
	rc = cityman_iris_phy_init(s);
	if (rc)
		goto failed;
	s->stage = "csid-init";
	rc = msm_csid_init(d, &s->version);
	if (d->csid_state == CSID_POWER_UP && d->base)
		s->csid_initialized = true;
	if (rc && !s->csid_initialized && d->base)
		s->cleanup_error = -EIO;
	if (rc)
		goto failed;
	if (!s->csid_initialized) {
		rc = -EIO;
		goto failed;
	}
	s->stage = "csid-config";
	params.lut_params.num_cid = 1;
	params.lut_params.vc_cfg[0] = &vc;
	rc = msm_csid_config(d, &params);
	if (rc)
		goto failed;
	s->stage = "phy-config";
	rc = cityman_iris_phy_config(s);
	if (rc)
		goto failed;
	cityman_iris_csi_counts(d, &s->before);
	s->before_valid = true;
	s->stage = "listening";
	return 0;
failed:
	s->error = rc;
	cityman_iris_csi_end(s);
	return rc;
}
