/*
 * Host equivalence harness for the finite-v1 compact FX stream
 * (ATMlib2FX-3ii.3, stream framing selected by ATMlib2FX-hlh.6).
 *
 * Drives the *device* compact decoder (src/atm_synth.c compiled with
 * ATM_HAS_FX_COMPACT=1, which #includes src/atm_fx_compact.c) on the host and
 * emits the same tick CSV schema as tools/music_authoring/preview/trace_main.c
 * (the original PROGMEM engine trace), so the two runs can be diffed for the
 * same authored score.  The effect/command core is the unmodified library, so
 * the only thing under test is the generated stream, its framing and the refill
 * ring.
 *
 * The osc.c timer layer is substituted exactly as in the PROGMEM trace harness
 * (2000 Hz base, ISR down-counter semantics, floor-quantized tick rates).  This
 * is a host diagnostic build: it contributes no AVR bytes.
 *
 * Usage: compact_trace_main <stream.bin> [music_ticks] [service_every_ticks] [phase]
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#define ATM_HAS_FX_COMPACT (1)
#define ATM_FX_COMPACT_DIAG (1)
#include "atm_synth.c"

/* ------------------------------------------------------------------ */
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
	for (i = 0; i < OSC_CH_COUNT; i++) {
		osc_params_array[i].mod = 0x7F;
	}
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
	if (cb) {
		host_cb[callback_idx].counter = 0;
	}
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

/* ------------------------------------------------------------------ */
static uint8_t *g_stream;
static uint32_t g_stream_len;
static uint32_t g_stream_base = 0; /* simulate a high FX-section address */

void atm_fx_compact_fetch(uint32_t offset, uint8_t *dst, uint8_t n)
{
	for (uint8_t i = 0; i < n; i++) {
		uint32_t o = offset + i;
		if (o < g_stream_base) { dst[i] = 0; continue; }
		o -= g_stream_base;
		dst[i] = o < g_stream_len ? g_stream[o] : 0;
	}
}

static uint32_t g_music_ticks = 0;
static uint32_t g_limit = 512;
static uint32_t g_service_every = 1;
static uint32_t g_service_phase = 0;
static uint32_t g_stop_tick = 0;

static void print_header(void)
{
	printf("tick,channel,tempo,inc,vol,note,delay,cvol,cmod,active\n");
}

static void record_tick(void)
{
	for (uint8_t c = 0; c < OSC_CH_COUNT; c++) {
		printf("%u,%u,%u,0x%04x,%u,%u,0x%04x,%u,%u,0x%02x\n",
			(unsigned)g_music_ticks,
			(unsigned)c,
			(unsigned)atmlib_state.tick_rate,
			(unsigned)osc_params_array[c].phase_increment,
			(unsigned)osc_params_array[c].vol,
			(unsigned)channels[c].note,
			(unsigned)channels[c].delay,
			(unsigned)channels[c].vol,
			(unsigned)channels[c].mod,
			(unsigned)atmlib_state.channel_active_mute);
	}
}

static void host_tick_handler(void)
{
	for (uint8_t n = 0; n < OSC_TICK_CALLBACK_COUNT; n++) {
		if (host_cb[n].counter != 255) {
			if (!host_cb[n].cb) {
				host_cb[n].counter = 255;
			}
			continue;
		}
		if (host_cb[n].cb) {
			host_cb[n].cb(n, host_cb[n].priv);
			if (n == 0) {
				g_music_ticks++;
				record_tick();
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
		if (host_cb[n].counter == 0xFF) {
			due = 1;
		}
	}
	if (due) {
		host_tick_handler();
	}
}

int main(int argc, char **argv)
{
	const char *path = argc > 1 ? argv[1] : "stream.bin";
	if (argc > 2) g_limit = (uint32_t)strtoul(argv[2], NULL, 10);
	if (argc > 3) g_service_every = (uint32_t)strtoul(argv[3], NULL, 10);
	if (argc > 4) g_service_phase = (uint32_t)strtoul(argv[4], NULL, 10);
	if (argc > 5) g_stream_base = (uint32_t)strtoul(argv[5], NULL, 16);
	if (g_service_every == 0) g_service_every = 1;

	FILE *f = fopen(path, "rb");
	if (!f) { perror(path); return 1; }
	fseek(f, 0, SEEK_END);
	long sz = ftell(f);
	fseek(f, 0, SEEK_SET);
	g_stream = malloc((size_t)sz);
	if (!g_stream) { perror("malloc"); return 1; }
	if (fread(g_stream, 1, (size_t)sz, f) != (size_t)sz) { perror("fread"); return 1; }
	fclose(f);
	g_stream_len = (uint32_t)sz;

	memset(&atm_fx_compact_state, 0, sizeof(atm_fx_compact_state));
	osc_setup();
	atm_synth_setup();
	atm_fx_compact_play(g_stream_base, g_stream_len);

	print_header();
	atm_fx_compact_service();
	while (g_music_ticks < g_limit) {
		if (g_music_ticks > 0 &&
		    (g_music_ticks % g_service_every) == g_service_phase) {
			atm_fx_compact_service();
		}
		base_event();
		if (host_cb[0].cb == NULL) {
			break;
		}
	}

	g_stop_tick = atm_fx_compact_state.stop_tick;
	fprintf(stderr, "compact trace: ticks=%u underruns=%u max_gap=%u "
		"max_record=%u max_window=%u error=%u stopped=%u active=%u\n",
		(unsigned)g_music_ticks,
		(unsigned)atm_fx_compact_state.underruns,
		(unsigned)atm_fx_compact_state.max_service_gap,
		(unsigned)atm_fx_compact_state.max_record,
		(unsigned)atm_fx_compact_state.max_window,
		(unsigned)atm_fx_compact_state.error,
		(unsigned)g_stop_tick,
		(unsigned)atm_fx_compact_state.active);
	free(g_stream);
	return 0;
}
