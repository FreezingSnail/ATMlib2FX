/*
 * fx_loop_selftest.c - permanent host checks for the loop-capable compact FX
 * stream (ATMlib2FX-hlh.8).
 *
 * Compiled and run by tests/fx_pack/run-tests.sh. Covers:
 *   - encoder loop admission: zero-time cycle rejection, loop period not
 *     detected within the tick cap, SET_LOOP_PATTERN operand bounds (out of
 *     range and the reserved 255), loop region larger than the ring;
 *   - loop stream validation: header extent, record-boundary loop_start,
 *     truncation, ring limit, all-gap-0 loop-region rejection, and an accepted
 *     well-formed loop stream;
 *   - device decoder: a hand-built intro/loop stream restarts its channels at
 *     the loop boundary (bitmap restart mask), replays with zero underruns,
 *     rejects a malformed loop header, and bounds the same-tick wrap chain on
 *     an all-gap-0 region instead of hanging.
 *
 * The device decoder is compiled here with ATM_FX_COMPACT_LOOP=1 (the finite
 * selftest, fx_pack_selftest.c, is compiled without it). Contributes no AVR
 * bytes.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef ATM_FX_COMPACT_RING
#define ATM_FX_COMPACT_RING (32)
#endif

#define ATM_HAS_FX_COMPACT (1)
#define ATM_FX_COMPACT_LOOP (1)
#define ATM_FX_COMPACT_DIAG (1)
#include "atm_synth.c"

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
	uint8_t i;
	memset(osc_params_array, 0, sizeof(osc_params_array));
	memset(host_cb, 0, sizeof(host_cb));
	for (i = 0; i < OSC_CH_COUNT; i++) osc_params_array[i].mod = 0x7F;
	osc_params_array[OSC_CH_THREE].phase_increment = 0x0001;
}
void osc_set_tick_rate(const uint8_t i, const uint16_t r)
{
	host_cb[i].preset = (uint8_t)((OSC_SAMPLERATE / OSC_ISR_PRESCALER_DIV) / r - 1);
}
void osc_set_tick_callback(const uint8_t i, const osc_tick_callback cb, const void *priv)
{
	host_cb[i].cb = cb;
	host_cb[i].priv = (void *)priv;
	if (cb) host_cb[i].counter = 0;
}
void osc_get_tick_callback(const uint8_t i, osc_tick_callback *cb, void **priv)
{
	if (cb) *cb = host_cb[i].cb;
	if (priv) *priv = host_cb[i].priv;
}

#include "fx_encode.h"
#include "fx_score.h"

static uint8_t g_buf[4096];
static size_t g_buflen;

void atm_fx_compact_fetch(uint32_t offset, uint8_t *dst, uint8_t n)
{
	for (uint8_t i = 0; i < n; i++) {
		uint32_t o = offset + i;
		dst[i] = o < g_buflen ? g_buf[o] : 0;
	}
}

static int g_fail;
static void check(const char *what, int cond)
{
	if (!cond) {
		fprintf(stderr, "FAIL: %s\n", what);
		g_fail = 1;
	} else {
		printf("ok: %s\n", what);
	}
}

/* ---------------- synthetic modern score builder ---------------- */
static void make_score(struct fx_score *s, const uint8_t *const *pats,
		       const size_t *sizes, int np, const uint8_t entries[4])
{
	size_t h = (size_t)7 + 2 * (size_t)np;
	size_t pos = h, total = h;

	memset(s, 0, sizeof(*s));
	for (int i = 0; i < np; i++) total += sizes[i];
	s->bytes = calloc(total ? total : 1, 1);
	s->pattern_offset = malloc(sizeof(uint32_t) * (size_t)np);
	if (!s->bytes || !s->pattern_offset) { perror("malloc"); exit(1); }
	s->bytes[0] = 0x03;
	s->bytes[1] = (uint8_t)np;
	for (int i = 0; i < np; i++) {
		s->pattern_offset[i] = (uint32_t)pos;
		s->bytes[2 + 2 * i] = (uint8_t)(pos & 0xFF);
		s->bytes[3 + 2 * i] = (uint8_t)((pos >> 8) & 0xFF);
		memcpy(s->bytes + pos, pats[i], sizes[i]);
		pos += sizes[i];
	}
	s->bytes[2 + 2 * np] = 4;
	for (int ch = 0; ch < 4; ch++)
		s->bytes[3 + 2 * np + ch] = entries[ch];
	s->len = total;
	s->num_patterns = (uint8_t)np;
	s->num_channels = 4;
	for (int ch = 0; ch < 4; ch++) s->entry[ch] = entries[ch];
	snprintf(s->format_name, sizeof(s->format_name), "synthetic");
	s->source_len = total;
}

