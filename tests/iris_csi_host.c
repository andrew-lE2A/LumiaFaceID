/* Execute production owner helpers with simulated receiver lifecycle APIs. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
#define __iomem
#define MAX_CSIPHY 3
#define CSI_DECODE_10BIT 2
#define CSIPHY_POWER_UP 0
#define CSIPHY_POWER_DOWN 1
#define CSID_POWER_UP 0
#define CSID_POWER_DOWN 1
struct mutex { bool locked; };
struct platform_device { int id; };
struct resource { unsigned int start; };
struct csiphy_reg_parms_t {
    u32 mipi_csiphy_glbl_pwr_cfg_addr, mipi_csiphy_glbl_reset_addr,
        mipi_csiphy_lnn_cfg1_addr, mipi_csiphy_lnn_cfg2_addr,
        mipi_csiphy_lnn_cfg3_addr, mipi_csiphy_lnn_cfg4_addr,
        mipi_csiphy_lnn_cfg5_addr, mipi_csiphy_lnn_misc1_addr,
        mipi_csiphy_interrupt_status0_addr;
};
struct csid_reg_parms_t {
    u32 csid_stats_total_pkts_rcvd_addr, csid_stats_ecc_addr, csid_stats_crc_addr,
        csid_core_ctrl_0_addr, csid_core_ctrl_1_addr, csid_cid_lut_vc_0_addr,
        csid_cid_n_cfg_addr, csid_irq_status_addr;
};
struct csiphy_device {
    struct platform_device *pdev; struct resource *mem; struct mutex mutex;
    int ref_count, csiphy_state; void *base, *clk_mux_base;
    bool cityman_iris_exclusive;
    unsigned short lane_mask[3];
    struct { struct csiphy_reg_parms_t csiphy_reg; } *ctrl_reg;
};
struct csid_device {
    struct platform_device *pdev; struct resource *mem; struct mutex mutex;
    int csid_state; bool cityman_iris_exclusive; void *base;
    unsigned int lane_assign_override;
    struct { struct csid_reg_parms_t csid_reg; } *ctrl_reg;
};
struct msm_camera_csiphy_params { unsigned int lane_cnt, settle_cnt, lane_mask,
    combo_mode, csid_core, csiphy_clk; };
struct msm_camera_csi_lane_params { unsigned int csi_lane_assign, csi_lane_mask; };
struct msm_camera_csid_vc_cfg { unsigned int cid, dt, decode_format; };
struct msm_camera_csid_params { unsigned int lane_cnt, lane_assign, phy_sel, csi_clk;
    struct { unsigned int num_cid; struct msm_camera_csid_vc_cfg *vc_cfg[16]; } lut_params; };
static bool mutex_trylock(struct mutex *m) { if (m->locked) return false; m->locked=true; return true; }
static void mutex_unlock(struct mutex *m) { assert(m->locked); m->locked=false; }
static u32 msm_camera_io_r(void *p) { return *(u32 *)p; }
static int fault, calls;
static u32 mux, stats[8], phy_regs[128];
static void msm_camera_io_w(u32 v, void *p) {
    if (fault==20 && p==&stats[4]) return; /* control flag does not latch */
    *(u32 *)p=v;
}
static int step(int n) { calls++; return fault==n ? -EIO : 0; }
static int msm_csiphy_init(struct csiphy_device *p) {
    int rc=step(1); assert(p->mutex.locked);
    if (fault==7) { p->ref_count=1; return -ENOMEM; } /* legacy dirty failure */
    if (rc) return rc;
    p->ref_count=1; p->csiphy_state=CSIPHY_POWER_UP;
    p->base=phy_regs; p->clk_mux_base=&mux; return 0;
}
static int msm_csiphy_lane_config(struct csiphy_device *p, struct msm_camera_csiphy_params *v) {
    assert(p->mutex.locked && p->ref_count==1);
    assert(v->lane_cnt==1 && v->settle_cnt==22 && v->lane_mask==0x18);
    assert(v->combo_mode==1 && v->csid_core==3 && v->csiphy_clk==200000000);
    p->lane_mask[2]=v->lane_mask; mux=(mux & ~0xf0U) | 0x30;
    phy_regs[0x144/4]=0x31; phy_regs[0x140/4]=0x10;
    phy_regs[(0x40*3+4)/4]=phy_regs[(0x40*4+4)/4]=0x10;
    phy_regs[(0x40*3+8)/4]=phy_regs[(0x40*4+8)/4]=v->settle_cnt;
    phy_regs[(0x40*3+0x28)/4]=4; phy_regs[(0x40*4+0x28)/4]=8;
    return step(4);
}
static int msm_csiphy_release(struct csiphy_device *p, struct msm_camera_csi_lane_params *v) {
    assert(p->mutex.locked && p->ref_count==1);
    assert(v->csi_lane_assign==4 && v->csi_lane_mask==0x18);
    if (step(6)) return -EIO;
    p->lane_mask[2]=0; p->base=NULL; p->ref_count=0;
    p->csiphy_state=CSIPHY_POWER_DOWN; return 0;
}
static int msm_csid_init(struct csid_device *d, u32 *v) {
    assert(d->mutex.locked && d->cityman_iris_exclusive);
    d->base=stats; d->csid_state=CSID_POWER_UP; *v=0x30000000;
    return step(2); /* includes initialized-but-reset-timed-out case */
}
static int msm_csid_config(struct csid_device *d, struct msm_camera_csid_params *v) {
    assert(d->mutex.locked && d->cityman_iris_exclusive);
    assert(v->lane_cnt==1 && v->lane_assign==4 && v->phy_sel==2 && v->csi_clk==200000000);
    assert(v->lut_params.num_cid==1 && v->lut_params.vc_cfg[0]->cid==0);
    assert(v->lut_params.vc_cfg[0]->dt==0x2b && v->lut_params.vc_cfg[0]->decode_format==2);
    stats[3]=0x40; stats[4]=0x4000f; stats[5]=0x2b; stats[6]=0x23;
    return step(3);
}
static int msm_csid_release(struct csid_device *d) {
    assert(d->mutex.locked && d->cityman_iris_exclusive);
    if (step(5)) return -EIO;
    d->csid_state=CSID_POWER_DOWN; d->base=NULL; return 0;
}
#include "../kernel/driver/cityman_iris_csi.h"
#include "../kernel/driver/cityman_iris_csiphy.h"
#include "../kernel/driver/cityman_iris_csid.h"

