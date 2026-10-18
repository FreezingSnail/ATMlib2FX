/*
 * selftest.c - C selftest for the ATMlib2FX song-shrink engine
 * (ATMlib2FX-hlh.3). Host-only. Run by tests/atm-shrink/run-tests.sh.
 *
 * The strongest check is `sim_equivalent`: a faithful port of the library
 * traversal (same model as research/fx/tools/fx_compile_stream.c) that replays
 * two scores tick by tick and compares every command byte a channel executes.
 * It ignores only the internal pattern-stack index, which legitimately changes
 * when calls are added.
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stddef.h>

#include "shrink_core.h"

static int failures = 0;
static int passes = 0;

#define CHECK(cond, msg) do { \
	if (cond) { passes++; } \
	else { printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, msg); failures++; } \
} while (0)

/* ---- packed blob builder (mirrors the PROGMEM layout) ---- */
static size_t build_blob(uint8_t *out, uint8_t fmt, int npat, int nch,
			 const uint8_t *start, const struct shrink_pat *pats)
{
	size_t hdr = 2 + 2u * (size_t)npat + 1 + (size_t)nch;
	out[0] = fmt;
	out[1] = (uint8_t)npat;
	size_t off = hdr;
	for (int i = 0; i < npat; i++) {
		out[2 + 2 * i] = (uint8_t)(off & 0xFF);
		out[3 + 2 * i] = (uint8_t)((off >> 8) & 0xFF);
		off += (size_t)pats[i].len;
	}
	out[2 + 2 * npat] = (uint8_t)nch;
	for (int c = 0; c < nch; c++)
		out[3 + 2 * npat + c] = start[c];
	size_t w = hdr;
	for (int i = 0; i < npat; i++) {
		memcpy(out + w, pats[i].b, (size_t)pats[i].len);
		w += (size_t)pats[i].len;
	}
	return w;
}

static void set_pat(struct shrink_pat *p, const uint8_t *b, int len)
{
	memset(p, 0, sizeof(*p));
	memcpy(p->b, b, (size_t)len);
	p->len = len;
	p->alive = 1;
}

/* ---- traversal simulator ------------------------------------------- */
struct sim_pat { const uint8_t *b; int pat; int rep; };
struct sim_ch { struct sim_pat st[SHRINK_STACK_DEPTH]; int sp; int delay; int active; };

static const uint8_t *sim_base;
static const struct shrink_score *sim_s;

static const uint8_t *sim_ptr(int pat) { return sim_s->pat[pat].b; }

static void sim_reset(struct sim_ch *c, int entry)
{
	memset(c, 0, sizeof(*c));
	c->active = 1;
	c->st[0].b = sim_ptr(entry);
	c->st[0].pat = (uint8_t)entry;
}

static uint64_t fnv(uint64_t h, uint8_t v) { h ^= v; h *= 1099511628211ULL; return h; }

/* Hash the command bytes a channel executes for one tick (traversal-only
 * commands are consumed, a genuine stop is hashed as a marker). */
