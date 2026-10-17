/*
 * Reference-trace harness for ATMlib2FX-hlh.1.
 *
 * Purpose: produce a deterministic, tick-level record of original ATMlib
 * playback behavior for the research/fx/footprint_baseline fixture, so that a
 * future FX-based decoder can be compared against the original implementation
 * rather than against hand-invented timings.
 *
 * Approach: compile the *unmodified* library C sources (src/atm_synth.c and the
 * src/cmd_parse.c it includes) for the host, substituting only the osc.c timer
 * layer with a stub that reproduces the timer ISR's callback scheduling exactly
 * (2000 Hz base = OSC_SAMPLERATE / OSC_ISR_PRESCALER_DIV). The library's own
 * score parsing, command interpreter, effect implementation and tick handlers
 * run unchanged, so the trace values are the original implementation's values.
 *
 * This is a host diagnostic build. It is never part of a production AVR image
 * and its cost is not part of any footprint number in research/fx/fx-footprint-results.md.
 *
 * Scheduling contract (documented so the trace is reproducible):
 *   - The base timer runs at OSC_SAMPLERATE / OSC_ISR_PRESCALER_DIV = 2000 Hz.
 *   - Each registered tick callback has the same down-counter the ISR uses; a
 *     callback fires when its counter wraps 0 -> 0xFF and is reloaded with
 *     preset = 2000 / requested_rate - 1 (original osc_set_tick_rate math,
 *     including its floor quantization).
 *   - Callback 0 is music, callback 1 is SFX (same order the ISR loops).
 *   - Zero-based music tick index counts completed music callbacks.
 *   - With the sfx mode, the SFX track is started immediately after music tick
 *     index (START_TICK - 1) completes, i.e. at the START_TICK boundary, and
 *     then runs on its own tempo.
 *
 * Output: CSV to stdout. Two event kinds share the column count so a diff is
 * meaningful:
 *   'M' music tick: all four music channels.
 *   'S' SFX tick:   the single SFX channel (music channels are not advanced).
 *
 * Usage: trace_main <music|sfx> [music_ticks] [sfx_start_tick]
 *   trace_main music 512
 *   trace_main sfx   512 64
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "atm_synth.c"   /* includes src/cmd_parse.c; library core, unmodified */

/* ------------------------------------------------------------------ */
/* osc.c timer-layer substitution. Behavior mirrors the real osc.c:    */
/* osc_reset() seeds mod=0x7F and the OSC3 LFSR, osc_set_tick_rate()    */
/* computes the ISR prescaler, osc_set_tick_callback() arms ASAP.       */

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
	/* osc_reset() equivalent: no timer registers on host. */
	uint8_t i;
	memset(osc_params_array, 0, sizeof(osc_params_array));
	memset(host_cb, 0, sizeof(host_cb));
	for (i = 0; i < OSC_CH_COUNT; i++) {
		osc_params_array[i].mod = 0x7F;
	}
	osc_params_array[OSC_CH_THREE].phase_increment = 0x0001; /* seed LFSR */
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
		host_cb[callback_idx].counter = 0; /* trigger callback ASAP */
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
/* Trace fixtures and state.                                           */

#include "song.h"

static struct atm_sfx_state sfx_state;

static uint64_t g_base = 0;        /* base timer events elapsed            */
static uint32_t g_music_ticks = 0; /* completed music callbacks            */
static uint32_t g_sfx_ticks = 0;   /* completed SFX callbacks              */
static uint32_t g_limit = 512;     /* stop after this many music ticks     */
static uint32_t g_sfx_at = 64;     /* start SFX after this many music ticks*/
static int g_with_sfx = 0;
static int g_sfx_started = 0;

static const uint8_t kSfxChannel = OSC_CH_TWO;

/* One channel's observable state. Order is fixed and documented. */
static void print_channel_fields(const struct osc_params *osc, const struct atm_channel_state *ch)
{
	printf(",0x%04x,%u,%u,%u,%u,%u,0x%04x,%u",
		(unsigned)osc->phase_increment, (unsigned)osc->mod, (unsigned)osc->vol,
		(unsigned)ch->note, (unsigned)ch->vol, (unsigned)ch->mod,
		(unsigned)ch->delay, (unsigned)ch->pstack_index);
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
	printf(",%u", (unsigned)ch->loop_pattern_index);
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

static void record_sfx_tick(void)
{
	const uint8_t c = kSfxChannel;
	printf("S,%u,%llu,%u,0x%02x",
		(unsigned)g_sfx_ticks, (unsigned long long)g_base,
		(unsigned)sfx_state.track_info.tick_rate,
		(unsigned)sfx_state.track_info.channel_active_mute);
	print_channel_fields(&osc_params_array[c], &sfx_state.channel_state);
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
				if (g_with_sfx && !g_sfx_started && g_music_ticks == g_sfx_at) {
					atm_synth_play_sfx_track(kSfxChannel, (const uint8_t *)&sfx1, &sfx_state);
					g_sfx_started = 1;
				}
			} else {
				g_sfx_ticks++;
				record_sfx_tick();
			}
		}
		host_cb[n].counter = host_cb[n].preset;
	}
}

/* Reproduces the decrement-both-counters / fire-if-any-wrapped logic of the
   real Timer3 ISR before it calls osc_tick_handler(). */
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
	const char *mode = argc > 1 ? argv[1] : "music";
	if (argc > 2) g_limit = (uint32_t)strtoul(argv[2], NULL, 10);
	if (argc > 3) g_sfx_at = (uint32_t)strtoul(argv[3], NULL, 10);
	g_with_sfx = strcmp(mode, "sfx") == 0;

	memset(&sfx_state, 0, sizeof(sfx_state));
	osc_setup();
	atm_synth_setup();
	atm_synth_play_score((const uint8_t *)&score);

	print_header();
	while (g_music_ticks < g_limit) {
		base_event();
	}
	return 0;
}
