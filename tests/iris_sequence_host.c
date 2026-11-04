/* Executes the production power sequence with simulated kernel operations. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>

typedef uint16_t u16;
typedef uint8_t u8;
typedef uint32_t u32;
struct device { int unused; };
struct mutex { int unused; };
struct regulator { int id; };
struct clk { int id; unsigned long rate; };
struct pinctrl { int unused; };
struct pinctrl_state { int id; };
struct cci_device { int ref_count; };
struct msm_camera_cci_client { void *cci_subdev; };
enum msm_cci_cmd_type { MSM_CCI_INIT, MSM_CCI_RELEASE };
struct cityman_iris;
#ifdef CONFIG_CITYMAN_IRIS_STREAM
struct iris_stream_io;
static struct iris_stream_io iris_stream_io(struct cityman_iris *);
static int iris_nvm_finish(struct cityman_iris *);
static int iris_nvm_probe(struct cityman_iris *);
#endif
static int iris_cci_command(struct cityman_iris *, enum msm_cci_cmd_type);
static int iris_read_model(struct cityman_iris *, u16 *);
static const char *failure;
static int remaining, enables[4], gpio_owned, reads, events, bad_voltage;
static u16 returned_model;
static struct cci_device cci;

static int event(const char *name)
{
    events++;
    if (failure && !strcmp(name, failure) && remaining) {
        remaining--;
        return -EIO;
    }
    return 0;
}
static int gpio_request(int pin, const char *label)
{
    int rc;
    assert(pin == 102 && label);
    rc = event("request"); if (!rc) gpio_owned = 1;
    return rc;
}
static int gpio_direction_output(int pin, int value)
{ assert(pin == 102 && value == 0); return event("direction"); }
static void gpio_set_value_cansleep(int pin, int value)
{ assert(pin == 102 && (value == 0 || value == 1)); event(value ? "reset-high" : "reset-low"); }
static void gpio_free(int pin)
{ assert(pin == 102 && gpio_owned); gpio_owned = 0; event("free"); }
static void usleep_range(int low, int high)
{ assert(low > 0 && high >= low); }
static int pinctrl_select_state(struct pinctrl *p, struct pinctrl_state *s)
{ assert(p); return event(s->id ? "sleep" : "active"); }
static int regulator_enable(struct regulator *r)
{
    char name[32]; int rc;
    snprintf(name, sizeof(name), "enable:%d", r->id); rc = event(name);
    if (!rc) enables[r->id]++;
    return rc;
}
static int regulator_disable(struct regulator *r)
{
    char name[32]; int rc;
    assert(enables[r->id] == 1);
    snprintf(name, sizeof(name), "disable:%d", r->id); rc = event(name);
    if (!rc) enables[r->id]--;
    return rc;
}
static int regulator_get_voltage(struct regulator *r)
{
    const int values[] = {2800000, 1800000, 1300000, 1200000};
    char name[32]; int rc;
    snprintf(name, sizeof(name), "voltage:%d", r->id); rc = event(name);
    return rc ? rc : values[r->id] + (r->id == bad_voltage);
}
static unsigned long clk_get_rate(struct clk *c) { return c->rate; }
static int clk_set_rate(struct clk *c, unsigned long rate)
{ int rc = event(rate == 9600000 ? "rate" : "restore"); if (!rc) c->rate = rate; return rc; }
static int clock_refs[2];
static int clk_prepare_enable(struct clk *c)
{ int rc = event(c->id ? "clock" : "source"); if (!rc) clock_refs[c->id]++; return rc; }
static void clk_disable_unprepare(struct clk *c)
{ assert(clock_refs[c->id] == 1); clock_refs[c->id]--; }
static void *v4l2_get_subdevdata(void *p) { return p; }
#define dev_info(dev, ...) ((void)(dev))
#define CITYMAN_IRIS_HOST_TEST
#include "../kernel/driver/cityman_iris_id.c"

#ifdef CONFIG_CITYMAN_IRIS_STREAM
/* The host harness excludes production CCI helpers; these are not exercised. */
static int iris_nvm_finish(struct cityman_iris *iris) { (void)iris; return 0; }
static int iris_nvm_probe(struct cityman_iris *iris) { (void)iris; return 0; }
#endif