int main(void) {
    struct platform_device pp={2}, dp={3};
    struct resource pm={0xfda0b400}, dm={0xfda08c00};
    struct csiphy_device p; struct csid_device d; struct iris_csi s;
    typeof(*d.ctrl_reg) regs={{0,4,8,12,16,20,24,28}};
    typeof(*p.ctrl_reg) preg={{0x144,0x140,0,4,8,0xc,0x10,0x28,0x18c}};
    unsigned int n;
    int cleanup_status=0, teardown_calls=0;
    IRIS_CSI_RELEASE_STEP(cleanup_status, (++teardown_calls, -EIO));
    IRIS_CSI_RELEASE_STEP(cleanup_status, (++teardown_calls, -ENOMEM));
    IRIS_CSI_RELEASE_STEP(cleanup_status, (++teardown_calls, 0));
    assert(cleanup_status==-EIO && teardown_calls==3);
    for(n=0;n<21;n++) {
        memset(&p,0,sizeof(p)); memset(&d,0,sizeof(d)); memset(&s,0,sizeof(s));
        p.pdev=&pp; p.mem=&pm; p.csiphy_state=CSIPHY_POWER_DOWN; p.ctrl_reg=&preg;
        d.pdev=&dp; d.mem=&dm; d.csid_state=CSID_POWER_DOWN; d.ctrl_reg=&regs;
        cityman_iris_phy_device=&p; cityman_iris_csid_device=&d;
        mux=0xa5; memset(stats,0,sizeof(stats)); calls=0; fault=n<=7 ? n : 0;
        memset(phy_regs,0,sizeof(phy_regs));
        if(n==8) p.ref_count=1;
        if(n==9) p.lane_mask[0]=1;
        if(n==10) p.mutex.locked=true;
        if(n==11) d.mutex.locked=true;
        if(n==12) d.csid_state=CSID_POWER_UP;
        if(n==13) d.lane_assign_override=0x4320;
        if(n==14) cityman_iris_phy_device=NULL;
        if(n==15) cityman_iris_csid_device=NULL;
        if(n==16) p.base=&mux;
        if(n==17) d.base=stats;
        if(n==18) pm.start=0;
        if(n==19) dm.start=0;
        if(n==20) fault=20;
        if(n==0 || n==5 || n==6) {
            assert(!cityman_iris_csi_begin(&s));
            assert(p.mutex.locked && d.mutex.locked && s.before_valid);
            assert(!s.before.packets && !s.before.ecc && !s.before.crc);
            assert(s.csid_before[0]==0x40 && s.csid_before[1]==0x5000f);
            assert(s.csid_before[2]==0x2b && s.csid_before[3]==0x23);
            assert(s.phy_before[0]==0x35 && s.phy_before[1]==0x31 && s.phy_before[2]==0x10);
            assert(s.phy_before[3]==0x10 && s.phy_before[4]==22 && s.phy_before[5]==4);
            assert(s.phy_before[6]==0x10 && s.phy_before[7]==22 && s.phy_before[8]==8);
            stats[0]=120; stats[1]=0xabcd0002; stats[2]=3;
            phy_regs[0x18c/4]=0x12; phy_regs[(0x18c+7*4)/4]=0x34;
            if(n==0) {
                cityman_iris_csi_sample(&s);
                assert(s.after.packets==120 && s.csid_after[1]==0x5000f);
                assert(s.phy_after[9]==0x12 && s.phy_after[16]==0x34);
                stats[0]=999; /* stop-time state must not overwrite saved running state */
                cityman_iris_csi_sample(&s);
                assert(s.after.packets==120);
            }
            assert(cityman_iris_csi_end(&s)==((n==5 || n==6) ? -EIO : 0));
            assert(s.after_valid && s.after.packets==120 && s.after.ecc==2 && s.after.crc==3);
            assert(mux==0xa5); /* restore shared route before releasing PHY */
        } else {
            assert(cityman_iris_csi_begin(&s)<0);
            assert(s.error<0);
            if(n>=8 && n<20) assert(!calls); /* refuse busy/wrong hardware before initialization */
            if(n==20) assert(!s.before_valid && !s.after_valid);
        }
        if(n==5 || n==6 || n==7) assert(s.cleanup_error<0);
        else assert(!s.cleanup_error);
        assert(!s.phy && !s.csid && !s.phy_initialized && !s.csid_initialized);
        assert(!d.cityman_iris_exclusive);
        assert(!p.cityman_iris_exclusive);
        assert(p.mutex.locked==(n==10) && d.mutex.locked==(n==11));
        assert(!cityman_iris_csi_end(&s)); /* no double release on outer cleanup */
        pm.start=0xfda0b400; dm.start=0xfda08c00;
    }
    puts("21 production receiver lifecycle scenarios passed");
    return 0;
}
