/*
 * fx_pack_selftest.c - permanent host checks for the finite-v1 compact FX
 * converter (ATMlib2FX-hlh.7).
 *
 * Covers:
 *   - gap varint boundaries 0/1/31/32/33/127/128/254/255/256/257/
 *     0x7EFE/0x7EFF/0x7F00/65534/65535 (encode + decode round-trip);
 *   - converter admission: oversize record, len<5, glen<1, bitmap 0/>15,
 *     SET_LOOP_PATTERN rejection, out-of-range CALL, gap > 65535, and the
 *     score-header rejections (format, channel count);
 *   - legacy v1 score translation to modern commands;
 *   - a host decode round-trip using the real device decoder
 *     (src/atm_synth.c with ATM_HAS_FX_COMPACT), porting the retained
 *     compact_format_test.c checks (gap advance, oversize, zero-channel,
 *     malformed, underflow freeze) plus a converted-stream round-trip.
 *
 * The device decoder is compiled into this host binary exactly as in
 * research/fx/fx_compact_spike/trace/compact_format_test.c; it contributes no
 * AVR bytes. Run via tests/fx_pack/run-tests.sh.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ATM_HAS_FX_COMPACT (1)
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

/* ---------------- shared stream buffer ---------------- */
static uint8_t g_buf[8192];
static size_t g_buflen;

void atm_fx_compact_fetch(uint32_t offset, uint8_t *dst, uint8_t n)
{
	for (uint8_t i = 0; i < n; i++) {
		uint32_t o = offset + i;
		dst[i] = o < g_buflen ? g_buf[o] : 0;
	}
}

/* ---------------- harness ---------------- */
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

/* ================================================================== */
/* gap codec                                                          */

static void test_gap_codec(void)
{
	static const uint32_t vals[] = {
		0, 1, 31, 32, 33, 127, 128, 254, 255, 256, 257,
		0x7EFE, 0x7EFF, 0x7F00, 65534, 65535
	};
	char msg[96];
	int ok = 1;

	for (size_t i = 0; i < sizeof(vals) / sizeof(vals[0]); i++) {
		uint8_t buf[8];
		uint8_t *end;
		uint32_t g = 0, used = 0;
		uint8_t want = fx_gap_nbytes(vals[i]);

		memset(buf, 0xAA, sizeof(buf));
		end = fx_put_gap(buf, vals[i]);
		if ((size_t)(end - buf) != want) ok = 0;
		if (fx_decode_gap(buf, sizeof(buf), &g, &used) != 0) ok = 0;
		if (g != vals[i] || used != want) ok = 0;
	}
	check("gap codec boundaries round-trip (16 values)", ok);
	snprintf(msg, sizeof(msg), "gap 65536 is rejected by the varint limit: %s",
		 fx_gap_nbytes(65536) == 0 ? "yes" : "NO");
	check(msg, fx_gap_nbytes(65536) == 0);
}

/* ================================================================== */
/* stream validator                                                   */

static int validate_bytes(const uint8_t *b, size_t n, char *err, size_t errlen)
{
	return fx_stream_validate(b, n, FX_ENC_DEFAULT_RING, err, errlen);
}

static void test_validator(void)
{
	char err[256];

	{
		static const uint8_t good[] = {
			0xC0, 0x05, 0x00, 0x01, 0x01, 0x00, 0x00
		};
		check("validator accepts a minimal well-formed stream",
		      validate_bytes(good, sizeof(good), err, sizeof(err)) == 0);
	}
	{
		static const uint8_t oversize[] = {
			0xC0, 0x21, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
			0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x00
		};
		check("validator rejects len > ring",
		      validate_bytes(oversize, sizeof(oversize), err, sizeof(err)) != 0 &&
		      strstr(err, "> ring") != NULL);
	}
	{
		static const uint8_t shortrec[] = { 0xC0, 0x04, 0, 0, 0, 0x00 };
		check("validator rejects len < 5",
		      validate_bytes(shortrec, sizeof(shortrec), err, sizeof(err)) != 0 &&
		      strstr(err, "< 5") != NULL);
	}
	{
		static const uint8_t zero_bm[] = { 0xC0, 0x05, 0, 0x00, 0, 0, 0x00 };
		check("validator rejects bitmap 0",
		      validate_bytes(zero_bm, sizeof(zero_bm), err, sizeof(err)) != 0 &&
		      strstr(err, "bitmap 0") != NULL);
	}
	{
		static const uint8_t high_bm[] = { 0xC0, 0x05, 0, 0x10, 0, 0, 0x00 };
		check("validator rejects bitmap > 15",
		      validate_bytes(high_bm, sizeof(high_bm), err, sizeof(err)) != 0 &&
		      strstr(err, "> 15") != NULL);
	}
	{
		static const uint8_t zero_glen[] = { 0xC0, 0x05, 0, 0x01, 0x00, 0, 0x00 };
		check("validator rejects glen 0",
		      validate_bytes(zero_glen, sizeof(zero_glen), err, sizeof(err)) != 0 &&
		      strstr(err, "glen 0") != NULL);
	}
	{
		/* len 6, gap 0, bitmap 1, glen 3, command 0x92 needs 3 bytes
		 * but only two remain in the group */
		static const uint8_t bad_cmd[] = {
			0xC0, 0x06, 0x00, 0x01, 0x03, 0x92, 0x00, 0x00
		};
		check("validator rejects a command that overflows the group",
		      validate_bytes(bad_cmd, sizeof(bad_cmd), err, sizeof(err)) != 0 &&
		      strstr(err, "overflows") != NULL);
	}
}

