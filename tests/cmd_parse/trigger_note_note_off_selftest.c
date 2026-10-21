/*
 * trigger_note_note_off_selftest.c - permanent host checks for note-off /
 * note-cut behaviour of trigger_note() in src/cmd_parse.c (ATMlib2FX-mgd).
 *
 * Background: trigger_note() handles note index 0 as note off (also used by
 * the arpeggio/note-cut path in src/atm_synth.c). Before this fix the branch
 * wrote vol = 0 but fell through to trigger_both, which restored ch->vol and
 * retriggered ch->mod. The intended upstream behaviour is:
 *
 *     note off:  osc.vol = 0; do not touch osc.mod;
 *
 * so a raw NOTE_OFF gates the channel and a note cut really silences it, while
 * an in-flight mod slide and the last SET_MOD value survive. Note-on behaviour
 * (vol and mod both triggered) is checked here as a guard against regression.
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
#error "trigger_note_note_off_selftest requires ATM_HAS_FX_SLIDE"
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
	const uint8_t cvol = 0x11;
	const uint8_t cmod = 0x22;

	/* N1. Note off with no slide: vol is zeroed, mod is not retriggered. */
	memset(&osc, 0, sizeof(osc));
	osc.vol = 0xAA;
	osc.mod = 0x55;
	ch = make_channel(&osc, cvol, cmod, 0, 0x00, 0x00);
	trigger_note(0, &ch);
	CHECK(osc.vol == 0, "note off: osc.vol zeroed");
	CHECK(osc.mod == 0x55, "note off: osc.mod NOT retriggered (old code wrote 0x22)");

	/* N2. Note off with an active mod slide: the slide state and mod survive. */
	memset(&osc, 0, sizeof(osc));
	osc.vol = 0xAA;
	osc.mod = 0x55;
	ch = make_channel(&osc, cvol, cmod, -16, 0x00, 0x80);
	trigger_note(0, &ch);
	CHECK(osc.vol == 0, "note off + mod slide: osc.vol zeroed");
	CHECK(osc.mod == 0x55, "note off + mod slide: osc.mod preserved");
	CHECK(ch.vf_slide.slide_count == 0x80, "note off + mod slide: slide_count preserved");
	CHECK(ch.vf_slide.slide_amount == -16, "note off + mod slide: slide_amount preserved");

	/* N3. Note off with a volume slide: mod still untouched, vol zeroed. */
	memset(&osc, 0, sizeof(osc));
	osc.vol = 0xAA;
	osc.mod = 0x55;
	ch = make_channel(&osc, cvol, cmod, -16, 0x00, 0x00);
	trigger_note(0, &ch);
	CHECK(osc.vol == 0, "note off + vol slide: osc.vol zeroed");
	CHECK(osc.mod == 0x55, "note off + vol slide: osc.mod preserved");

	/* N4. Note on still triggers both, so the return does not leak. */
	memset(&osc, 0, sizeof(osc));
	osc.vol = 0xAA;
	osc.mod = 0x55;
	ch = make_channel(&osc, cvol, cmod, 0, 0x00, 0x00);
	trigger_note(60, &ch);
	CHECK(osc.vol == cvol, "note on: osc.vol triggered");
	CHECK(osc.mod == cmod, "note on: osc.mod triggered");

	/* N5. Note on after a note off re-applies both values. */
	memset(&osc, 0, sizeof(osc));
	ch = make_channel(&osc, cvol, cmod, 0, 0x00, 0x00);
	trigger_note(0, &ch);
	trigger_note(60, &ch);
	CHECK(osc.vol == cvol, "note off then note on: osc.vol restored");
	CHECK(osc.mod == cmod, "note off then note on: osc.mod restored");

	if (failures) {
		printf("trigger_note_note_off_selftest: %d FAILURES\n", failures);
		return 1;
	}
	printf("trigger_note_note_off_selftest: all checks passed\n");
	return 0;
}