static uint64_t sim_step(struct sim_ch *c)
{
	uint64_t h = 1469598103934665603ULL;
	while (c->delay == 0) {
		struct sim_pat *ps = &c->st[c->sp];
		const uint8_t *p = ps->b;
		uint8_t id = p[0];
		uint8_t sz = shrink_cmd_size(id);

		if (id < 0x40) { h = fnv(h, id); ps->b += sz; }
		else if (id < 0x60) { c->delay = (uint16_t)(id - 0x3F); ps->b += sz; }
		else if (id < 0x70) {
			if (id == SHRINK_CMD_TERM) {
				if (ps->rep > 0) { ps->rep--; ps->b = sim_ptr(ps->pat); }
				else if (c->sp == 0) { c->active = 0; c->delay = 0xFFFF; h = fnv(h, 0xEE); break; }
				else { c->sp--; }
			} else { h = fnv(h, id); ps->b += sz; }
		} else if (id < 0x80) {
			h = fnv(h, id); h = fnv(h, p[1]); ps->b += sz;
		} else {
			uint8_t csz = (uint8_t)(((id >> 4) & 0x07) + 1);
			uint8_t cid = (uint8_t)(id & 0x0F);
			if (cid == 0x02) { /* CALL / CALL_REPEAT */
				uint8_t track = p[1];
				if (c->sp < SHRINK_STACK_DEPTH - 1 && track != ps->pat) {
					ps->b += 1 + csz;
					c->sp++;
					c->st[c->sp].b = sim_ptr(track);
					c->st[c->sp].pat = track;
					c->st[c->sp].rep = csz > 1 ? p[2] : 0;
				} else {
					ps->b += 1 + csz;
				}
			} else if (cid == 0x00) { /* SET_LOOP_PATTERN */
				/* Traversal-only: the operand is a pattern
				 * reference that finalize may renumber, so hash
				 * the opcode but not its value (the effect on
				 * playback is a restart, not a command byte).
				 * An out-of-range operand is corruption. */
				h = fnv(h, id);
				if (p[1] >= (uint8_t)sim_s->npat) h = fnv(h, 0xEF);
				ps->b += 1 + csz;
			} else {
				for (uint8_t k = 0; k < (uint8_t)(1 + csz); k++) h = fnv(h, p[k]);
				ps->b += 1 + csz;
			}
		}
	}
	if (c->delay != 0xFFFF) c->delay--;
	return h;
}

static uint64_t sim_hash(const struct shrink_score *s, int ticks)
{
	sim_s = s;
	sim_base = NULL;
	(void)sim_base;
	struct sim_ch ch[SHRINK_MAX_CHANNELS];
	for (uint8_t c = 0; c < s->num_channels; c++) sim_reset(&ch[c], s->start[c]);

	uint64_t h = 1469598103934665603ULL;
	for (int t = 0; t < ticks; t++) {
		h = fnv(h, (uint8_t)(t & 0xFF));
		for (uint8_t c = 0; c < s->num_channels; c++) {
			h = fnv(h, c);
			h = fnv(h, (uint8_t)ch[c].active);
			uint64_t ch_h = sim_step(&ch[c]);
			for (int b = 0; b < 8; b++) h = fnv(h, (uint8_t)(ch_h >> (b * 8)));
		}
	}
	return h;
}

/* ------------------------------------------------------------------ */
static void test_parse(void)
{
	struct shrink_pat p[2];
	uint8_t b0[] = { 0x74, 0x10, SHRINK_CMD_TERM };
	uint8_t b1[] = { 0x19, SHRINK_CMD_TERM };
	set_pat(&p[0], b0, sizeof(b0));
	set_pat(&p[1], b1, sizeof(b1));
	uint8_t start[] = { 0, 1 };
	uint8_t blob[64];
	size_t n = build_blob(blob, 0x03, 2, 2, start, p);

	struct shrink_score s;
	CHECK(shrink_parse(&s, blob, n) == SHRINK_OK, "parse ok");
	CHECK(s.npat == 2, "npat 2");
	CHECK(s.num_channels == 2, "nch 2");
	CHECK(s.pat[0].len == 3 && s.pat[0].b[0] == 0x74, "pat0");
	CHECK(s.pat[1].len == 2 && s.pat[1].b[0] == 0x19, "pat1");
	CHECK(shrink_score_bytes(&s) == (int)n, "score bytes == blob");

	/* Reject a legacy raw array (no pattern-table bit). */
	uint8_t legacy[] = { 0x08, 0x00, 0x04, 0x00 };
	struct shrink_score r;
	CHECK(shrink_parse(&r, legacy, sizeof(legacy)) == SHRINK_ERR_FORMAT,
	      "legacy rejected");
}