/* ================================================================== */
/* synthetic modern score builder                                     */

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

static int encode_score(const struct fx_score *s, uint16_t ring, uint32_t ticks,
			struct fx_encode_result *res)
{
	struct fx_score_patterns view = fx_score_view(s);
	struct fx_encode_options opt;

	memset(&opt, 0, sizeof(opt));
	opt.ring = ring;
	opt.tick_cap = ticks;
	opt.tempo_override = 0;
	memset(res, 0, sizeof(*res));
	return fx_encode(&view, &opt, res);
}

/* ================================================================== */
/* encoder admission tests                                            */

static void test_encode_simple(void)
{
	static const uint8_t p0[] = { 12, 0x41, 0x61 }; /* note, delay 2, stop */
	static const uint8_t p1[] = { 0x61 };
	const uint8_t *pats[] = { p0, p1 };
	const size_t sizes[] = { sizeof(p0), sizeof(p1) };
	const uint8_t entries[4] = { 0, 0, 0, 0 };
	struct fx_score s;
	struct fx_encode_result res;
	char err[256];

	make_score(&s, pats, sizes, 2, entries);
	check("simple modern score converts",
	      encode_score(&s, 32, 100, &res) == 0);
	check("simple stream validates",
	      fx_stream_validate(res.stream, res.stream_len, 32, err, sizeof(err)) == 0);
	check("simple stream has magic and END",
	      res.stream_len >= 2 && res.stream[0] == 0xC0 &&
	      res.stream[res.stream_len - 1] == 0x00);
	check("simple conversion reports a positive tick span",
	      res.meta.ticks_span > 0 && res.meta.passes >= 1);
	{
		struct fx_encode_result r2;
		int same = 0;
		if (encode_score(&s, 32, 100, &r2) == 0) {
			same = (r2.stream_len == res.stream_len &&
				memcmp(r2.stream, res.stream, res.stream_len) == 0);
			fx_encode_result_free(&r2);
		}
		check("simple conversion is deterministic", same);
	}
	fx_encode_result_free(&res);
	fx_score_free(&s);
}

