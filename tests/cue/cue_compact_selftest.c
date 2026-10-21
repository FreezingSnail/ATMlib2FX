/*
 * cue_compact_selftest.c - host check that the compact FX backend routes the
 * CUE 1-parameter command through the shared process_1p_cmd()/apply_cmd() path
 * (ATMlib2FX-mpt claim).
 *
 * src/atm_synth.c includes src/atm_fx_compact.c, and apply_cmd() dispatches
 * 0x70..0x7F to
 * process_1p_cmd(). This test feeds a one-record compact stream containing
 * ATM_CMD_M_CUE(0x2A) and confirms the shared cue byte is latched, so the
 * command works in the FX build without a second command decoder.
 *
 * Host diagnostic only. Run via tests/cue/run-tests.sh.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <avr/pgmspace.h>

#include "atm_synth.c" /* includes cmd_parse.c + atm_fx_compact.c */

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

/* ---------------- compact fixture + byte source ---------------- */

/* 0xC0 magic, then one due-pass record for channel 0:
 *   len=7, gap=0, bitmap=0x01, glen=3, { CUE(0x2A), NOTE_C4 }, then END (0x00).
 * The record length includes its own length byte and the per-channel group. */
static const uint8_t stream_data[] = {
	0xC0, 0x07, 0x00, 0x01, 0x03,
	ATM_CMD_1P_SET_CUE, 0x2A, ATM_CMD_I_NOTE_C4,
	0x00,
};

void atm_fx_compact_fetch(uint32_t offset, uint8_t *dst, uint8_t n)
{
	for (uint8_t i = 0; i < n; i++) {
		const uint32_t at = offset + i;
		dst[i] = at < sizeof(stream_data) ? stream_data[at] : 0;
	}
}

static int failures = 0;

#define CHECK(cond, msg) do { \
	if (cond) { printf("ok: %s\n", (msg)); } \
	else { printf("FAIL: %s\n", (msg)); failures++; } \
} while (0)

int main(void)
{
	osc_setup();
	atm_synth_setup();

	CHECK(atm_synth_get_cue() == 0, "compact: cue starts empty");

	atm_fx_compact_play(0, (uint32_t)sizeof(stream_data));
	CHECK(atm_fx_compact_is_active(), "compact: stream armed");
	atm_fx_compact_service(); /* foreground refill of the ring */

	{
		osc_tick_callback cb = NULL;
		void *priv = NULL;
		osc_get_tick_callback(0, &cb, &priv);
		CHECK(cb != NULL, "compact: tick consumer registered");
		cb(0, priv); /* apply the due-pass record */
	}

	CHECK(atm_synth_check_cue(0x2A) == 1, "compact: CUE applied via process_1p_cmd");
	CHECK(atm_synth_get_cue() == 0x2A, "compact: get() returns the cue value");
	CHECK(atm_synth_get_cue() == 0, "compact: get() clears the cue");

	if (failures) {
		printf("cue_compact_selftest: %d FAILURES\n", failures);
		return 1;
	}
	printf("cue_compact_selftest: all checks passed\n");
	return 0;
}