static void test_inline(void)
{
	struct shrink_pat p[2];
	uint8_t b0[] = { SHRINK_CMD_CALL, 0x01, SHRINK_CMD_TERM };
	uint8_t b1[] = { 0x74, 0x10, SHRINK_CMD_TERM };
	set_pat(&p[0], b0, sizeof(b0));
	set_pat(&p[1], b1, sizeof(b1));
	uint8_t start[] = { 0 };
	uint8_t blob[64];
	size_t n = build_blob(blob, 0x03, 2, 1, start, p);

	struct shrink_score s, orig;
	CHECK(shrink_parse(&s, blob, n) == SHRINK_OK, "inline parse");
	CHECK(shrink_parse(&orig, blob, n) == SHRINK_OK, "inline orig parse");

	int saved = shrink_inline_single_use(&s);
	CHECK(saved == 5, "inline saves 5 bytes");
	CHECK(shrink_finalize(&s) == SHRINK_OK, "inline finalize");
	CHECK(s.npat == 1, "inline drops pattern");
	CHECK(s.pat[0].len == 3 && s.pat[0].b[0] == 0x74 && s.pat[0].b[1] == 0x10,
	      "inline body spliced");
	CHECK(shrink_max_depth(&s) == 0, "inline removes nesting");
	CHECK(sim_hash(&orig, 8) == sim_hash(&s, 8), "inline playback identical");
}

static void test_share(void)
{
	/* R X R X R TERM with R a 10-byte run and X a 1-byte note. */
	const uint8_t R[] = { 0x74, 0x10, 0x5f, 0x74, 0x20, 0x4f, 0x19, 0x74, 0x30, 0x47 };
	uint8_t body[64];
	int n = 0;
	for (int k = 0; k < 3; k++) {
		memcpy(body + n, R, sizeof(R)); n += (int)sizeof(R);
		if (k < 2) body[n++] = 0x3c; /* a distinct 1-byte note */
	}
	body[n++] = SHRINK_CMD_TERM;

	struct shrink_pat p[1];
	set_pat(&p[0], body, n);
	uint8_t start[] = { 0 };
	uint8_t blob[128];
	size_t bn = build_blob(blob, 0x03, 1, 1, start, p);

	struct shrink_score s, orig;
	CHECK(shrink_parse(&s, blob, bn) == SHRINK_OK, "share parse");
	CHECK(shrink_parse(&orig, blob, bn) == SHRINK_OK, "share orig parse");

	int before = shrink_score_bytes(&s);
	int saved = shrink_share_runs(&s);
	CHECK(saved == 11, "share saves 11 bytes (formula)");
	CHECK(shrink_finalize(&s) == SHRINK_OK, "share finalize");
	CHECK(shrink_pattern_count(&s) == 2, "share adds one pattern");
	CHECK(before - shrink_score_bytes(&s) == 11, "share size delta 11");
	CHECK(shrink_max_depth(&s) <= SHRINK_STACK_DEPTH - 1, "share depth ok");
	CHECK(sim_hash(&orig, 64) == sim_hash(&s, 64), "share playback identical");
}

static void test_share_forbidden(void)
{
	/* The only repeated run contains SET_TEMPO, which must never be shared. */
	uint8_t body[] = {
		0x74, 0x10, 0x72, 0x32,
		0x74, 0x10, 0x72, 0x32,
		SHRINK_CMD_TERM
	};
	struct shrink_pat p[1];
	set_pat(&p[0], body, sizeof(body));
	uint8_t start[] = { 0 };
	uint8_t blob[64];
	size_t bn = build_blob(blob, 0x03, 1, 1, start, p);

	struct shrink_score s;
	CHECK(shrink_parse(&s, blob, bn) == SHRINK_OK, "forbidden parse");
	CHECK(shrink_share_runs(&s) == 0, "tempo run not shared");
	CHECK(shrink_pattern_count(&s) == 1, "no pattern added");
}