static void test_calls_and_repeats(void)
{
	const uint8_t entries[4] = { 0, 0, 0, 0 };
	struct fx_score s;
	struct fx_encode_result res;

	/* CALL_REPEAT track 1 twice, then stop. Expect passes at ticks 0, 2, 4
	 * and completion at tick 5. */
	{
		static const uint8_t p0[] = { 12, 0x92, 1, 1, 0x61 };
		static const uint8_t p1[] = { 13, 0x41, 0x61 };
		const uint8_t *pats[] = { p0, p1 };
		const size_t sizes[] = { sizeof(p0), sizeof(p1) };
		make_score(&s, pats, sizes, 2, entries);
		check("CALL_REPEAT resolves offline (3 passes, stop at tick 5)",
		      encode_score(&s, 32, 100, &res) == 0 &&
		      res.meta.passes == 3 && res.meta.stopped_at == 5);
		fx_encode_result_free(&res);
		fx_score_free(&s);
	}
	/* CALL to the current pattern is skipped (no recursion). */
	{
		static const uint8_t p0[] = { 0x82, 0x00, 0x61 };
		const uint8_t *pats[] = { p0 };
		const size_t sizes[] = { sizeof(p0) };
		make_score(&s, pats, sizes, 1, entries);
		check("CALL to the current pattern is skipped, not recursed",
		      encode_score(&s, 32, 100, &res) == 0 &&
		      res.meta.stopped_at == 1);
		fx_encode_result_free(&res);
		fx_score_free(&s);
	}
	/* CALL at the three-level stack limit is skipped. */
	{
		static const uint8_t p0[] = { 0x82, 1, 0x61 };
		static const uint8_t p1[] = { 0x82, 2, 0x61 };
		static const uint8_t p2[] = { 0x82, 3, 0x61 };
		static const uint8_t p3[] = { 14, 0x61 };
		const uint8_t *pats[] = { p0, p1, p2, p3 };
		const size_t sizes[] = { sizeof(p0), sizeof(p1), sizeof(p2), sizeof(p3) };
		make_score(&s, pats, sizes, 4, entries);
		check("CALL at the stack limit is skipped, conversion terminates",
		      encode_score(&s, 32, 100, &res) == 0 &&
		      res.meta.stopped_at == 1);
		fx_encode_result_free(&res);
		fx_score_free(&s);
	}
	/* A legal nested call (depth 2) executes the called pattern. */
	{
		static const uint8_t p0[] = { 0x82, 1, 0x61 };
		static const uint8_t p1[] = { 0x82, 3, 0x61 };
		static const uint8_t p2[] = { 0x61 };
		static const uint8_t p3[] = { 14, 0x61 };
		const uint8_t *pats[] = { p0, p1, p2, p3 };
		const size_t sizes[] = { sizeof(p0), sizeof(p1), sizeof(p2), sizeof(p3) };
		make_score(&s, pats, sizes, 4, entries);
		check("legal nested CALL executes the called pattern",
		      encode_score(&s, 32, 100, &res) == 0 &&
		      res.meta.passes == 1 && res.meta.stopped_at == 1);
		fx_encode_result_free(&res);
		fx_score_free(&s);
	}
}

static void test_encode_rejections(void)
{
	struct fx_score s;
	struct fx_encode_result res;
	const uint8_t entries1[4] = { 0, 0, 0, 0 };

	/* SET_LOOP_PATTERN */
	{
		static const uint8_t p[] = { 0x80, 0x00, 0x61 };
		const uint8_t *pats[] = { p };
		const size_t sizes[] = { sizeof(p) };
		make_score(&s, pats, sizes, 1, entries1);
		check("SET_LOOP_PATTERN is rejected in finite v1",
		      encode_score(&s, 32, 100, &res) != 0 &&
		      strstr(res.error, "SET_LOOP_PATTERN") != NULL &&
		      strstr(res.error, "pattern 0") != NULL);
		fx_encode_result_free(&res);
		fx_score_free(&s);
	}
	/* out-of-range CALL */
	{
		static const uint8_t p[] = { 0x82, 0x09, 0x61 };
		const uint8_t *pats[] = { p };
		const size_t sizes[] = { sizeof(p) };
		make_score(&s, pats, sizes, 1, entries1);
		check("out-of-range CALL names the source pattern",
		      encode_score(&s, 32, 100, &res) != 0 &&
		      strstr(res.error, "CALL target") != NULL &&
		      strstr(res.error, "pattern 0") != NULL);
		fx_encode_result_free(&res);
		fx_score_free(&s);
	}
	/* oversize due record: ten notes per channel at tick 0 */
	{
		static const uint8_t p[] = {
			1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 0x5F, 0x61
		};
		const uint8_t *pats[] = { p };
		const size_t sizes[] = { sizeof(p) };
		make_score(&s, pats, sizes, 1, entries1);
		check("record larger than the ring is rejected with the tick",
		      encode_score(&s, 32, 100, &res) != 0 &&
		      strstr(res.error, "> ring 32") != NULL &&
		      strstr(res.error, "tick 0") != NULL);
		fx_encode_result_free(&res);
		fx_score_free(&s);
	}
	/* zero-channel/glen are covered by the validator above; the encoder
	 * cannot synthesize them because they are output invariants. */
}

