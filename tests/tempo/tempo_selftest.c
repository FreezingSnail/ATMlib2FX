/*
 * tempo_selftest.c - permanent host checks for the runtime tempo API
 * (ATMlib2FX-y1w): atm_synth_set_tempo(uint8_t tick_rate).
 *
 * Compiles the real library C sources (src/atm_synth.c, which includes
 * src/cmd_parse.c) for the host with an AVR PROGMEM shim, and substitutes only
 * the osc.c timer layer with a stub that reproduces the Timer3 ISR callback
 * scheduling exactly (2000 Hz base = OSC_SAMPLERATE / OSC_ISR_PRESCALER_DIV).
 * This is the same contract used by the reference-trace harness
 * (research/fx/footprint_baseline/trace/trace_main.c), so the emitted "tempo"
 * column is the real atmlib_state.tick_rate the score tick handler sees.
 *
 * Checks:
 *   T1..T3   defaults and pre-score state.
 *   T4..T9   sketch-side set_tempo() clamps 0 -> 1 and applies immediately to
 *            the music callback preset for edge cases 0, 1, 8, 255.
 *   T10..    the trace "tempo" column shows the new rate from the next tick.
 *   T??      effective quantization: callbacks are floor(2000 / rate) base
 *            events apart for 1, 8 and 255 (no hang / no runaway); the SFX
 *            player keeps its own independent rate; the change applies while
 *            the score is paused.
 *
 * Host diagnostic only: contributes no AVR bytes. Run via tests/tempo/run-tests.sh.
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

#define TEMPO_BASE_HZ (OSC_SAMPLERATE / OSC_ISR_PRESCALER_DIV) /* 2000 */

void osc_setup(void)
{
	memset(osc_params_array, 0, sizeof(osc_params_array));
	memset(host_cb, 0, sizeof(host_cb));
}

void osc_set_tick_rate(const uint8_t callback_idx, const uint16_t rate_hz)
{
	/* Exactly osc.c: div is a uint8_t, so the preset wraps for rate_hz < 8. */
	host_cb[callback_idx].preset = (uint8_t)(TEMPO_BASE_HZ / rate_hz - 1);
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

/* ---------------- tick driver (mirrors trace_main.c) ---------------- */
static uint64_t g_base = 0;
static struct atm_sfx_state sfx_state;

#define TRACE_MAX 128
static uint8_t          trace_tempo[TRACE_MAX];
static uint64_t         trace_base[TRACE_MAX];
static unsigned         trace_n = 0;

static void record_music_tick(void)
{
	if (trace_n < TRACE_MAX) {
		trace_tempo[trace_n] = atmlib_state.tick_rate;
		trace_base[trace_n] = g_base;
	}
	trace_n++;
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

/* Drive base events until `want` further music ticks have been recorded.
 * Bounded so a stall (callback never firing) cannot hang the test. */
static int wait_ticks(unsigned want, unsigned long guard)
{
	unsigned start = trace_n;
	while ((trace_n - start) < want && guard > 0) {
		base_event();
		guard--;
	}
	return (int)(trace_n - start);
}

/* ---------------- fixtures ---------------- */

/* One pattern, four channels: sustained activity (a huge delay) so music ticks
 * keep arriving for the whole test. No tempo command, so the default applies. */
#define TEMPO_PATTERN0 {                 \
	ATM_CMD_I_NOTE_C4,               \
	ATM_CMD_M_DELAY_TICKS_2(60000),  \
}
static const uint8_t tempo_pattern0[] = TEMPO_PATTERN0;

const PROGMEM struct tempo_score_data {
	uint8_t fmt;
	uint8_t num_patterns;
	uint16_t patterns_offset[1];
	uint8_t num_channels;
	uint8_t start_patterns[4];
	uint8_t pattern0[sizeof(tempo_pattern0)];
} tempo_score = {
	.fmt = ATM_SCORE_FMT_FULL,
	.num_patterns = 1,
	.patterns_offset = { (uint16_t)offsetof(struct tempo_score_data, pattern0) },
	.num_channels = 4,
	.start_patterns = { 0, 0, 0, 0 },
	.pattern0 = TEMPO_PATTERN0,
};

/* Minimal-mono SFX on its own tempo (40 Hz) with a long delay so it stays
 * active while we poke the music tempo. */
const PROGMEM struct tempo_sfx_data {
	uint8_t fmt;
	uint8_t pattern0[6];
} tempo_sfx = {
	.fmt = ATM_SCORE_FMT_MINIMAL_MONO,
	.pattern0 = {
		ATM_CMD_M_SET_TEMPO(40),
		ATM_CMD_I_NOTE_C4,
		ATM_CMD_M_DELAY_TICKS_2(60000),
	},
};

static int failures = 0;

#define CHECK(cond, msg) do { \
	if (cond) { printf("ok: %s\n", (msg)); } \
	else { printf("FAIL: %s\n", (msg)); failures++; } \
} while (0)

