/*
 * orig_trace.c - original-engine loop reference trace (ATMlib2FX-hlh.8).
 *
 * Compiles the *unmodified* library C sources (src/atm_synth.c and the
 * src/cmd_parse.c it includes) for the host with only the osc.c timer layer
 * substituted by a stub that reproduces the Timer3 ISR callback scheduling
 * (2000 Hz base, floor-quantized tick rates). The library's own score parsing,
 * command interpreter, effect implementation, loop restart and tick handler run
 * unchanged, so the emitted CSV is the original implementation's behaviour.
 *
 * A case's song.h is selected with -I<case> (like the footprint_baseline
 * harness); the score object is `score`.
 *
 * Usage: orig_trace <music_ticks>
 * Host diagnostic build; contributes no AVR bytes.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "atm_synth.c" /* includes src/cmd_parse.c; library core, unmodified */

/* ---- osc.c timer-layer substitution (mirrors the hlh.1 harness) ---- */
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
	uint8_t i;
	memset(osc_params_array, 0, sizeof(osc_params_array));
	memset(host_cb, 0, sizeof(host_cb));
	for (i = 0; i < OSC_CH_COUNT; i++)
		osc_params_array[i].mod = 0x7F;
	osc_params_array[OSC_CH_THREE].phase_increment = 0x0001;
}

void osc_set_tick_rate(const uint8_t callback_idx, const uint16_t rate_hz)
{
	uint16_t base = OSC_SAMPLERATE / OSC_ISR_PRESCALER_DIV; /* 2000 */
	host_cb[callback_idx].preset = (uint8_t)(base / rate_hz - 1);
}

void osc_set_tick_callback(const uint8_t callback_idx, const osc_tick_callback cb, const void *priv)
{
	host_cb[callback_idx].cb = cb;
	host_cb[callback_idx].priv = (void *)priv;
	if (cb) host_cb[callback_idx].counter = 0;
}

void osc_get_tick_callback(const uint8_t callback_idx, osc_tick_callback *cb, void **priv)
{
	if (cb) *cb = host_cb[callback_idx].cb;
	if (priv) *priv = host_cb[callback_idx].priv;
}

#include "song.h"
#include "loops_trace_common.h"

static uint64_t g_base = 0;
static uint32_t g_music_ticks = 0;
static uint32_t g_limit = 64;

static void record_music_tick(void)
{
	printf("M,%u,%llu,%u,0x%02x",
		(unsigned)g_music_ticks, (unsigned long long)g_base,
		(unsigned)atmlib_state.tick_rate,
		(unsigned)atmlib_state.channel_active_mute);
	for (uint8_t c = 0; c < OSC_CH_COUNT; c++)
		loops_print_channel_fields(&osc_params_array[c], &channels[c]);
	printf("\n");
}

static void host_tick_handler(void)
{
	for (uint8_t n = 0; n < OSC_TICK_CALLBACK_COUNT; n++) {
		if (host_cb[n].counter != 255) {
			if (!host_cb[n].cb) host_cb[n].counter = 255;
			continue;
		}
		if (host_cb[n].cb) {
			host_cb[n].cb(n, host_cb[n].priv);
			if (n == 0) {
				g_music_ticks++;
				record_music_tick();
			}
		}
		host_cb[n].counter = host_cb[n].preset;
	}
}

static void base_event(void)
{
	int due = 0;
	for (uint8_t n = 0; n < OSC_TICK_CALLBACK_COUNT; n++) {
		host_cb[n].counter--;
		if (host_cb[n].counter == 0xFF) due = 1;
	}
	if (due) host_tick_handler();
	g_base++;
}

int main(int argc, char **argv)
{
	if (argc > 1) g_limit = (uint32_t)strtoul(argv[1], NULL, 10);

	osc_setup();
	atm_synth_setup();
	atm_synth_play_score((const uint8_t *)&score);

	loops_print_header();
	while (g_music_ticks < g_limit) {
		base_event();
		if (host_cb[0].cb == NULL) break; /* original stopped */
	}
	fprintf(stderr, "orig trace: ticks=%u active=%u\n",
		(unsigned)g_music_ticks, host_cb[0].cb ? 1u : 0u);
	return 0;
}