static void test_encode_gap_limits(void)
{
	/* One long delay with operand 0xFFFF schedules 65536 ticks -> gap 65535
	 * (the varint maximum). Two in a row exceed it and must be rejected. */
	static const uint8_t one[] = {
		12, 0x95, 0xFF, 0xFF, 13, 0x61
	};
	static const uint8_t two[] = {
		12, 0x95, 0xFF, 0xFF, 0x95, 0xFF, 0xFF, 13, 0x61
	};
	const uint8_t entries[4] = { 0, 0, 0, 0 };
	struct fx_score s;
	struct fx_encode_result res;
	char err[256];

	{
		const uint8_t *pats[] = { one };
		const size_t sizes[] = { sizeof(one) };
		make_score(&s, pats, sizes, 1, entries);
		check("gap 65535 (maximum varint) is accepted",
		      encode_score(&s, 32, 70000, &res) == 0);
		check("gap 65535 stream validates",
		      fx_stream_validate(res.stream, res.stream_len, 32,
					 err, sizeof(err)) == 0);
		fx_encode_result_free(&res);
		fx_score_free(&s);
	}
	{
		const uint8_t *pats[] = { two };
		const size_t sizes[] = { sizeof(two) };
		make_score(&s, pats, sizes, 1, entries);
		check("gap > 65535 is rejected with the tick",
		      encode_score(&s, 32, 200000, &res) != 0 &&
		      strstr(res.error, "gap") != NULL &&
		      strstr(res.error, "65535") != NULL);
		fx_encode_result_free(&res);
		fx_score_free(&s);
	}
}

static void test_parse_rejections(void)
{
	char err[256];
	struct fx_score s;

	{
		static const uint8_t bad_fmt[] = { 0x00, 0x01, 0, 0, 4, 0, 0, 0, 0 };
		check("non-full format is rejected",
		      fx_score_parse(bad_fmt, sizeof(bad_fmt), FX_SCORE_MODERN_FULL,
				     &s, err, sizeof(err)) != 0 &&
		      strstr(err, "ATM_SCORE_FMT_FULL") != NULL);
		fx_score_free(&s);
	}
	{
		static const uint8_t bad_ch[] = { 0x03, 0x01, 0x09, 0x00, 0x03,
						  0x00, 0x00, 0x00, 0x00, 0x61 };
		check("non-4-channel score is rejected",
		      fx_score_parse(bad_ch, sizeof(bad_ch), FX_SCORE_MODERN_FULL,
				     &s, err, sizeof(err)) != 0 &&
		      strstr(err, "channel count") != NULL);
		fx_score_free(&s);
	}
}

static void test_legacy_translation(void)
{
	/* track count 1, offset 0, four entries 0, data: set vol 5, delay 3,
	 * stop. The pre-2.0 command bytes must become modern bytes. */
	static const uint8_t legacy[] = {
		0x01,
		0x00, 0x00,
		0x00, 0x00, 0x00, 0x00,
		0x40, 0x05,
		0xA2,
		0x9F
	};
	static const uint8_t want[] = { 0x74, 0x05, 0x42, 0x61 };
	struct fx_score s;
	struct fx_encode_result res;
	char err[256];
	int ok;

	memset(&s, 0, sizeof(s));
	ok = fx_score_parse(legacy, sizeof(legacy), FX_SCORE_LEGACY_V1,
			    &s, err, sizeof(err)) == 0;
	check("legacy v1 score parses", ok);
	if (ok) {
		check("legacy v1 is translated to modern command bytes",
		      s.num_patterns == 1 &&
		      s.len - s.pattern_offset[0] == sizeof(want) &&
		      memcmp(s.bytes + s.pattern_offset[0], want, sizeof(want)) == 0);
		check("legacy v1 stream converts",
		      encode_score(&s, 32, 100, &res) == 0);
		check("legacy v1 stream validates",
		      fx_stream_validate(res.stream, res.stream_len, 32,
					 err, sizeof(err)) == 0);
		fx_encode_result_free(&res);
	}
	fx_score_free(&s);
}

/* ================================================================== */
/* device decoder checks (ported from compact_format_test.c)         */

static void putb(uint8_t b)
{
	if (g_buflen < sizeof(g_buf)) g_buf[g_buflen++] = b;
}

static void put_gap_t(uint16_t g)
{
	uint8_t tmp[4];
	uint8_t *e = fx_put_gap(tmp, g);
	for (uint8_t *p = tmp; p < e; p++) putb(*p);
}