static int encode_loop(const struct fx_score *s, uint16_t ring, uint32_t ticks,
		       struct fx_encode_result *res)
{
	struct fx_score_patterns view = fx_score_view(s);
	struct fx_encode_options opt;

	memset(&opt, 0, sizeof(opt));
	opt.ring = ring;
	opt.tick_cap = ticks;
	opt.allow_loops = 1;
	memset(res, 0, sizeof(*res));
	return fx_encode(&view, &opt, res);
}

/* ================================================================== */
/* encoder loop admission                                             */

static void test_zero_time_cycle(void)
{
	/* Loop target pattern is just STOP: the restart stops again in the same
	 * tick, so the original would spin forever. Rejected. */
	static const uint8_t p0[] = { 0x80, 0x01, 0x61 }; /* loop->1, stop */
	static const uint8_t p1[] = { 0x61 };
	const uint8_t *pats[] = { p0, p1 };
	const size_t sizes[] = { sizeof(p0), sizeof(p1) };
	const uint8_t entries[4] = { 0, 0, 0, 0 };
	struct fx_score s;
	struct fx_encode_result res;

	make_score(&s, pats, sizes, 2, entries);
	check("zero-time loop cycle is rejected",
	      encode_loop(&s, 32, 100, &res) != 0 &&
	      strstr(res.error, "zero-time loop cycle") != NULL);
	fx_encode_result_free(&res);
	fx_score_free(&s);
}

static void test_traversal_cycle_cap(void)
{
	/* Long loop period, tiny tick cap: the cycle is never observed. */
	static const uint8_t p0[] = { 12, 0x80, 0x01, 0x55, 0x61 };
	static const uint8_t p1[] = { 13, 0x55, 0x61 };
	const uint8_t *pats[] = { p0, p1 };
	const size_t sizes[] = { sizeof(p0), sizeof(p1) };
	const uint8_t entries[4] = { 0, 0, 0, 0 };
	struct fx_score s;
	struct fx_encode_result res;

	make_score(&s, pats, sizes, 2, entries);
	check("loop period not detected within the tick cap is rejected",
	      encode_loop(&s, 32, 10, &res) != 0 &&
	      strstr(res.error, "traversal-cycle") != NULL);
	fx_encode_result_free(&res);
	fx_score_free(&s);
}

static void test_operand_bounds(void)
{
	const uint8_t entries[4] = { 0, 0, 0, 0 };
	struct fx_score s;
	struct fx_encode_result res;

	/* target pattern out of range */
	{
		static const uint8_t p[] = { 0x80, 0x09, 0x61 };
		const uint8_t *pats[] = { p };
		const size_t sizes[] = { sizeof(p) };
		make_score(&s, pats, sizes, 1, entries);
		check("SET_LOOP_PATTERN target out of range is rejected",
		      encode_loop(&s, 32, 100, &res) != 0 &&
		      strstr(res.error, "out of range") != NULL);
		fx_encode_result_free(&res);
		fx_score_free(&s);
	}
	/* reserved 255 no-loop marker */
	{
		static const uint8_t p[] = { 0x80, 0xFF, 0x61 };
		const uint8_t *pats[] = { p };
		const size_t sizes[] = { sizeof(p) };
		make_score(&s, pats, sizes, 1, entries);
		check("SET_LOOP_PATTERN target 255 (reserved) is rejected",
		      encode_loop(&s, 32, 100, &res) != 0 &&
		      strstr(res.error, "255") != NULL);
		fx_encode_result_free(&res);
		fx_score_free(&s);
	}
	/* finite mode still rejects SET_LOOP_PATTERN */
	{
		struct fx_score_patterns view;
		struct fx_encode_options opt;
		static const uint8_t p[] = { 0x80, 0x00, 0x61 };
		const uint8_t *pats[] = { p };
		const size_t sizes[] = { sizeof(p) };
		make_score(&s, pats, sizes, 1, entries);
		view = fx_score_view(&s);
		memset(&opt, 0, sizeof(opt));
		opt.ring = 32;
		opt.tick_cap = 100;
		check("finite mode still rejects SET_LOOP_PATTERN",
		      fx_encode(&view, &opt, &res) != 0 &&
		      strstr(res.error, "finite v1") != NULL);
		fx_encode_result_free(&res);
		fx_score_free(&s);
	}
}