static int iris_cci_command(struct cityman_iris *iris, enum msm_cci_cmd_type cmd)
{
    int rc = event(cmd == MSM_CCI_INIT ? "cci-init" : "cci-release");
    assert(iris->client.cci_subdev == &cci);
    if (!rc) cci.ref_count += cmd == MSM_CCI_INIT ? 1 : -1;
    assert(cci.ref_count >= 0);
    return rc;
}
static int iris_read_model(struct cityman_iris *iris, u16 *model)
{
    int rc;
    assert(iris->clock_on && iris->cci_on && gpio_owned);
    reads++; rc = event("read");
    if (!rc) *model = returned_model;
    return rc;
}
static struct cityman_iris state;
static struct regulator regs[4];
static struct clk source, clock;
static struct pinctrl pins;
static struct pinctrl_state active = {0}, sleep_state = {1};
static struct device device;
static void reset(const char *fail, int count)
{
    int i;
    memset(&state, 0, sizeof(state)); memset(enables, 0, sizeof(enables));
    memset(clock_refs, 0, sizeof(clock_refs)); cci.ref_count = 0;
    failure = fail; remaining = count; gpio_owned = reads = events = 0;
    bad_voltage = -1; returned_model = IRIS_MODEL;
    state.dev = &device; state.reset = 102; state.pins = &pins;
    state.active = &active; state.sleep = &sleep_state;
    source.id = 0; source.rate = 24000000; clock.id = 1;
    state.source = &source; state.clock = &clock;
    state.client.cci_subdev = &cci;
    for (i = 0; i < 4; i++) { regs[i].id = i; state.rails[i] = &regs[i]; }
}
static void balanced(void)
{
    int i;
    for (i = 0; i < 4; i++) assert(!enables[i] && !state.enabled[i]);
    assert(!gpio_owned && !state.gpio_owned && !cci.ref_count && !state.cci_on);
    assert(!clock_refs[0] && !clock_refs[1] && !state.source_on && !state.clock_on);
    assert(source.rate == 24000000 && !state.blocked && !state.cleanup_error);
}
int main(void)
{
    const char *failures[] = {"request", "direction", "active", "enable:0", "enable:1",
        "enable:2", "enable:3", "voltage:0", "voltage:2", "voltage:3",
        "rate", "source", "clock", "cci-init", "read"};
    const char *cleanup_failures[] = {"cci-release", "sleep", "disable:0", "disable:1",
        "disable:2", "disable:3", "restore"};
    unsigned int i; int count = 0, previous;
    reset(NULL, 0); assert(!iris_identify(&state)); assert(!strcmp(state.status, "identified"));
    assert(state.model == IRIS_MODEL && state.attempts == 1); balanced(); count++;
    for (i = 0; i < sizeof(failures)/sizeof(*failures); i++) {
        reset(failures[i], 2); assert(iris_identify(&state) < 0);
        assert(state.error < 0 && !strcmp(state.status, "failed")); balanced(); count++;
    }
    reset("read", 1); assert(!iris_identify(&state) && reads == 2); balanced(); count++;
    reset(NULL, 0); returned_model = 0xffff; assert(iris_identify(&state) == -ENODEV);
    assert(state.model == 0xffff); balanced(); count++;
    reset(NULL, 0); bad_voltage = 2; assert(iris_identify(&state) == -ERANGE);
    assert(!reads); balanced(); count++;
    for (i = 0; i < sizeof(cleanup_failures)/sizeof(*cleanup_failures); i++) {
        reset(cleanup_failures[i], 1); assert(iris_identify(&state) < 0);
        assert(state.blocked && state.cleanup_error && !strcmp(state.status, "cleanup-error"));
        previous = events; assert(iris_identify(&state) == -EBUSY && events == previous); count++;
    }
    reset(NULL, 0); cci.ref_count = 1; assert(iris_identify(&state) == -EBUSY && !events); count++;
    reset(NULL, 0); state.suspended = true; assert(iris_identify(&state) == -EBUSY && !events); count++;
    printf("%d actual production-sequence scenarios passed (simulated hardware only)\n", count);
    return 0;
}