static void emit_pass_ch0(uint16_t gap, const uint8_t *cmds, uint8_t n)
{
	putb((uint8_t)(1 + fx_gap_nbytes(gap) + 1 + 1 + n));
	put_gap_t(gap);
	putb(0x01);
	putb(n);
	for (uint8_t i = 0; i < n; i++) putb(cmds[i]);
}

static void begin_test(void)
{
	g_buflen = 0;
	putb(0xC0);
	memset(&atm_fx_compact_state, 0, sizeof(atm_fx_compact_state));
	osc_setup();
	atm_synth_setup();
}

static void test_gap_advance(uint16_t g)
{
	static const uint8_t n12[1] = { 12 };
	static const uint8_t n13[1] = { 13 };
	int a = -1, b = -1;
	char msg[96];

	begin_test();
	emit_pass_ch0(g, n12, 1);
	emit_pass_ch0(0, n13, 1);
	putb(0x00);
	atm_fx_compact_play(0, (uint32_t)g_buflen);
	for (int i = 1; i <= (int)g + 4; i++) {
		atm_fx_compact_service();
		if (host_cb[0].cb == NULL) break;
		host_cb[0].cb(0, host_cb[0].priv);
		if (a < 0 && channels[0].note == 12) {
			a = i;
		} else if (a >= 0 && channels[0].note == 13) {
			b = i;
			break;
		}
	}
	snprintf(msg, sizeof(msg),
		 "device gap %u advances %u ticks", (unsigned)g,
		 (unsigned)g + 1);
	check(msg, a == 1 && b > 0 && (b - a) == (int)g + 1);
}

static void test_decoder_rejections(void)
{
	{
		begin_test();
		putb((uint8_t)(ATM_FX_COMPACT_RING + 1));
		for (int i = 0; i < ATM_FX_COMPACT_RING + 1; i++) putb(0x00);
		putb(0x00);
		atm_fx_compact_play(0, (uint32_t)g_buflen);
		atm_fx_compact_service();
		if (host_cb[0].cb) host_cb[0].cb(0, host_cb[0].priv);
		check("device rejects oversize record (error=2, stopped)",
		      atm_fx_compact_state.error == 2 &&
		      atm_fx_compact_state.active == 0);
	}
	{
		begin_test();
		putb(5);
		put_gap_t(0);
		putb(0x00);
		putb(0x00);
		putb(0x00);
		atm_fx_compact_play(0, (uint32_t)g_buflen);
		atm_fx_compact_service();
		if (host_cb[0].cb) host_cb[0].cb(0, host_cb[0].priv);
		check("device rejects zero-channel pass (error=1, stopped)",
		      atm_fx_compact_state.error == 1 &&
		      atm_fx_compact_state.active == 0);
	}
	{
		begin_test();
		putb(6);
		put_gap_t(0);
		putb(0x01);
		putb(3);
		putb(12);
		putb(12);
		putb(0x00);
		atm_fx_compact_play(0, (uint32_t)g_buflen);
		channels[0].note = 0x2A;
		atm_fx_compact_service();
		if (host_cb[0].cb) host_cb[0].cb(0, host_cb[0].priv);
		check("device rejects malformed group without mutation",
		      atm_fx_compact_state.error == 1 &&
		      atm_fx_compact_state.active == 0 &&
		      channels[0].note == 0x2A);
	}
	{
		begin_test();
		putb(24);
		put_gap_t(0);
		putb(0x01);
		putb(20);
		for (int i = 0; i < 6; i++) putb(12);
		atm_fx_compact_play(0, (uint32_t)g_buflen);
		channels[0].note = 0x2A;
		for (int i = 0; i < 3; i++) {
			atm_fx_compact_service();
			if (host_cb[0].cb) host_cb[0].cb(0, host_cb[0].priv);
		}
		check("device underflow increments and freezes without mutation",
		      atm_fx_compact_state.underruns >= 1 &&
		      channels[0].note == 0x2A);
	}
}

static int run_decoder(const uint8_t *stream, size_t len, int max_ticks)
{
	if (len > sizeof(g_buf)) return -1;
	memcpy(g_buf, stream, len);
	g_buflen = len;
	memset(&atm_fx_compact_state, 0, sizeof(atm_fx_compact_state));
	osc_setup();
	atm_synth_setup();
	atm_fx_compact_play(0, (uint32_t)len);
	for (int i = 0; i < max_ticks; i++) {
		if (host_cb[0].cb == NULL) break;
		atm_fx_compact_service();
		if (host_cb[0].cb == NULL) break;
		host_cb[0].cb(0, host_cb[0].priv);
	}
	return 0;
}