static void test_loop_region_ring(void)
{
	/* One looping channel whose loop region spans three records (15 bytes)
	 * and so exceeds a 12-byte ring, while each record fits. */
	static const uint8_t p0[] = { 0x80, 0x01, 12, 0x41, 0x61 };
	static const uint8_t p1[] = { 13, 0x41, 14, 0x41, 0x61 };
	static const uint8_t p2[] = { 0x61 };
	const uint8_t *pats[] = { p0, p1, p2 };
	const size_t sizes[] = { sizeof(p0), sizeof(p1), sizeof(p2) };
	const uint8_t entries[4] = { 0, 2, 2, 2 };
	struct fx_score s;
	struct fx_encode_result res;

	make_score(&s, pats, sizes, 3, entries);
	check("loop region larger than the ring is rejected",
	      encode_loop(&s, 12, 100, &res) != 0 &&
	      strstr(res.error, "loop region") != NULL);
	fx_encode_result_free(&res);
	fx_score_free(&s);
}

static void test_loop_conversion(void)
{
	/* Two channels: intro then a two-tick loop. The stream must be 0xC1,
	 * validate, carry a non-zero restart mask, and be deterministic. */
	static const uint8_t p0[] = { 0x80, 0x01, 12, 0x44, 0x61 };
	static const uint8_t p1[] = { 13, 0x41, 0x61 };
	const uint8_t *pats[] = { p0, p1 };
	const size_t sizes[] = { sizeof(p0), sizeof(p1) };
	const uint8_t entries[4] = { 0, 0, 0, 0 };
	struct fx_score s;
	struct fx_encode_result res, r2;
	char err[256];
	int same = 0;

	make_score(&s, pats, sizes, 2, entries);
	check("loop score converts to a 0xC1 stream",
	      encode_loop(&s, 32, 200, &res) == 0 &&
	      res.meta.has_loop == 1 && res.stream_len >= 6 &&
	      res.stream[0] == 0xC1);
	check("loop stream validates",
	      fx_stream_validate(res.stream, res.stream_len, 32,
				 err, sizeof(err)) == 0);
	check("loop metadata reports intro and cycle extents",
	      res.meta.loop_start_offset > 0 &&
	      res.meta.cycle_ticks > 0 && res.meta.loop_passes >= 1);
	if (encode_loop(&s, 32, 200, &r2) == 0) {
		same = (r2.stream_len == res.stream_len &&
			memcmp(r2.stream, res.stream, res.stream_len) == 0);
		fx_encode_result_free(&r2);
	}
	check("loop conversion is deterministic", same);
	fx_encode_result_free(&res);
	fx_score_free(&s);
}

/* ================================================================== */
/* loop stream validation                                             */

static void test_loop_validator(void)
{
	char err[256];

	/* minimal well-formed: header(4) + effect-only record(gap1,bitmap0)
	 * + END. loop_start_rel = 4. */
	{
		static const uint8_t good[] = { 0xC1, 0x04, 0x00, 0x00,
						0x03, 0x01, 0x00, 0x00 };
		check("validator accepts a well-formed loop stream",
		      fx_stream_validate(good, sizeof(good), 32,
					 err, sizeof(err)) == 0);
	}
	/* loop_start_rel below the header */
	{
		static const uint8_t bad[] = { 0xC1, 0x02, 0x00, 0x00,
					       0x03, 0x00, 0x00, 0x00 };
		check("validator rejects loop_start_rel below the header",
		      fx_stream_validate(bad, sizeof(bad), 32,
					 err, sizeof(err)) != 0 &&
		      strstr(err, "loop_start_rel") != NULL);
	}
	/* loop_start_rel not on a record boundary (mid-record) */
	{
		static const uint8_t bad[] = {
			0xC1, 0x06, 0x00, 0x00,
			0x05, 0x00, 0x01, 0x01, 12,
			0x00
		};
		check("validator rejects a loop_start_rel inside a record",
		      fx_stream_validate(bad, sizeof(bad), 32,
					 err, sizeof(err)) != 0 &&
		      strstr(err, "record boundary") != NULL);
	}
	/* loop region larger than the ring */
	{
		static const uint8_t bad[] = {
			0xC1, 0x04, 0x00, 0x00,
			0x06, 0x00, 0x01, 0x02, 12, 13,
			0x00
		};
		check("validator rejects a loop region larger than the ring",
		      fx_stream_validate(bad, sizeof(bad), 5,
					 err, sizeof(err)) != 0 &&
		      strstr(err, "loop region") != NULL);
	}
	/* truncated record */
	{
		static const uint8_t bad[] = { 0xC1, 0x04, 0x00, 0x00,
					       0x09, 0x00, 0x01 };
		check("validator rejects a truncated loop record",
		      fx_stream_validate(bad, sizeof(bad), 32,
					 err, sizeof(err)) != 0);
	}
	/* all-gap-0 loop region: replay would never yield a tick */
	{
		static const uint8_t bad[] = {
			0xC1, 0x04, 0x00, 0x00,
			0x05, 0x00, 0x01, 0x01, 0x0C,
			0x05, 0x00, 0x01, 0x01, 0x0D,
			0x00
		};
		check("validator rejects an all-gap-0 loop region",
		      fx_stream_validate(bad, sizeof(bad), 32,
					 err, sizeof(err)) != 0 &&
		      strstr(err, "non-zero gap") != NULL);
	}
}

