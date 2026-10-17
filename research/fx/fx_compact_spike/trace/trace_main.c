/*
 * Reference-trace harness for the compact directly-consumed FX stream
 * (ATMlib2FX-hlh.5).
 *
 * Purpose: drive the *device* compact decoder (src/atm_synth.c compiled with
 * ATM_HAS_FX_COMPACT=1, which #includes src/atm_fx_compact.c) on the host and
 * emit the same tick-level CSV schema as the original reference trace, so the
 * two can be diffed. The effect/command core is the unmodified library code, so
 * the only thing under test is the compact stream + framing + refill ring.
 *
 * The byte source is a host array loaded from the converter's .bin output; the
 * osc.c timer layer is substituted exactly as in the baseline trace harness
 * (2000 Hz base, ISR down-counter semantics, floor-quantized tick rates).
 *
 * This is a host diagnostic build. It contributes no AVR bytes and is not part
 * of any footprint number.
 *
 * Usage: trace_main <stream.bin> [music_ticks] [service_every_ticks]
 *   music_ticks          stop after this many music ticks (default 512)
 *   service_every_ticks  call service() only every N music ticks (default 1).
 *                        The ring must hold the whole N-tick window.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

/* Compile the library core as the compact FX stream build. */
#define ATM_HAS_FX_COMPACT (1)
#define ATM_FX_COMPACT_DIAG (1)
#include "atm_synth.c"

/* ------------------------------------------------------------------ */
/* osc.c timer-layer substitution (same contract as the baseline trace). */
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
/* FX byte source: a host array holding the generated stream.          */
static uint8_t *g_stream;
static uint32_t g_stream_len;

void atm_fx_compact_fetch(uint32_t offset, uint8_t *dst, uint8_t n)
{
	for (uint8_t i = 0; i < n; i++) {
		uint32_t o = offset + i;
		dst[i] = o < g_stream_len ? g_stream[o] : 0;
	}
}

/* ------------------------------------------------------------------ */
static uint64_t g_base = 0;
static uint32_t g_music_ticks = 0;
static uint32_t g_limit = 512;
static uint32_t g_service_every = 1;
static uint32_t g_service_phase = 0;

static void print_channel_fields(const struct osc_params *osc, const struct atm_channel_state *ch)
{
	printf(",0x%04x,%u,%u,%u,%u,%u,0x%04x,%u",
		(unsigned)osc->phase_increment, (unsigned)osc->mod, (unsigned)osc->vol,
		(unsigned)ch->note, (unsigned)ch->vol, (unsigned)ch->mod,
		(unsigned)ch->delay, 0u /* ps: traversal state removed in this build */);
#if ATM_HAS_FX_SLIDE
	printf(",%d,%u,%u", (int)ch->vf_slide.slide_amount,
		(unsigned)ch->vf_slide.slide_config, (unsigned)ch->vf_slide.slide_count);
#else
	printf(",-,-,-");
#endif
#if ATM_HAS_FX_NOTE_RETRIG
	printf(",%u,%u,%u", (unsigned)ch->arpNotes, (unsigned)ch->arpTiming, (unsigned)ch->arpCount);
#else
	printf(",-,-,-");
#endif
#if ATM_HAS_FX_NOISE_RETRIG
	printf(",%u,%u", (unsigned)ch->reConfig, (unsigned)ch->reCount);
#else
	printf(",-,-");
#endif
#if ATM_HAS_FX_LFO
	printf(",%u,%u,%u", (unsigned)ch->treviDepth, (unsigned)ch->treviConfig, (unsigned)ch->treviCount);
#else
	printf(",-,-,-");
#endif
#if ATM_HAS_FX_GLISSANDO
	printf(",%d,%u", (int)ch->glisConfig, (unsigned)ch->glisCount);
#else
	printf(",-,-");
#endif
#if ATM_HAS_FX_LOOP
	printf(",255"); /* loop_pattern_index: the fixture issues no loop command */
#else
	printf(",-");
#endif
}

static void record_music_tick(void)
{
	printf("M,%u,%llu,%u,0x%02x",
		(unsigned)g_music_ticks, (unsigned long long)g_base,
		(unsigned)atmlib_state.tick_rate, (unsigned)atmlib_state.channel_active_mute);
	for (uint8_t c = 0; c < OSC_CH_COUNT; c++) {
		print_channel_fields(&osc_params_array[c], &channels[c]);
	}
	printf("\n");
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
		if (host_cb[n].counter == 0xFF) {
			due = 1;
		}
	}
	if (due) {
		host_tick_handler();
	}
	g_base++;
}

static void print_header(void)
{
	printf("event,tick,base,tempo,active");
	for (uint8_t c = 0; c < OSC_CH_COUNT; c++) {
		printf(",c%u_inc,c%u_mod,c%u_vol,c%u_note,c%u_cvol,c%u_cmod,c%u_delay,c%u_ps"
		       ",c%u_sla,c%u_slc,c%u_slk,c%u_arp,c%u_art,c%u_arc,c%u_rec,c%u_recn"
		       ",c%u_trd,c%u_trt,c%u_trc,c%u_glc,c%u_glk,c%u_lp",
			c,c,c,c,c,c,c,c,c,c,c,c,c,c,c,c,c,c,c,c,c,c);
	}
	printf("\n");
}

int main(int argc, char **argv)
{
	const char *path = argc > 1 ? argv[1] : "build/fx-port/compact/compact_stream.bin";
	if (argc > 2) g_limit = (uint32_t)strtoul(argv[2], NULL, 10);
	if (argc > 3) g_service_every = (uint32_t)strtoul(argv[3], NULL, 10);
	if (argc > 4) g_service_phase = (uint32_t)strtoul(argv[4], NULL, 10);
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
	atm_fx_compact_play(0, g_stream_len);

	print_header();
	atm_fx_compact_service();
	while (g_music_ticks < g_limit) {
		if (g_music_ticks > 0 &&
		    (g_music_ticks % g_service_every) == g_service_phase) {
			atm_fx_compact_service();
		}
		base_event();
		if (host_cb[0].cb == NULL) {
			fprintf(stderr, "compact trace: player stopped after %u ticks\n",
				g_music_ticks);
			break;
		}
		if (g_base > 100000000ull) {
			fprintf(stderr, "compact trace: base-event cap hit after %u ticks\n",
				g_music_ticks);
			break;
		}
	}

	fprintf(stderr, "compact trace: ticks=%u underruns=%u max_gap=%u "
		"max_record=%u max_window=%u error=%u stopped=%u active=%u\n",
		(unsigned)atm_fx_compact_state.ticks,
		(unsigned)atm_fx_compact_state.underruns,
		(unsigned)atm_fx_compact_state.max_service_gap,
		(unsigned)atm_fx_compact_state.max_record,
		(unsigned)atm_fx_compact_state.max_window,
		(unsigned)atm_fx_compact_state.error,
		(unsigned)atm_fx_compact_state.stop_tick,
		(unsigned)atm_fx_compact_state.active);
	free(g_stream);
	return 0;
}