static void test_decoder_roundtrip(void)
{
	static const uint8_t p0[] = {
		12, 0x74, 0x7F, 0x41, 0x5F, 0x61
	};
	const uint8_t *pats[] = { p0 };
	const size_t sizes[] = { sizeof(p0) };
	const uint8_t entries[4] = { 0, 0, 0, 0 };
	struct fx_score s;
	struct fx_encode_result res;

	make_score(&s, pats, sizes, 1, entries);
	if (encode_score(&s, 32, 100, &res) == 0) {
		run_decoder(res.stream, res.stream_len, 100);
		check("converted stream decodes with no error/underrun",
		      atm_fx_compact_state.error == 0 &&
		      atm_fx_compact_state.underruns == 0);
		fx_encode_result_free(&res);
	} else {
		check("converted stream decodes with no error/underrun", 0);
	}
	fx_score_free(&s);
}

/* ================================================================== */
/* --decode mode                                                      */

static int decode_stream_file(const char *path)
{
	FILE *f = fopen(path, "rb");
	long sz;
	int limited;

	if (!f) { perror(path); return 1; }
	fseek(f, 0, SEEK_END);
	sz = ftell(f);
	fseek(f, 0, SEEK_SET);
	if (sz < 0 || (size_t)sz > sizeof(g_buf)) {
		fprintf(stderr, "decode: %s is too large (%ld bytes)\n", path, sz);
		fclose(f);
		return 1;
	}
	g_buflen = (size_t)sz;
	if (fread(g_buf, 1, g_buflen, f) != g_buflen) {
		perror("fread");
		fclose(f);
		return 1;
	}
	fclose(f);

	memset(&atm_fx_compact_state, 0, sizeof(atm_fx_compact_state));
	osc_setup();
	atm_synth_setup();
	atm_fx_compact_play(0, (uint32_t)g_buflen);
	for (int i = 0; i < 100000; i++) {
		if (host_cb[0].cb == NULL) break;
		atm_fx_compact_service();
		if (host_cb[0].cb == NULL) break;
		host_cb[0].cb(0, host_cb[0].priv);
	}

	limited = (host_cb[0].cb != NULL);
	printf("decode: ticks=%u underruns=%u error=%u stopped=%u active=%u "
	       "max_record=%u max_window=%u max_service_gap=%u%s\n",
	       (unsigned)atm_fx_compact_state.ticks,
	       (unsigned)atm_fx_compact_state.underruns,
	       (unsigned)atm_fx_compact_state.error,
	       (unsigned)atm_fx_compact_state.stop_tick,
	       (unsigned)atm_fx_compact_state.active,
	       (unsigned)atm_fx_compact_state.max_record,
	       (unsigned)atm_fx_compact_state.max_window,
	       (unsigned)atm_fx_compact_state.max_service_gap,
	       limited ? " (tick limit hit)" : "");
	return (atm_fx_compact_state.error == 0 &&
		atm_fx_compact_state.underruns == 0 &&
		atm_fx_compact_state.stop_tick > 0) ? 0 : 1;
}

/* ================================================================== */

int main(int argc, char **argv)
{
	if (argc >= 3 && !strcmp(argv[1], "--decode"))
		return decode_stream_file(argv[2]);

	/* gap codec */
	test_gap_codec();
	/* stream validator (device admission mirrored on the host) */
	test_validator();
	/* encoder */
	test_encode_simple();
	test_calls_and_repeats();
	test_encode_rejections();
	test_encode_gap_limits();
	test_parse_rejections();
	test_legacy_translation();
	/* device decoder, ported from compact_format_test.c */
	{
		static const uint16_t gaps[] = {
			0, 1, 31, 32, 33, 127, 128, 254, 255, 256, 257,
			0x7EFE, 0x7EFF, 0x7F00, 65534, 65535
		};
		for (size_t i = 0; i < sizeof(gaps) / sizeof(gaps[0]); i++)
			test_gap_advance(gaps[i]);
	}
	test_decoder_rejections();
	test_decoder_roundtrip();

	if (g_fail) {
		fprintf(stderr, "fx_pack_selftest: FAILED\n");
		return 1;
	}
	printf("fx_pack_selftest: all checks passed\n");
	return 0;
}