static void test_share_depth_gate(void)
{
	const uint8_t R[] = { 0x74, 0x10, 0x5f, 0x74, 0x20, 0x4f, 0x19, 0x74, 0x30, 0x47 };
	uint8_t b2[64];
	int n = 0;
	memcpy(b2 + n, R, sizeof(R)); n += (int)sizeof(R);
	memcpy(b2 + n, R, sizeof(R)); n += (int)sizeof(R);
	b2[n++] = SHRINK_CMD_TERM;

	struct shrink_pat p[3];
	uint8_t b0[] = { SHRINK_CMD_CALL, 0x01, SHRINK_CMD_TERM };
	uint8_t b1[] = { SHRINK_CMD_CALL, 0x02, SHRINK_CMD_TERM };
	set_pat(&p[0], b0, sizeof(b0));
	set_pat(&p[1], b1, sizeof(b1));
	set_pat(&p[2], b2, n);
	uint8_t start[] = { 0 };
	uint8_t blob[256];
	size_t bn = build_blob(blob, 0x03, 3, 1, start, p);

	struct shrink_score s;
	CHECK(shrink_parse(&s, blob, bn) == SHRINK_OK, "depth parse");
	CHECK(shrink_max_depth(&s) == 2, "depth is 2 before share");
	CHECK(shrink_share_runs(&s) == 0, "share rejected at depth limit");
	CHECK(shrink_pattern_count(&s) == 3, "depth gate adds nothing");
}

static void test_loop_detect(void)
{
	struct shrink_pat p[1];
	uint8_t body[] = { SHRINK_CMD_LOOP, 0x00, 0x74, 0x10, SHRINK_CMD_TERM };
	set_pat(&p[0], body, sizeof(body));
	uint8_t start[] = { 0 };
	uint8_t blob[64];
	size_t bn = build_blob(blob, 0x03, 1, 1, start, p);

	struct shrink_score s;
	CHECK(shrink_parse(&s, blob, bn) == SHRINK_OK, "loop parse");
	CHECK(shrink_loop_normalize(&s) == 0, "loop saves 0 (already canonical)");
	CHECK(s.loop_present == 1, "loop detected");

	uint8_t oneshot[] = { 0x74, 0x10, SHRINK_CMD_TERM };
	set_pat(&p[0], oneshot, sizeof(oneshot));
	bn = build_blob(blob, 0x03, 1, 1, start, p);
	struct shrink_score t;
	CHECK(shrink_parse(&t, blob, bn) == SHRINK_OK, "oneshot parse");
	CHECK(shrink_loop_normalize(&t) == 0 && t.loop_present == 0,
	      "one-shot has no loop");
}

/* ---- drift regressions (ATMlib2FX-hlh.3 review) --------------------- */

/* SET_LOOP_PATTERN operand regression. Review repro: p0={CALL 1; LOOP 2;
 * END}, p1 a single-use leaf, p2 the loop target. The old engine dropped p1
 * and emitted p0={74 10; LOOP 2; END} with npat=2, i.e. operand 2 out of
 * range (garbage restart). The fix: a loop operand is a use (+ its target is
 * never inlined away) and finalize remaps the operand. */