static uint8_t expected_preset(uint16_t rate_hz)
{
	return (uint8_t)(TEMPO_BASE_HZ / rate_hz - 1);
}

/* Assert the trace tempo column reports `want` on the very next music tick. */
static void expect_next_tick_tempo(uint8_t want)
{
	const unsigned start = trace_n;
	const int got = wait_ticks(1, 2000000);
	CHECK(got == 1, "next tick arrives (no hang)");
	if (got == 1) {
		printf("    trace: M,%u,%llu,%u  (expected tempo %u)\n",
		       start + 1, (unsigned long long)trace_base[start],
		       trace_tempo[start], (unsigned)want);
		CHECK(trace_tempo[start] == want, "trace tempo column shows the new rate on the next tick");
	}
}

int main(void)
{
	osc_setup();
	atm_synth_setup();

	/* ---- T1..T3 defaults ------------------------------------------------ */
	CHECK(atmlib_state.tick_rate == 0, "tick_rate is 0 before a score is loaded");

	atm_synth_play_score((const uint8_t *)&tempo_score);
	CHECK(atmlib_state.tick_rate == 25, "play_score() sets the default 25 Hz");
	CHECK(host_cb[0].preset == expected_preset(25),
	      "music callback preset matches the default rate (2000/25-1)");

	/* Baseline tick at the default tempo. */
	CHECK(wait_ticks(1, 100) == 1, "baseline music tick arrives");
	CHECK(trace_tempo[trace_n - 1] == 25, "baseline tick reports 25 Hz");

	/* ---- T4 edge 0 -> 1, applied immediately ---------------------------- */
	atm_synth_set_tempo(0);
	CHECK(atmlib_state.tick_rate == 1, "set_tempo(0) is clamped to 1");
	CHECK(host_cb[0].preset == expected_preset(1) && host_cb[0].preset == 207,
	      "set_tempo(0) applies preset 207 (2000/1-1 truncated to u8) at once");
	expect_next_tick_tempo(1);

	/* ---- T5 edge 1 ------------------------------------------------------ */
	atm_synth_set_tempo(1);
	CHECK(atmlib_state.tick_rate == 1, "set_tempo(1) stores 1");
	CHECK(host_cb[0].preset == 207, "set_tempo(1) applies preset 207");
	expect_next_tick_tempo(1);

	/* ---- T6 edge 8 ------------------------------------------------------ */
	atm_synth_set_tempo(8);
	CHECK(atmlib_state.tick_rate == 8, "set_tempo(8) stores 8");
	CHECK(host_cb[0].preset == 249, "set_tempo(8) applies preset 249 (2000/8-1)");
	expect_next_tick_tempo(8);
	/* Quantization: 250 base events per tick for rate 8. */
	{
		const unsigned start = trace_n;
		CHECK(wait_ticks(2, 2000000) == 2, "rate 8: two ticks arrive (no hang)");
		if (trace_n - start == 2) {
			const uint64_t sp = trace_base[trace_n - 1] - trace_base[trace_n - 2];
			CHECK(sp == 250, "rate 8: callbacks 250 base events apart");
		}
	}

	/* ---- T7 edge 255 ---------------------------------------------------- */
	atm_synth_set_tempo(255);
	CHECK(atmlib_state.tick_rate == 255, "set_tempo(255) stores 255");
	CHECK(host_cb[0].preset == 6, "set_tempo(255) applies preset 6 (2000/255-1)");
	expect_next_tick_tempo(255);
	/* Quantization: floor(2000/255) = 7 base events per tick. */
	{
		const unsigned start = trace_n;
		CHECK(wait_ticks(3, 100000) == 3, "rate 255: ticks arrive (no hang)");
		if (trace_n - start == 3) {
			uint64_t sp = trace_base[trace_n - 1] - trace_base[trace_n - 2];
			CHECK(sp == 7, "rate 255: callbacks 7 base events apart");
			sp = trace_base[trace_n - 2] - trace_base[trace_n - 3];
			CHECK(sp == 7, "rate 255: spacing is stable (no divergence)");
		}
	}

	/* ---- T8 rate 1 quantization + no runaway ---------------------------- */
	atm_synth_set_tempo(1);
	{
		const unsigned start = trace_n;
		CHECK(wait_ticks(2, 2000000) == 2, "rate 1: two ticks arrive (no hang)");
		if (trace_n - start == 2) {
			const uint64_t sp = trace_base[trace_n - 1] - trace_base[trace_n - 2];
			CHECK(sp == 208, "rate 1: callbacks 208 base events apart (quantized)");
		}
	}

	/* ---- T9 applies while paused --------------------------------------- */
	atm_synth_set_score_paused(1);
	CHECK(atm_synth_get_score_paused() == 1, "score is paused");
	{
		const unsigned before = trace_n;
		atm_synth_set_tempo(50);
		CHECK(atmlib_state.tick_rate == 50, "set_tempo(50) while paused stores 50");
		CHECK(host_cb[0].preset == expected_preset(50) && host_cb[0].preset == 39,
		      "set_tempo(50) while paused applies preset 39 at once");
		for (int i = 0; i < 5000; i++) {
			base_event();
		}
		CHECK(trace_n == before, "paused score emits no music ticks");
	}
	atm_synth_set_score_paused(0);
	CHECK(atm_synth_get_score_paused() == 0, "score resumed");
	expect_next_tick_tempo(50);

	/* ---- T10 SFX keeps its own independent rate ------------------------ */
	atm_synth_play_sfx_track(OSC_CH_ONE, (const uint8_t *)&tempo_sfx, &sfx_state);
	/* Fire the SFX once so its handler has re-applied its own rate. */
	{
		const unsigned before = trace_n;
		wait_ticks(1, 2000000); /* let at least one base window pass */
		(void)before;
	}
	CHECK(sfx_state.track_info.tick_rate == 40, "SFX track rate is 40");
	CHECK(host_cb[1].preset == expected_preset(40), "SFX preset matches 40 Hz");
	{
		const uint8_t sfx_preset_before = host_cb[1].preset;
		const uint8_t sfx_rate_before = sfx_state.track_info.tick_rate;
		atm_synth_set_tempo(200);
		CHECK(atmlib_state.tick_rate == 200, "music tempo changed to 200");
		CHECK(host_cb[0].preset == expected_preset(200) && host_cb[0].preset == 9,
		      "music preset updated to 9 while SFX is active");
		CHECK(host_cb[1].preset == sfx_preset_before,
		      "SFX preset untouched by set_tempo()");
		CHECK(sfx_state.track_info.tick_rate == sfx_rate_before,
		      "SFX independent rate untouched by set_tempo()");
	}
	atm_synth_stop_sfx_track(&sfx_state);

	/* ---- trace evidence dump ------------------------------------------- */
	printf("# recorded music ticks (event,tick,base,tempo)\n");
	for (unsigned i = 0; i < trace_n && i < TRACE_MAX; i++) {
		printf("M,%u,%llu,%u\n", i + 1, (unsigned long long)trace_base[i], trace_tempo[i]);
	}

	if (failures) {
		printf("tempo_selftest: %d FAILURES\n", failures);
		return 1;
	}
	printf("tempo_selftest: all checks passed\n");
	return 0;
}
