/*
 * cue_selftest.c - permanent host checks for the CUE command channel
 * (ATMlib2FX-mpt), PROGMEM score/SFX path.
 *
 * The CUE command (ATM_CMD_M_CUE(v), command id 0x77) latches a byte into the
 * single shared atmlib_state.cue holder. Sketches read it with
 * atm_synth_get_cue() (value + clear, 0 = none) or compare without clearing
 * with atm_synth_check_cue(id). This test compiles the real library C sources
 * (src/atm_synth.c, which includes src/cmd_parse.c) for the host with an AVR
 * PROGMEM shim, and drives the registered osc tick callbacks exactly as the
 * timer ISR would.
 *
 * Checks:
 *   P1..P8  score path: latch, check (no clear), get (value + clear).
 *   P9..P12 SFX path: an SFX cue is latched into the same shared byte and
 *           stays observable after the SFX stops (upstream semantics).
 *
 * Host diagnostic only: contributes no AVR bytes. Run via tests/cue/run-tests.sh.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stddef.h>

#include <avr/pgmspace.h>

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

static int fire(const uint8_t callback_idx)
{
	osc_tick_callback cb = NULL;
	void *priv = NULL;
	osc_get_tick_callback(callback_idx, &cb, &priv);
	if (!cb) {
		return 0;
	}
	cb(callback_idx, priv);
	return 1;
}

/* ---------------- fixtures ---------------- */

/* One pattern, four channels, FULL format so play_score() can resolve the
 * entry-pattern array. CUE(0x2A) runs on the first tick, CUE(0x2B) after one
 * 8-tick delay. */
#define PATTERN0_DATA {            \
	ATM_CMD_M_CUE(0x2A),       \
	ATM_CMD_I_NOTE_C4,         \
	ATM_CMD_M_DELAY_TICKS(8),  \
	ATM_CMD_M_CUE(0x2B),       \
	ATM_CMD_M_DELAY_TICKS(8),  \
	ATM_CMD_I_NOTE_OFF,        \
	ATM_CMD_I_STOP,            \
}
const uint8_t pattern0_array[] = PATTERN0_DATA;

const PROGMEM struct cue_score_data {
	uint8_t fmt;
	uint8_t num_patterns;
	uint16_t patterns_offset[1];
	uint8_t num_channels;
	uint8_t start_patterns[4];
	uint8_t pattern0[sizeof(pattern0_array)];
} cue_score = {
	.fmt = ATM_SCORE_FMT_FULL,
	.num_patterns = 1,
	.patterns_offset = { (uint16_t)offsetof(struct cue_score_data, pattern0) },
	.num_channels = 4,
	.start_patterns = { 0, 0, 0, 0 },
	.pattern0 = PATTERN0_DATA,
};

/* Minimal-mono SFX: CUE(0x33) on its first tick. */
const PROGMEM struct cue_sfx_data {
	uint8_t fmt;
	uint8_t pattern0[6];
} cue_sfx = {
	.fmt = ATM_SCORE_FMT_MINIMAL_MONO,
	.pattern0 = {
		ATM_CMD_M_CUE(0x33),
		ATM_CMD_I_NOTE_C4,
		ATM_CMD_M_DELAY_TICKS(4),
		ATM_CMD_I_NOTE_OFF,
		ATM_CMD_I_STOP,
	},
};

static struct atm_sfx_state sfx_state;
static int failures = 0;

#define CHECK(cond, msg) do { \
	if (cond) { printf("ok: %s\n", (msg)); } \
	else { printf("FAIL: %s\n", (msg)); failures++; } \
} while (0)

int main(void)
{
	osc_setup();
	atm_synth_setup();

	CHECK(ATM_CMD_M_CUE(0x5A) == 0x5A && ATM_CMD_1P_SET_CUE - 1 == ATM_CMD_1P_SET_MOD,
	      "macro encodes id 0x77 immediately after SET_MOD");

	CHECK(atm_synth_get_cue() == 0, "cue starts empty (0 = none)");

	atm_synth_play_score((const uint8_t *)&cue_score);
	fire(0); /* first music tick runs CUE(0x2A) */

	CHECK(atm_synth_check_cue(0x2A) == 1, "score: check(id) matches latched cue");
	CHECK(atm_synth_check_cue(0x2B) == 0, "score: check(other) does not match");
	CHECK(atm_synth_check_cue(0x2A) == 1, "score: check(id) does not clear");
	CHECK(atm_synth_get_cue() == 0x2A, "score: get() returns the cue value");
	CHECK(atm_synth_get_cue() == 0, "score: get() clears the cue");
	CHECK(atm_synth_check_cue(0x2A) == 0, "score: cleared cue no longer matches");

	/* Advance to the second CUE(0x2B) (8-tick delay) and confirm re-latch. */
	{
		int found = 0;
		for (int i = 0; i < 32 && !found; i++) {
			fire(0);
			if (atm_synth_check_cue(0x2B)) {
				found = 1;
			}
		}
		CHECK(found, "score: later CUE(0x2B) latches");
		CHECK(atm_synth_get_cue() == 0x2B, "score: get() returns latest cue");
	}

	/* SFX shares the same byte and stays observable after it stops. */
	atm_synth_get_cue(); /* clear */
	atm_synth_play_sfx_track(OSC_CH_ONE, (const uint8_t *)&cue_sfx, &sfx_state);
	fire(1);
	CHECK(atm_synth_check_cue(0x33) == 1, "sfx: cue latched into shared byte");
	atm_synth_stop_sfx_track(&sfx_state);
	CHECK(atm_synth_check_cue(0x33) == 1, "sfx: cue observable after stop");
	CHECK(atm_synth_get_cue() == 0x33, "sfx: get() returns shared cue");

	if (failures) {
		printf("cue_selftest: %d FAILURES\n", failures);
		return 1;
	}
	printf("cue_selftest: all checks passed\n");
	return 0;
}