static void test_loop_operand_uses(void)
{
	struct shrink_pat p[3];
	uint8_t b0[] = { SHRINK_CMD_CALL, 0x01, SHRINK_CMD_LOOP, 0x02, SHRINK_CMD_TERM };
	uint8_t b1[] = { 0x74, 0x10, SHRINK_CMD_TERM };
	uint8_t b2[] = { 0x74, 0x20, SHRINK_CMD_TERM };
	set_pat(&p[0], b0, sizeof(b0));
	set_pat(&p[1], b1, sizeof(b1));
	set_pat(&p[2], b2, sizeof(b2));
	uint8_t start[] = { 0 };
	uint8_t blob[128];
	size_t bn = build_blob(blob, 0x03, 3, 1, start, p);

	struct shrink_score s, orig;
	CHECK(shrink_parse(&s, blob, bn) == SHRINK_OK, "loop-operand parse");
	CHECK(shrink_parse(&orig, blob, bn) == SHRINK_OK, "loop-operand orig parse");

	CHECK(shrink_inline_single_use(&s) == 5, "loop-operand: leaf inlined");
	CHECK(shrink_finalize(&s) == SHRINK_OK, "loop-operand finalize");
	CHECK(s.npat == 2, "loop-operand: npat drops to 2");
	CHECK(s.pat[0].len == 5 &&
	      s.pat[0].b[2] == SHRINK_CMD_LOOP && s.pat[0].b[3] == 0x01,
	      "loop-operand: operand remapped to live pattern");
	CHECK(s.pat[1].len == 3 && s.pat[1].b[1] == 0x20,
	      "loop-operand: loop target body preserved");
	CHECK(shrink_validate(&s) == SHRINK_OK, "loop-operand: refs valid");
	CHECK(sim_hash(&orig, 16) == sim_hash(&s, 16),
	      "loop-operand: playback identical");

	/* A pattern that is a loop target and a single-use CALL target at once
	 * must survive: inlining it would leave the operand dangling. */
	struct shrink_pat q[2];
	uint8_t c0[] = { SHRINK_CMD_CALL, 0x01, SHRINK_CMD_LOOP, 0x01, SHRINK_CMD_TERM };
	uint8_t c1[] = { 0x74, 0x30, SHRINK_CMD_TERM };
	set_pat(&q[0], c0, sizeof(c0));
	set_pat(&q[1], c1, sizeof(c1));
	bn = build_blob(blob, 0x03, 2, 1, start, q);
	struct shrink_score t;
	CHECK(shrink_parse(&t, blob, bn) == SHRINK_OK, "loop-call-target parse");
	CHECK(shrink_inline_single_use(&t) == 0, "loop-call-target not inlined");
	CHECK(shrink_finalize(&t) == SHRINK_OK, "loop-call-target finalize");
	CHECK(t.npat == 2 && shrink_validate(&t) == SHRINK_OK,
	      "loop-call-target stays valid");
}

static void test_validate(void)
{
	struct shrink_score s;
	memset(&s, 0, sizeof(s));
	s.npat = 1;
	s.num_channels = 1;
	s.start[0] = 0;

	uint8_t self_loop[] = { SHRINK_CMD_LOOP, 0x00, SHRINK_CMD_TERM };
	set_pat(&s.pat[0], self_loop, sizeof(self_loop));
	CHECK(shrink_validate(&s) == SHRINK_OK, "validate accepts self-loop");

	uint8_t stale[] = { SHRINK_CMD_LOOP, 0x01, SHRINK_CMD_TERM };
	set_pat(&s.pat[0], stale, sizeof(stale));
	CHECK(shrink_validate(&s) == SHRINK_ERR_RANGE, "validate rejects stale ref");

	uint8_t truncated[] = { 0x74 };
	set_pat(&s.pat[0], truncated, sizeof(truncated));
	CHECK(shrink_validate(&s) == SHRINK_ERR_RANGE, "validate rejects truncated cmd");

	set_pat(&s.pat[0], self_loop, sizeof(self_loop));
	s.start[0] = 1;
	CHECK(shrink_validate(&s) == SHRINK_ERR_RANGE, "validate rejects bad entry");
}

/* Depth-3 single-use CALL chain input (drift 2 regression support): the
 * library skips CALL at pstack_index >= SHRINK_STACK_DEPTH-1, so inlining the
 * chain down to depth 0 changes playback. The CLI must reject this input with
 * exit 4 (checked end-to-end in run-tests.sh). */
