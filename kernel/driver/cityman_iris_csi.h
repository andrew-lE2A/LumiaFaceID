/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef CITYMAN_IRIS_CSI_H
#define CITYMAN_IRIS_CSI_H

/* Fixed cityman CAMT route, recovered from the pinned original ARM driver.
 * PHY lane 3 is the combo clock; lane 4 carries the single data lane. */
#define IRIS_CSI_LANE_MASK 0x18
#define IRIS_CSI_LANE_ASSIGN 0x0004
#define IRIS_CSI_SETTLE 20
/* Original CORE_CTRL_1 construction at VA 0x41ded8 sets this flag.
 * Its exact statistics semantics remain unverified; save the readback. */
#define IRIS_CSI_ORIGINAL_CTRL1_FLAG (1U << 16)
#define IRIS_CSI_CSID_REGS 5
#define IRIS_CSI_PHY_REGS 17

/* Legacy release helpers otherwise discard clock/regulator errors. Keep the
 * first failure while still attempting all remaining teardown operations. */
#define IRIS_CSI_RELEASE_STEP(status, expression) do { \
	int iris_release_rc = (expression); \
	if (iris_release_rc < 0 && !(status)) \
		(status) = iris_release_rc; \
} while (0)

struct iris_csi_counts {
	u32 packets, ecc, crc;
};

struct iris_csi {
	bool requested, phy_initialized, csid_initialized, before_valid, after_valid;
	void *phy, *csid;
	struct iris_csi_counts before, after;
	u32 version;
	u32 phy_mux_before;
	bool phy_mux_valid;
	u32 csid_before[IRIS_CSI_CSID_REGS], csid_after[IRIS_CSI_CSID_REGS];
	u32 phy_before[IRIS_CSI_PHY_REGS], phy_after[IRIS_CSI_PHY_REGS];
	const char *stage;
	int error, cleanup_error;
};

/* Begin/end run synchronously in the same sysfs write. Both owner mutexes
 * remain held across the sensor start/stop; no userspace session can join. */
int cityman_iris_phy_lock(struct iris_csi *s);
int cityman_iris_phy_init(struct iris_csi *s);
int cityman_iris_phy_config(struct iris_csi *s);
int cityman_iris_phy_end(struct iris_csi *s);
void cityman_iris_phy_sample(struct iris_csi *s, bool after);
int cityman_iris_csi_begin(struct iris_csi *s);
void cityman_iris_csi_sample(struct iris_csi *s);
int cityman_iris_csi_end(struct iris_csi *s);
#endif
