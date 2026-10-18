/*
 * cue_fx_selftest.c - host check that the compiled FX-stream backend routes the
 * CUE 1-parameter command through the same process_1p_cmd() handler as the
 * PROGMEM path (ATMlib2FX-mpt claim).
 *
 * Built with -DATM_HAS_FX_STREAM=1: src/atm_synth.c then includes
 * src/atm_fx_stream.c and the crates' apply_cmd() dispatches 0x70..0x7F to
 * process_1p_cmd(). This test stages a one-tick stream containing
 * ATM_CMD_M_CUE(0x2A) and confirms the shared cue byte is latched, so the
 * feature works in the FX build "for free".
 *
 * Host diagnostic only. Run via tests/cue/run-tests.sh.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <avr/pgmspace.h>

#include "atm_synth.c" /* FX stream build: includes cmd_parse.c + atm_fx_stream.c */

#if !ATM_HAS_FX_STREAM
#error "cue_fx_selftest must be compiled with -DATM_HAS_FX_STREAM=1"
#endif

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

/* ---------------- FX stream fixture + byte source ---------------- */

/* 0xF5 magic, then one APPLY record for channel 0:
 *   ctl=0x01, len=0x03, bytes { CUE(0x2A), NOTE_C4 }, then END (0x10). */
static const uint8_t stream_data[] = {
	0xF5, 0x01, 0x03, ATM_CMD_1P_SET_CUE, 0x2A, ATM_CMD_I_NOTE_C4, 0x10,
};

void atm_fx_stream_fetch(uint32_t offset, uint8_t *dst, uint8_t n)
{
	for (uint8_t i = 0; i < n; i++) {
		dst[i] = stream_data[offset + i];
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

	CHECK(atm_synth_get_cue() == 0, "fx: cue starts empty");

	atm_fx_stream_play(0, (uint32_t)sizeof(stream_data));
	CHECK(atm_fx_stream_is_active(), "fx: stream armed");
	atm_fx_stream_service(); /* foreground refill of the ring */

	{
		osc_tick_callback cb = NULL;
		void *priv = NULL;
		osc_get_tick_callback(0, &cb, &priv);
		CHECK(cb != NULL, "fx: tick consumer registered");
		cb(0, priv); /* apply the staged one-tick frame */
	}

	CHECK(atm_synth_check_cue(0x2A) == 1, "fx: CUE applied via process_1p_cmd");
	CHECK(atm_synth_get_cue() == 0x2A, "fx: get() returns the cue value");
	CHECK(atm_synth_get_cue() == 0, "fx: get() clears the cue");

	if (failures) {
		printf("cue_fx_selftest: %d FAILURES\n", failures);
		return 1;
	}
	printf("cue_fx_selftest: all checks passed\n");
	return 0;
}
