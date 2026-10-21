/*
 * trigger_note_slide_selftest.c - permanent host checks for trigger_note()
 * slide re-trigger behaviour in src/cmd_parse.c (ATMlib2FX-74q).
 *
 * Background: trigger_note() decides, on a new note, whether the pending
 * volume/frequency/mod slide keeps running or is reset. slide_count bits
 * [7:6] carry the slide target (0x00 = vol, 0x40 = freq, 0x80 = mod) and bits
 * [5:0] the tick counter. The fix under test restores
 *
 *     if (q == 0)            (was: if (!q == 0), i.e. (!q) == 0)
 *
 * so the measured behaviour matches the inline comments:
 *   q == 0x00 (vol slide):  set mod only, do not reset vol;
 *   q == 0x80 (mod slide):  set vol only, keep the mod slide running;
 *   q == 0x40 (freq slide): trigger both;
 * no slide / re-triggered slide config: trigger both.
 *
 * The test compiles the real library C sources (src/atm_synth.c, which
 * includes src/cmd_parse.c) for the host, substituting only the osc.c timer
 * layer, and calls the static trigger_note() directly. Host diagnostic only:
 * it contributes no AVR bytes. Run via tests/cmd_parse/run-tests.sh.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "atm_synth.c" /* library core; includes src/cmd_parse.c */

/* ---------------- osc.c timer-layer substitution ---------------- */
struct host_cb {
	uint8_t preset;
	uint8_t counter;
	osc_tick_callback cb;
	void *priv;
};

struct osc_params osc_params_array[OSC_CH_COUNT];
static struct host_cb host_cb[OSC_TICK_CALLBACK_COUNT];

void osc_setup(void)
{
	memset(osc_params_array, 0, sizeof(osc_params_array));
	memset(host_cb, 0, sizeof(host_cb));
}

void osc_set_tick_rate(const uint8_t callback_idx, const uint16_t rate_hz)
{
	const uint16_t base = OSC_SAMPLERATE / OSC_ISR_PRESCALER_DIV;
	host_cb[callback_idx].preset = (uint8_t)(base / rate_hz - 1);
}

void osc_set_tick_callback(const uint8_t callback_idx, const osc_tick_callback cb, const void *priv)
{
	host_cb[callback_idx].cb = cb;
	host_cb[callback_idx].priv = (void *)priv;
}

void osc_get_tick_callback(const uint8_t callback_idx, osc_tick_callback *cb, void **priv)
{
	if (cb) {
		*cb = host_cb[callback_idx].cb;
	}
	if (priv) {
		*priv = host_cb[callback_idx].priv;
	}
}

/* Unused by these tests; the compact decoder requires a byte source. */
void atm_fx_compact_fetch(uint32_t offset, uint8_t *dst, uint8_t n)
{
	(void)offset;
	memset(dst, 0, n);
}

#if !ATM_HAS_FX_SLIDE
#error "trigger_note_slide_selftest requires ATM_HAS_FX_SLIDE"
#endif

static int failures = 0;

#define CHECK(cond, msg) do { \
	if (cond) { printf("ok: %s\n", (msg)); } \
	else { printf("FAIL: %s\n", (msg)); failures++; } \
} while (0)

/* Build a channel state driven by a local osc_params. */
static struct atm_channel_state make_channel(
	struct osc_params *osc, uint8_t vol, uint8_t mod,
	int8_t slide_amount, uint8_t slide_config, uint8_t slide_count)
{
	struct atm_channel_state ch;
	memset(&ch, 0, sizeof(ch));
	ch.vol = vol;
	ch.mod = mod;
	ch.dst_osc_params = osc;
	ch.vf_slide.slide_amount = slide_amount;
	ch.vf_slide.slide_config = slide_config;
	ch.vf_slide.slide_count = slide_count;
	return ch;
}

int main(void)
{
	struct osc_params osc;
	struct atm_channel_state ch;
	const uint8_t note = 60;
	const uint8_t cvol = 0x11;
	const uint8_t cmod = 0x22;

	/* S1. No active slide: both vol and mod are re-triggered. */
	memset(&osc, 0, sizeof(osc));
	osc.vol = 0xAA;
	osc.mod = 0x55;
	ch = make_channel(&osc, cvol, cmod, 0, 0x00, 0x00);
	trigger_note(note, &ch);
	CHECK(osc.vol == cvol, "no slide: ch->vol applied");
	CHECK(osc.mod == cmod, "no slide: ch->mod applied");

	/* S2. Volume slide (q == 0x00), not re-triggered: mod only, vol untouched. */
	memset(&osc, 0, sizeof(osc));
	osc.vol = 0xAA;
	osc.mod = 0x55;
	ch = make_channel(&osc, cvol, cmod, -16, 0x00, 0x00);
	trigger_note(note, &ch);
	CHECK(osc.mod == cmod, "vol slide: new note applies ch->mod");
	CHECK(osc.vol == 0xAA, "vol slide: ch->vol NOT reset (slide keeps running)");

	/* S3. Mod slide (q == 0x80): vol only, mod untouched and still running. */
	memset(&osc, 0, sizeof(osc));
	osc.vol = 0xAA;
	osc.mod = 0x55;
	ch = make_channel(&osc, cvol, cmod, -16, 0x00, 0x80);
	trigger_note(note, &ch);
	CHECK(osc.vol == cvol, "mod slide: new note applies ch->vol");
	CHECK(osc.mod == 0x55, "mod slide: ch->mod NOT reset (slide keeps running)");
	CHECK(ch.vf_slide.slide_count == 0x80, "mod slide: slide_count preserved");

	/* S4. Frequency slide (q == 0x40): both re-triggered. */
	memset(&osc, 0, sizeof(osc));
	osc.vol = 0xAA;
	osc.mod = 0x55;
	ch = make_channel(&osc, cvol, cmod, -16, 0x00, 0x40);
	trigger_note(note, &ch);
	CHECK(osc.vol == cvol, "freq slide: ch->vol applied");
	CHECK(osc.mod == cmod, "freq slide: ch->mod applied");

	/* S5. Slide re-triggered (slide_config bit 0x40): mask count, both applied. */
	memset(&osc, 0, sizeof(osc));
	osc.vol = 0xAA;
	osc.mod = 0x55;
	ch = make_channel(&osc, cvol, cmod, -16, 0x40, 0x80);
	trigger_note(note, &ch);
	CHECK(osc.vol == cvol, "re-triggered slide: ch->vol applied");
	CHECK(osc.mod == cmod, "re-triggered slide: ch->mod applied");
	CHECK(ch.vf_slide.slide_count == 0x00, "re-triggered slide: slide_count masked to 0x3F");

	if (failures) {
		printf("trigger_note_slide_selftest: %d FAILURES\n", failures);
		return 1;
	}
	printf("trigger_note_slide_selftest: all checks passed\n");
	return 0;
}