static void test_depth3_chain(void)
{
	struct shrink_pat p[4];
	uint8_t b0[] = { SHRINK_CMD_CALL, 0x01, SHRINK_CMD_TERM };
	uint8_t b1[] = { SHRINK_CMD_CALL, 0x02, SHRINK_CMD_TERM };
	uint8_t b2[] = { SHRINK_CMD_CALL, 0x03, SHRINK_CMD_TERM };
	uint8_t b3[] = { 0x74, 0x10, SHRINK_CMD_TERM };
	set_pat(&p[0], b0, sizeof(b0));
	set_pat(&p[1], b1, sizeof(b1));
	set_pat(&p[2], b2, sizeof(b2));
	set_pat(&p[3], b3, sizeof(b3));
	uint8_t start[] = { 0 };
	uint8_t blob[128];
	size_t bn = build_blob(blob, 0x03, 4, 1, start, p);

	struct shrink_score s;
	CHECK(shrink_parse(&s, blob, bn) == SHRINK_OK, "depth3-chain parse");
	CHECK(shrink_max_depth(&s) == SHRINK_STACK_DEPTH,
	      "depth3-chain: input depth reaches the limit");
}

/* Loop-rooted depth regression (ATMlib2FX-hlh.3, second review round): a
 * SET_LOOP_PATTERN target is restarted at pstack_index 0 (the library restarts
 * a stopped channel, which always stopped at depth 0, from
 * ch->loop_pattern_index; src/atm_synth.c start_loop), so a CALL chain rooted
 * only at a loop target must be depth-counted exactly like a channel-entry
 * chain. sim_step does not model loop restart, so this class is asserted
 * directly on the depth model and the share gate, not via sim_hash. */
static void test_loop_root_depth(void)
{
	/* depth-3 loop-rooted chain: p0 loops into p1; p1 -> p2 -> p3 -> p4 */
	struct shrink_pat p[5];
	uint8_t b0[] = { SHRINK_CMD_LOOP, 0x01, SHRINK_CMD_TERM };
	uint8_t b1[] = { SHRINK_CMD_CALL, 0x02, SHRINK_CMD_TERM };
	uint8_t b2[] = { SHRINK_CMD_CALL, 0x03, SHRINK_CMD_TERM };
	uint8_t b3[] = { SHRINK_CMD_CALL, 0x04, SHRINK_CMD_TERM };
	uint8_t b4[] = { 0x74, 0x10, SHRINK_CMD_TERM };
	set_pat(&p[0], b0, sizeof(b0));
	set_pat(&p[1], b1, sizeof(b1));
	set_pat(&p[2], b2, sizeof(b2));
	set_pat(&p[3], b3, sizeof(b3));
	set_pat(&p[4], b4, sizeof(b4));
	uint8_t start[] = { 0 };
	uint8_t blob[128];
	size_t bn = build_blob(blob, 0x03, 5, 1, start, p);

	struct shrink_score s;
	CHECK(shrink_parse(&s, blob, bn) == SHRINK_OK, "loop-root-depth3 parse");
	CHECK(shrink_max_depth(&s) == SHRINK_STACK_DEPTH,
	      "loop-rooted chain: input depth reaches the limit");

	/* One hop shorter: depth 2, must stay gate-passing. */
	struct shrink_pat q[4];
	uint8_t c0[] = { SHRINK_CMD_LOOP, 0x01, SHRINK_CMD_TERM };
	uint8_t c1[] = { SHRINK_CMD_CALL, 0x02, SHRINK_CMD_TERM };
	uint8_t c2[] = { SHRINK_CMD_CALL, 0x03, SHRINK_CMD_TERM };
	uint8_t c3[] = { 0x74, 0x20, SHRINK_CMD_TERM };
	set_pat(&q[0], c0, sizeof(c0));
	set_pat(&q[1], c1, sizeof(c1));
	set_pat(&q[2], c2, sizeof(c2));
	set_pat(&q[3], c3, sizeof(c3));
	bn = build_blob(blob, 0x03, 4, 1, start, q);
	struct shrink_score t;
	CHECK(shrink_parse(&t, blob, bn) == SHRINK_OK, "loop-root-depth2 parse");
	CHECK(shrink_max_depth(&t) == 2, "loop-rooted chain: depth 2 reported");

	/* The share-pass depth gate uses the same model: a run inside a
	 * loop-rooted pattern is a depth-0 site and may be shared (pre-fix the
	 * pattern looked unreachable and every candidate was refused). */
	const uint8_t R[] = { 0x74, 0x10, 0x5f, 0x74, 0x20, 0x4f, 0x19, 0x74, 0x30, 0x47 };
	uint8_t body[64];
	int n = 0;
	memcpy(body + n, R, sizeof(R)); n += (int)sizeof(R);
	memcpy(body + n, R, sizeof(R)); n += (int)sizeof(R);
	body[n++] = SHRINK_CMD_TERM;
	struct shrink_pat r[2];
	uint8_t d0[] = { SHRINK_CMD_LOOP, 0x01, SHRINK_CMD_TERM };
	set_pat(&r[0], d0, sizeof(d0));
	set_pat(&r[1], body, n);
	bn = build_blob(blob, 0x03, 2, 1, start, r);
	struct shrink_score u;
	CHECK(shrink_parse(&u, blob, bn) == SHRINK_OK, "loop-root-share parse");
	CHECK(shrink_share_runs(&u) == 3,
	      "loop-rooted run shares at depth 0 (depth_ok sees the root)");
	CHECK(shrink_finalize(&u) == SHRINK_OK, "loop-root-share finalize");
	CHECK(shrink_pattern_count(&u) == 3 && u.pat[u.npat - 1].shared,
	      "loop-root-share adds one pattern");
}