/* ================================================================== */
/* device decoder                                                     */

static void reset_stream(void)
{
	g_buflen = 0;
	memset(&atm_fx_compact_state, 0, sizeof(atm_fx_compact_state));
	osc_setup();
	atm_synth_setup();
}

static void putb(uint8_t b) { if (g_buflen < sizeof(g_buf)) g_buf[g_buflen++] = b; }

static void run_decoder(int max_ticks)
{
	atm_fx_compact_play(0, (uint32_t)g_buflen);
	for (int i = 0; i < max_ticks; i++) {
		if (host_cb[0].cb == NULL) break;
		atm_fx_compact_service();
		if (host_cb[0].cb == NULL) break;
		host_cb[0].cb(0, host_cb[0].priv);
	}
}

/* Intro: ch0 note 12 at tick 0, then the loop. Loop region (offset 9):
 *   record A (tick 2): ch0 STOP + restart mask 1, gap 0
 *   record B (tick 2): ch0 note 13, gap 2
 * END. Replaying A/B re-arms ch0 and repeats note 13 forever. */
static void test_decoder_loop_restart(void)
{
	reset_stream();
	putb(0xC1);
	putb(0x09); putb(0x00); putb(0x00);        /* loop_start_rel = 9 */
	/* intro record (tick 0): len 5, gap 2, bitmap 1, glen 1, note 12 */
	putb(0x05); putb(0x02); putb(0x01); putb(0x01); putb(12);
	/* loop record A: len 5, gap 0, bitmap 0x11 (ch0 + restart mask 1) */
	putb(0x05); putb(0x00); putb(0x11); putb(0x01); putb(0x61);
	/* loop record B: len 5, gap 2, bitmap 1, glen 1, note 13 */
	putb(0x05); putb(0x02); putb(0x01); putb(0x01); putb(13);
	putb(0x00); /* END */

	run_decoder(12);
	check("loop decoder replays the loop region (note 13, no error)",
	      atm_fx_compact_state.error == 0 &&
	      atm_fx_compact_state.underruns == 0 &&
	      atm_fx_compact_state.active == 1 &&
	      channels[0].note == 13);
	check("loop decoder re-arms the looping channel at the restart",
	      (atmlib_state.channel_active_mute & 0xF0) != 0 &&
	      (atmlib_state.channel_active_mute & (1u << OSC_CH_COUNT)) != 0);
}

/* Streaming loop fixture (ATMlib2FX-hlh.16): a loop region larger than the
 * 32-byte ring. Intro record at tick 0, then a 38-byte loop region:
 *   A: ch0 STOP + restart mask 1, gap 0   (all-stopped sync, same tick)
 *   B: ch0 note 13, gap 1
 *   C: ch0 11 one-byte notes, gap 1
 *   D: ch0 9 one-byte notes, gap 1
 * loop_start_rel = 9. The region does not fit the ring, so the decoder must
 * stream it (re-fetching at the wrap) rather than pin it. */
static void build_streaming_loop(void)
{
	reset_stream();
	putb(0xC1);
	putb(0x09); putb(0x00); putb(0x00);        /* loop_start_rel = 9 */
	/* intro record (tick 0): len 5, gap 2, bitmap 1, glen 1, note 12 */
	putb(0x05); putb(0x02); putb(0x01); putb(0x01); putb(12);
	/* A: len 5, gap 0, bitmap 0x11 (ch0 + restart mask 1), STOP */
	putb(0x05); putb(0x00); putb(0x11); putb(0x01); putb(0x61);
	/* B: len 5, gap 1, bitmap 1, glen 1, note 13 */
	putb(0x05); putb(0x01); putb(0x01); putb(0x01); putb(13);
	/* C: len 15, gap 1, bitmap 1, glen 11 one-byte notes */
	putb(0x0F); putb(0x01); putb(0x01); putb(0x0B);
	for (uint8_t i = 0; i < 11; i++) putb((uint8_t)(20 + i));
	/* D: len 13, gap 1, bitmap 1, glen 9 one-byte notes */
	putb(0x0D); putb(0x01); putb(0x01); putb(0x09);
	for (uint8_t i = 0; i < 9; i++) putb((uint8_t)(40 + i));
	putb(0x00); /* END */
}

