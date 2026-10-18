/*
 * compact_trace.c - compact loop-decoder host trace (ATMlib2FX-hlh.8).
 *
 * Compiles the device decoder (src/atm_synth.c with ATM_HAS_FX_COMPACT=1 and
 * ATM_FX_COMPACT_LOOP=1) on the host, feeds it a converted compact stream from
 * a file, and emits the same tick CSV schema as orig_trace.c / the hlh.1
 * reference trace. Timer substitution is identical to the original harness, so
 * a normalized diff isolates the decoder.
 *
 * Usage: compact_trace <stream.bin> <music_ticks> [service_every]
 * Host diagnostic build; contributes no AVR bytes.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#ifndef ATM_FX_COMPACT_RING
#define ATM_FX_COMPACT_RING (32)
#endif

#define ATM_HAS_FX_COMPACT (1)
#define ATM_FX_COMPACT_LOOP (1)
#define ATM_FX_COMPACT_DIAG (1)
#include "atm_synth.c"

/* ---- osc.c timer-layer substitution ---- */
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

#include "loops_trace_common.h"

/* ---- FX byte source: a host array holding the converted stream ---- */
static uint8_t *g_stream;
static uint32_t g_stream_len;

void atm_fx_compact_fetch(uint32_t offset, uint8_t *dst, uint8_t n)
{
	for (uint8_t i = 0; i < n; i++) {
		uint32_t o = offset + i;
		dst[i] = o < g_stream_len ? g_stream[o] : 0;
	}
}

static uint64_t g_base = 0;
static uint32_t g_music_ticks = 0;
static uint32_t g_limit = 64;
static uint32_t g_service_every = 1;

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
	const char *path;
	if (argc < 3) {
		fprintf(stderr,
			"usage: compact_trace <stream.bin> <ticks> [service_every]\n");
		return 2;
	}
	path = argv[1];
	g_limit = (uint32_t)strtoul(argv[2], NULL, 10);
	if (argc > 3) g_service_every = (uint32_t)strtoul(argv[3], NULL, 10);
	if (g_service_every == 0) g_service_every = 1;

	FILE *f = fopen(path, "rb");
	if (!f) { perror(path); return 1; }
	fseek(f, 0, SEEK_END);
	long sz = ftell(f);
	fseek(f, 0, SEEK_SET);
	g_stream = malloc((size_t)sz ? (size_t)sz : 1);
	if (!g_stream) { perror("malloc"); return 1; }
	if (fread(g_stream, 1, (size_t)sz, f) != (size_t)sz) { perror("fread"); return 1; }
	fclose(f);
	g_stream_len = (uint32_t)sz;

	memset(&atm_fx_compact_state, 0, sizeof(atm_fx_compact_state));
	osc_setup();
	atm_synth_setup();
	atm_fx_compact_play(0, g_stream_len);

	loops_print_header();
	atm_fx_compact_service();
	while (g_music_ticks < g_limit) {
		if (g_music_ticks > 0 &&
		    (g_music_ticks % g_service_every) == 0)
			atm_fx_compact_service();
		base_event();
		if (host_cb[0].cb == NULL) break; /* stopped (should not happen) */
		if (g_base > 200000000ull) break;
	}

	fprintf(stderr,
		"compact trace: ticks=%u underruns=%u error=%u active=%u "
		"record_max=%u window_max=%u service_gap=%u\n",
		(unsigned)atm_fx_compact_state.ticks,
		(unsigned)atm_fx_compact_state.underruns,
		(unsigned)atm_fx_compact_state.error,
		(unsigned)atm_fx_compact_state.active,
		(unsigned)atm_fx_compact_state.max_record,
		(unsigned)atm_fx_compact_state.max_window,
		(unsigned)atm_fx_compact_state.max_service_gap);
	free(g_stream);
	return 0;
}