static void test_emit_roundtrip(void)
{
	const uint8_t R[] = { 0x74, 0x10, 0x5f, 0x74, 0x20, 0x4f, 0x19, 0x74, 0x30, 0x47 };
	uint8_t body[64];
	int n = 0;
	for (int k = 0; k < 3; k++) {
		memcpy(body + n, R, sizeof(R)); n += (int)sizeof(R);
		if (k < 2) body[n++] = 0x3c;
	}
	body[n++] = SHRINK_CMD_TERM;
	struct shrink_pat p[1];
	set_pat(&p[0], body, n);
	uint8_t start[] = { 0 };
	uint8_t blob[128];
	size_t bn = build_blob(blob, 0x03, 1, 1, start, p);

	struct shrink_score s;
	shrink_parse(&s, blob, bn);
	shrink_share_runs(&s);
	shrink_finalize(&s);

	uint8_t out[512];
	size_t on = shrink_emit_blob(&s, out, sizeof(out));
	CHECK(on > 0, "emit blob");
	struct shrink_score r;
	CHECK(shrink_parse(&r, out, on) == SHRINK_OK, "reparse emitted");
	CHECK(r.npat == s.npat, "reparse npat");
	int same = 1;
	for (int i = 0; i < s.npat; i++)
		if (r.pat[i].len != s.pat[i].len ||
		    memcmp(r.pat[i].b, s.pat[i].b, (size_t)s.pat[i].len) != 0) same = 0;
	CHECK(same, "reparse bodies match");

	FILE *f = fopen("build/fx-port/shrink/selftest_header.h", "w");
	if (f) {
		shrink_emit_header(&s, f, "selftest");
		fclose(f);
	} else {
		/* keep the test independent of the working directory */
		FILE *g = tmpfile();
		CHECK(g != NULL, "header emit to tmpfile");
		if (g) { shrink_emit_header(&s, g, "selftest"); fclose(g); }
	}
}

int main(void)
{
	test_parse();
	test_inline();
	test_share();
	test_share_forbidden();
	test_share_depth_gate();
	test_loop_detect();
	test_loop_operand_uses();
	test_validate();
	test_depth3_chain();
	test_loop_root_depth();
	test_emit_roundtrip();

	printf("selftest: %d passed, %d failed\n", passes, failures);
	return failures ? 1 : 0;
}