static void test_decoder_streaming_loop(void)
{
	build_streaming_loop();
	run_decoder(40);
	check("streaming loop (region > ring) replays with no error/underrun",
	      atm_fx_compact_state.error == 0 &&
	      atm_fx_compact_state.underruns == 0 &&
	      atm_fx_compact_state.active == 1);
	check("streaming loop keeps looping (ticks advanced past one cycle)",
	      atm_fx_compact_state.ticks > 12);
	check("streaming loop re-arms the looping channel at the restart",
	      (atmlib_state.channel_active_mute & (1u << OSC_CH_COUNT)) != 0);
}

/* An unprefillable wrap must surface as an underrun: prefill once (play) then
 * starve the foreground service. The consumer stops when the record at the loop
 * boundary is not resident; it must not skip a tick or garble the loop (error
 * stays 0 and the player stays active). */
static void test_decoder_streaming_underrun(void)
{
	build_streaming_loop();
	atm_fx_compact_play(0, (uint32_t)g_buflen); /* prefill + arm */
	for (int i = 0; i < 40; i++) {
		if (host_cb[0].cb == NULL) break;
		host_cb[0].cb(0, host_cb[0].priv); /* tick, but never service */
	}
	check("unprefillable streaming wrap reports an underrun, no error",
	      atm_fx_compact_state.underruns > 0 &&
	      atm_fx_compact_state.error == 0 &&
	      atm_fx_compact_state.active == 1);
}

/* A 0xC1 header whose loop_start_rel points past the stream is malformed. */
static void test_decoder_loop_reject(void)
{
	reset_stream();
	putb(0xC1);
	putb(0xF0); putb(0x00); putb(0x00); /* loop_start_rel = 240 */
	putb(0x05); putb(0x00); putb(0x01); putb(0x01); putb(12);
	putb(0x00);
	atm_fx_compact_play(0, (uint32_t)g_buflen);
	check("loop decoder rejects an out-of-range loop header",
	      atm_fx_compact_state.error != 0 &&
	      atm_fx_compact_state.active == 0);
}

/* A loop region beyond ATM_FX_COMPACT_LOOP_MAX_REGION (0xFFFF) is a clean
 * rejection: the u24 header can address it, but the streamed region counter
 * cannot, so it must not be replayed partially or garbled. */
static void test_decoder_loop_region_bound(void)
{
	reset_stream();
	putb(0xC1);
	putb(0x04); putb(0x00); putb(0x00); /* loop_start_rel = 4 */
	putb(0x05); putb(0x00); putb(0x01); putb(0x01); putb(12);
	/* Claim a huge stream length so region = length-1-4 > 0xFFFF. The
	 * trailing bytes read as zero past the buffer; only the header matters. */
	atm_fx_compact_play(0, 0x20002u);
	check("loop decoder rejects a region above the streaming bound",
	      atm_fx_compact_state.error != 0 &&
	      atm_fx_compact_state.active == 0);
}

/* Crafted all-gap-0 loop region (rejected by fx_stream_validate): fed
 * directly to the decoder it must hit the same-tick wrap bound, set the
 * sticky format error and stop - never spin inside one tick. */
static void test_decoder_all_gap_zero(void)
{
	reset_stream();
	putb(0xC1);
	putb(0x04); putb(0x00); putb(0x00); /* loop_start_rel = 4 */
	putb(0x05); putb(0x00); putb(0x01); putb(0x01); putb(0x0C);
	putb(0x05); putb(0x00); putb(0x01); putb(0x01); putb(0x0D);
	putb(0x00); /* END */
	run_decoder(12);
	check("decoder bounds an all-gap-0 same-tick chain (error, stop, no hang)",
	      atm_fx_compact_state.error == 1 &&
	      atm_fx_compact_state.active == 0);
}

int main(void)
{
	printf("== fx loop selftest (ATMlib2FX-hlh.8) ==\n");
	test_zero_time_cycle();
	test_traversal_cycle_cap();
	test_operand_bounds();
	test_loop_region_ring();
	test_loop_conversion();
	test_loop_validator();
	test_decoder_loop_restart();
	test_decoder_streaming_loop();
	test_decoder_streaming_underrun();
	test_decoder_loop_reject();
	test_decoder_loop_region_bound();
	test_decoder_all_gap_zero();

	if (g_fail) {
		fprintf(stderr, "fx_loop_selftest: FAILED\n");
		return 1;
	}
	printf("fx_loop_selftest: all checks passed\n");
	return 0;
}
