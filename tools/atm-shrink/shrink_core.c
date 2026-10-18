/*
 * shrink_core.c - reusable offline song-shrink engine (ATMlib2FX-hlh.3).
 * See shrink_core.h for the format and transform contract.
 */
#include "shrink_core.h"

#include <string.h>
#include <stdlib.h>

uint8_t shrink_cmd_size(uint8_t id)
{
	if (id < 0x40) return 1;              /* note on/off              */
	if (id < 0x60) return 1;              /* short delay              */
	if (id < 0x70) return 1;              /* immediate                */
	if (id < 0x80) return 2;              /* one parameter byte       */
	return (uint8_t)(1 + (((id >> 4) & 0x07) + 1)); /* n params       */
}

static int is_call_id(uint8_t id)
{
	return id == SHRINK_CMD_CALL || id == SHRINK_CMD_CALL_REPEAT;
}

static int cmd_forbidden_in_run(uint8_t id)
{
	return id == SHRINK_CMD_TERM ||
	       is_call_id(id) ||
	       id == SHRINK_CMD_SET_TEMPO ||
	       id == SHRINK_CMD_ADD_TEMPO ||
	       id == SHRINK_CMD_LOOP;
}

/* ------------------------------------------------------------------ */
int shrink_format_capable(const struct shrink_score *s)
{
	return (s->fmt & 0x02) != 0;
}

int shrink_parse(struct shrink_score *s, const uint8_t *blob, size_t len)
{
	memset(s, 0, sizeof(*s));
	if (len < 3) return SHRINK_ERR_FORMAT;

	s->fmt = blob[0];
	if (!(s->fmt & 0x02)) return SHRINK_ERR_FORMAT;

	uint8_t npat = blob[1];
	if (npat == 0 || npat > SHRINK_MAX_PATTERNS) return SHRINK_ERR_RANGE;

	size_t hdr = 2 + 2u * (size_t)npat;
	if (len < hdr + 1) return SHRINK_ERR_FORMAT;

	uint8_t nch = blob[hdr];
	if (nch == 0 || nch > SHRINK_MAX_CHANNELS) return SHRINK_ERR_RANGE;
	if (len < hdr + 1 + nch) return SHRINK_ERR_FORMAT;

	s->num_channels = nch;
	for (uint8_t i = 0; i < nch; i++)
		s->start[i] = blob[hdr + 1 + i];

	size_t off[SHRINK_MAX_PATTERNS];
	for (uint8_t i = 0; i < npat; i++)
		off[i] = (size_t)blob[2 + 2 * i] | ((size_t)blob[3 + 2 * i] << 8);

	s->npat = npat;
	for (uint8_t i = 0; i < npat; i++) {
		size_t b = off[i];
		size_t e = (i + 1 < npat) ? off[i + 1] : len;
		if (b > len || e > len || e < b) return SHRINK_ERR_RANGE;
		size_t l = e - b;
		/* The packed struct carries tail alignment padding after the last
		 * pattern; a valid body always ends with the terminal opcode, so a
		 * trailing 0x00 byte can only be padding. */
		if (i + 1 == npat)
			while (l > 0 && blob[b + l - 1] == 0x00) l--;
		if (l > SHRINK_MAX_PATLEN) return SHRINK_ERR_RANGE;
		memcpy(s->pat[i].b, blob + b, l);
		s->pat[i].len = (int)l;
		s->pat[i].alive = 1;
	}
	return SHRINK_OK;
}

void shrink_parse_sfx(struct shrink_score *s, const uint8_t *blob, size_t len)
{
	if (len < 1) return;
	s->have_sfx = 1;
	s->sfx_fmt = blob[0];
	size_t l = len - 1;
	if (l > SHRINK_MAX_PATLEN) l = SHRINK_MAX_PATLEN;
	memcpy(s->sfx_pattern, blob + 1, l);
	s->sfx_len = (int)l;
}

/* ------------------------------------------------------------------ */
/* Call-nesting depth: maximum depth at which each pattern can be entered.
 *
 * Roots at depth 0 are the channel entry patterns and every
 * SET_LOOP_PATTERN target: the library restarts a stopped channel (which
 * always stopped at pstack_index 0) from ch->loop_pattern_index and then
 * executes the target exactly like a channel entry (src/atm_synth.c
 * start_loop). A CALL chain rooted only at a loop target is therefore
 * depth-counted like a channel-entry chain. */
static void compute_incoming(const struct shrink_score *s, int inc[])
{
	for (int i = 0; i < s->npat; i++) inc[i] = -1;
	for (uint8_t c = 0; c < s->num_channels; c++)
		if (s->start[c] < s->npat) inc[s->start[c]] = 0;

	for (int p = 0; p < s->npat; p++) {
		if (!s->pat[p].alive) continue;
		const uint8_t *b = s->pat[p].b;
		int len = s->pat[p].len;
		int i = 0;
		while (i < len) {
			uint8_t id = b[i];
			uint8_t sz = shrink_cmd_size(id);
			if (i + sz > len) break;
			if (id == SHRINK_CMD_LOOP && b[i + 1] < s->npat)
				inc[b[i + 1]] = 0;
			i += sz;
		}
	}

	int changed = 1;
	int guard = 0;
	while (changed && guard++ < SHRINK_MAX_PATTERNS * 2) {
		changed = 0;
		for (int p = 0; p < s->npat; p++) {
			if (!s->pat[p].alive || inc[p] < 0) continue;
			const uint8_t *b = s->pat[p].b;
			int len = s->pat[p].len;
			int i = 0;
			while (i < len) {
				uint8_t id = b[i];
				uint8_t sz = shrink_cmd_size(id);
				if (i + sz > len) break;
				if (is_call_id(id) && b[i + 1] < s->npat) {
					int q = b[i + 1];
					int cand = inc[p] + 1;
					if (cand > SHRINK_STACK_DEPTH + 1)
						cand = SHRINK_STACK_DEPTH + 1;
					if (cand > inc[q]) { inc[q] = cand; changed = 1; }
				}
				i += sz;
			}
		}
	}
}

int shrink_max_depth(const struct shrink_score *s)
{
	int inc[SHRINK_MAX_PATTERNS];
	compute_incoming(s, inc);
	int m = 0;
	for (int i = 0; i < s->npat; i++)
		if (s->pat[i].alive && inc[i] > m) m = inc[i];
	return m; /* maximum pstack index (0 = no nesting) */
}

/* ------------------------------------------------------------------ */
/* Transform 1: loop normalization.
 *
 * The canonical ATMlib2 loop is ATM_CMD_M_SET_LOOP_PATTERN: it is the only
 * construct that can restart a finished score without a tick gap (130c9ca).
 * A score that already uses it needs no change; a one-shot score has no
 * re-entry to fold. Legacy GOTO/REPEAT back-edges only exist in the pre-2.x
 * raw byte-array format, which this engine rejects at parse time (no pattern
 * table), so the transform is a conservation check here: it never rewrites
 * playback, it only reports the loop status. */
int shrink_loop_normalize(struct shrink_score *s)
{
	s->loop_present = 0;
	for (int p = 0; p < s->npat; p++) {
		if (!s->pat[p].alive) continue;
		const uint8_t *b = s->pat[p].b;
		int len = s->pat[p].len;
		int i = 0;
		while (i < len) {
			uint8_t id = b[i];
			uint8_t sz = shrink_cmd_size(id);
			if (i + sz > len) break;
			if (id == SHRINK_CMD_LOOP) s->loop_present = 1;
			i += sz;
		}
	}
	s->loop_normalized = s->loop_present;
	return 0;
}

/* ------------------------------------------------------------------ */
/* Transform 2: inline single-use patterns with body length L <= 5.
 *
 * A pattern that is called exactly once (plain CALL, never an entry point or
 * a SET_LOOP_PATTERN target) costs its body plus a 2-byte table entry plus a
 * 2-byte CALL, and the body ends with a 1-byte RETURN. Inlining drops the
 * table entry, the call and the return; per the ATMlib2FX-hlh.3 cost model
 * the body must fit in those 5 bytes (table entry 2 B + RETURN 1 B + CALL
 * 2 B).
 *
 * A SET_LOOP_PATTERN operand is a use: the loop target must stay a live
 * pattern (its restart pointer may never dangle), so it is never inlined
 * away. Finalize remaps the operand when other patterns are dropped. */
int shrink_inline_single_use(struct shrink_score *s)
{
	int saved = 0;
	int progress = 1;
	while (progress) {
		progress = 0;

		int entry[SHRINK_MAX_PATTERNS] = {0};
		int refs[SHRINK_MAX_PATTERNS] = {0};
		int call_only[SHRINK_MAX_PATTERNS];
		int caller[SHRINK_MAX_PATTERNS];
		int cpos[SHRINK_MAX_PATTERNS];
		for (int i = 0; i < s->npat; i++) {
			call_only[i] = 1;
			caller[i] = -1;
			cpos[i] = -1;
		}
		for (uint8_t c = 0; c < s->num_channels; c++)
			if (s->start[c] < s->npat) entry[s->start[c]] = 1;

		for (int p = 0; p < s->npat; p++) {
			if (!s->pat[p].alive) continue;
			const uint8_t *b = s->pat[p].b;
			int len = s->pat[p].len;
			int i = 0;
			while (i < len) {
				uint8_t id = b[i];
				uint8_t sz = shrink_cmd_size(id);
				if (i + sz > len) break;
				if (is_call_id(id)) {
					int q = b[i + 1];
					if (q < s->npat && s->pat[q].alive) {
						refs[q]++;
						if (id != SHRINK_CMD_CALL || q == p)
							call_only[q] = 0;
						if (refs[q] == 1) { caller[q] = p; cpos[q] = i; }
						else call_only[q] = 0;
					}
				} else if (id == SHRINK_CMD_LOOP) {
					/* The loop operand is a pattern reference:
					 * count it as a use and never inline its
					 * target away. */
					int q = b[i + 1];
					if (q < s->npat && s->pat[q].alive) {
						refs[q]++;
						call_only[q] = 0;
					}
				}
				i += sz;
			}
		}

		for (int q = 0; q < s->npat; q++) {
			if (!s->pat[q].alive) continue;
			if (entry[q] || refs[q] != 1 || !call_only[q]) continue;
			if (s->pat[q].len < 1 || s->pat[q].len > SHRINK_INLINE_MAX_LEN) continue;
			if (s->pat[q].b[s->pat[q].len - 1] != SHRINK_CMD_TERM) continue;

			int p = caller[q];
			int pos = cpos[q];
			if (p < 0 || pos < 0 || p == q) continue;

			/* Replace the 2-byte CALL at cpos with body[0 .. len-2]. */
			uint8_t tmp[SHRINK_MAX_PATLEN];
			int t = 0;
			for (int i = 0; i < pos; i++) tmp[t++] = s->pat[p].b[i];
			for (int i = 0; i < s->pat[q].len - 1; i++) tmp[t++] = s->pat[q].b[i];
			for (int i = pos + 2; i < s->pat[p].len; i++) tmp[t++] = s->pat[p].b[i];
			memcpy(s->pat[p].b, tmp, (size_t)t);
			s->pat[p].len = t;

			s->pat[q].alive = 0;
			saved += 5;
			progress = 1;
			break;
		}
	}
	return saved;
}

/* ------------------------------------------------------------------ */
/* Transform 3: share repeated command runs via CALL.
 *
 * A run of L bytes that occurs u times is worth a new pattern when
 *   u*L > L + 1 + 2 + 2u
 * (L body + 1 return + 2 table entry + 2u call sites). Runs must not contain
 * CALL, pattern end, tempo or loop commands; use sites must stay within the
 * call-nesting depth limit. */
static int count_occurrences(const struct shrink_score *s, int skip,
			     const uint8_t *run, int L, int *max_depth_ok,
			     const int *inc)
{
	int count = 0;
	*max_depth_ok = 1;
	for (int p = 0; p < s->npat; p++) {
		if (!s->pat[p].alive || p == skip || s->pat[p].shared) continue;
		const uint8_t *b = s->pat[p].b;
		int len = s->pat[p].len;
		int i = 0;
		while (i < len) {
			uint8_t sz = shrink_cmd_size(b[i]);
			if (i + sz > len) break;
			if (len - i >= L && memcmp(b + i, run, (size_t)L) == 0) {
				count++;
				if (inc[p] < 0 || inc[p] > 1) *max_depth_ok = 0;
				i += L;
			} else {
				i += sz;
			}
		}
	}
	return count;
}

int shrink_share_runs(struct shrink_score *s)
{
	int total = 0;

	for (;;) {
		int inc[SHRINK_MAX_PATTERNS];
		compute_incoming(s, inc);

		int best_saving = 0;
		int best_p = -1, best_o = -1, best_L = -1;

		for (int p = 0; p < s->npat; p++) {
			if (!s->pat[p].alive || s->pat[p].shared) continue;
			const uint8_t *b = s->pat[p].b;
			int len = s->pat[p].len;

			int pos[SHRINK_MAX_PATLEN];
			int np = 0;
			int i = 0;
			while (i < len) {
				pos[np++] = i;
				uint8_t sz = shrink_cmd_size(b[i]);
				if (i + sz > len) { np--; break; }
				i += sz;
			}
			pos[np] = len;

			for (int a = 0; a < np; a++) {
				for (int e = a + 1; e <= np; e++) {
					int L = pos[e] - pos[a];
					if (L < 2) continue;

					int forb = 0;
					for (int k = a; k < e; k++)
						if (cmd_forbidden_in_run(b[pos[k]])) { forb = 1; break; }
					if (forb) continue;

					const uint8_t *run = b + pos[a];
					int depth_ok = 1;
					int u = count_occurrences(s, -1, run, L, &depth_ok, inc);
					if (u < 2 || !depth_ok) continue;

					int saving = u * L - (L + 1 + 2 + 2 * u);
					if (saving > best_saving) {
						best_saving = saving;
						best_p = p;
						best_o = pos[a];
						best_L = L;
					}
				}
			}
		}

		if (best_saving <= 0 || best_p < 0) break;
		if (s->npat + 1 > SHRINK_MAX_PATTERNS) break;

		/* Materialize the shared pattern. */
		int S = s->npat;
		memset(&s->pat[S], 0, sizeof(s->pat[S]));
		memcpy(s->pat[S].b, s->pat[best_p].b + best_o, (size_t)best_L);
		s->pat[S].b[best_L] = SHRINK_CMD_TERM;
		s->pat[S].len = best_L + 1;
		s->pat[S].alive = 1;
		s->pat[S].shared = 1;
		s->npat++;

		/* Replace every non-overlapping occurrence with CALL S. */
		int replaced = 0;
		for (int p = 0; p < s->npat; p++) {
			if (!s->pat[p].alive || p == S || s->pat[p].shared) continue;
			uint8_t tmp[SHRINK_MAX_PATLEN];
			int t = 0;
			const uint8_t *b = s->pat[p].b;
			int len = s->pat[p].len;
			int i = 0;
			while (i < len) {
				uint8_t sz = shrink_cmd_size(b[i]);
				if (i + sz > len) break;
				if (len - i >= best_L && memcmp(b + i, s->pat[S].b, (size_t)best_L) == 0) {
					tmp[t++] = SHRINK_CMD_CALL;
					tmp[t++] = (uint8_t)S;
					i += best_L;
					replaced++;
				} else {
					for (int k = 0; k < sz; k++) tmp[t++] = b[i + k];
					i += sz;
				}
			}
			memcpy(s->pat[p].b, tmp, (size_t)t);
			s->pat[p].len = t;
		}

		if (replaced < 2) {
			/* Nothing actually replaced (should not happen); back off. */
			s->pat[S].alive = 0;
			s->npat--;
			break;
		}
		total += best_saving;
	}
	return total;
}

/* ------------------------------------------------------------------ */
/* Structural validity of a finalized score: every pattern reference
 * (CALL / CALL_REPEAT operand, SET_LOOP_PATTERN operand, channel entry point)
 * must address a live pattern in range, and every body must decode fully. */
int shrink_validate(const struct shrink_score *s)
{
	if (s->npat < 1 || s->npat > SHRINK_MAX_PATTERNS) return SHRINK_ERR_RANGE;
	if (s->num_channels < 1 || s->num_channels > SHRINK_MAX_CHANNELS)
		return SHRINK_ERR_RANGE;
	for (uint8_t c = 0; c < s->num_channels; c++)
		if (s->start[c] >= (uint8_t)s->npat || !s->pat[s->start[c]].alive)
			return SHRINK_ERR_RANGE;
	for (int p = 0; p < s->npat; p++) {
		if (!s->pat[p].alive) return SHRINK_ERR_RANGE;
		const uint8_t *b = s->pat[p].b;
		int len = s->pat[p].len;
		if (len < 1 || len > SHRINK_MAX_PATLEN) return SHRINK_ERR_RANGE;
		int i = 0;
		while (i < len) {
			uint8_t id = b[i];
			uint8_t sz = shrink_cmd_size(id);
			if (i + sz > len) return SHRINK_ERR_RANGE;
			if ((is_call_id(id) || id == SHRINK_CMD_LOOP) &&
			    (b[i + 1] >= (uint8_t)s->npat ||
			     !s->pat[b[i + 1]].alive))
				return SHRINK_ERR_RANGE;
			i += sz;
		}
	}
	return SHRINK_OK;
}

/* ------------------------------------------------------------------ */
/* Finalize: drop dead patterns, remap CALL / SET_LOOP_PATTERN operands and
 * entry points, then assert the result is reference-valid. */
int shrink_finalize(struct shrink_score *s)
{
	int map[SHRINK_MAX_PATTERNS];
	for (int i = 0; i < s->npat; i++) map[i] = -1;
	int n = 0;
	for (int i = 0; i < s->npat; i++)
		if (s->pat[i].alive) map[i] = n++;
	if (n == 0) return SHRINK_ERR_RANGE;

	struct shrink_pat out[SHRINK_MAX_PATTERNS];
	for (int i = 0; i < s->npat; i++) {
		if (!s->pat[i].alive) continue;
		out[map[i]] = s->pat[i];
	}

	for (int i = 0; i < n; i++) {
		uint8_t *b = out[i].b;
		int len = out[i].len;
		int j = 0;
		while (j < len) {
			uint8_t id = b[j];
			uint8_t sz = shrink_cmd_size(id);
			if (j + sz > len) break;
			if (is_call_id(id) || id == SHRINK_CMD_LOOP) {
				/* CALL and SET_LOOP_PATTERN both address
				 * patterns by table index; both must follow
				 * the compaction. A dangling reference is a
				 * corrupt result, not something to emit. */
				int q = b[j + 1];
				if (q >= s->npat || map[q] < 0)
					return SHRINK_ERR_RANGE;
				b[j + 1] = (uint8_t)map[q];
			}
			j += sz;
		}
	}

	for (int i = 0; i < n; i++) s->pat[i] = out[i];
	s->npat = n;

	for (uint8_t c = 0; c < s->num_channels; c++)
		if (s->start[c] < SHRINK_MAX_PATTERNS && map[s->start[c]] >= 0)
			s->start[c] = (uint8_t)map[s->start[c]];

	return shrink_validate(s);
}

/* ------------------------------------------------------------------ */
int shrink_header_bytes(const struct shrink_score *s)
{
	return 2 + 2 * s->npat + 1 + (int)s->num_channels;
}

int shrink_pattern_bytes(const struct shrink_score *s)
{
	int t = 0;
	for (int i = 0; i < s->npat; i++)
		if (s->pat[i].alive) t += s->pat[i].len;
	return t;
}

int shrink_score_bytes(const struct shrink_score *s)
{
	return shrink_header_bytes(s) + shrink_pattern_bytes(s);
}

int shrink_pattern_count(const struct shrink_score *s)
{
	int n = 0;
	for (int i = 0; i < s->npat; i++) if (s->pat[i].alive) n++;
	return n;
}

/* ------------------------------------------------------------------ */
size_t shrink_emit_blob(const struct shrink_score *s, uint8_t *buf, size_t cap)
{
	size_t hdr = (size_t)shrink_header_bytes(s);
	size_t total = hdr + (size_t)shrink_pattern_bytes(s);
	if (total > cap || s->npat > 255) return 0;

	buf[0] = s->fmt;
	buf[1] = (uint8_t)s->npat;
	size_t off = hdr;
	for (int i = 0; i < s->npat; i++) {
		buf[2 + 2 * i] = (uint8_t)(off & 0xFF);
		buf[3 + 2 * i] = (uint8_t)((off >> 8) & 0xFF);
		off += (size_t)s->pat[i].len;
	}
	size_t h = 2 + 2 * (size_t)s->npat;
	buf[h] = s->num_channels;
	for (uint8_t c = 0; c < s->num_channels; c++)
		buf[h + 1 + c] = s->start[c];

	size_t w = hdr;
	for (int i = 0; i < s->npat; i++) {
		memcpy(buf + w, s->pat[i].b, (size_t)s->pat[i].len);
		w += (size_t)s->pat[i].len;
	}
	return w;
}

static void emit_bytes(FILE *f, const uint8_t *b, int len, const char *indent)
{
	fprintf(f, "%s{", indent);
	for (int i = 0; i < len; i++)
		fprintf(f, "%s0x%02x", (i == 0) ? " " : ", ", b[i]);
	fprintf(f, " },\n");
}

int shrink_emit_header(const struct shrink_score *s, FILE *f, const char *name)
{
	fprintf(f, "/* Generated by tools/atm-shrink (ATMlib2FX-hlh.3). Do not edit. */\n");
	fprintf(f, "/* source: %s */\n", name);
	fprintf(f, "#ifndef SONG_H\n#define SONG_H\n\n");
	fprintf(f, "#ifndef PROGMEM\n#define PROGMEM\n#endif\n");
	fprintf(f, "#include <stddef.h>\n\n");

	fprintf(f, "const PROGMEM struct score_data {\n");
	fprintf(f, "  uint8_t fmt;\n");
	fprintf(f, "  uint8_t num_patterns;\n");
	fprintf(f, "  uint16_t patterns_offset[%d];\n", s->npat);
	fprintf(f, "  uint8_t num_channels;\n");
	fprintf(f, "  uint8_t start_patterns[%u];\n", (unsigned)s->num_channels);
	for (int i = 0; i < s->npat; i++)
		fprintf(f, "  uint8_t pattern%d[%d];\n", i, s->pat[i].len);
	fprintf(f, "} score = {\n");
	fprintf(f, "  0x%02x, 0x%02x,\n", s->fmt, (unsigned)s->npat & 0xFF);
	fprintf(f, "  {\n");
	for (int i = 0; i < s->npat; i++)
		fprintf(f, "    offsetof(struct score_data, pattern%d),\n", i);
	fprintf(f, "  },\n");
	fprintf(f, "  0x%02x,\n", (unsigned)s->num_channels);
	fprintf(f, "  {");
	for (uint8_t c = 0; c < s->num_channels; c++)
		fprintf(f, "%s0x%02x", c ? ", " : " ", s->start[c]);
	fprintf(f, " },\n");
	for (int i = 0; i < s->npat; i++)
		emit_bytes(f, s->pat[i].b, s->pat[i].len, "  ");
	fprintf(f, "};\n");

	if (s->have_sfx) {
		fprintf(f, "\nconst PROGMEM struct sfx1_data {\n");
		fprintf(f, "  uint8_t fmt;\n");
		fprintf(f, "  uint8_t pattern0[%d];\n", s->sfx_len);
		fprintf(f, "} sfx1 = {\n");
		fprintf(f, "  0x%02x,\n", (unsigned)s->sfx_fmt);
		emit_bytes(f, s->sfx_pattern, s->sfx_len, "  ");
		fprintf(f, "};\n");
	}

	fprintf(f, "\n#endif /* SONG_H */\n");
	return 0;
}

int shrink_emit_flat_header(const struct shrink_score *s, FILE *f, const char *name)
{
	uint8_t buf[1 << 16];
	size_t n = shrink_emit_blob(s, buf, sizeof(buf));
	if (!n) return -1;

	fprintf(f, "/* Generated by tools/atm-shrink (ATMlib2FX-hlh.3). Do not edit. */\n");
	fprintf(f, "/* source: %s */\n", name);
	fprintf(f, "#ifndef ATMLIB_SHRUNK_SCORE_H\n#define ATMLIB_SHRUNK_SCORE_H\n\n");
	fprintf(f, "#include <stdint.h>\n");
	fprintf(f, "#include <avr/pgmspace.h>\n\n");
	fprintf(f, "#define SCORE_BYTES %zu\n", n);
	fprintf(f, "const uint8_t score[] PROGMEM = {\n");
	for (size_t i = 0; i < n; i++) {
		if (i % 12 == 0) fprintf(f, "   ");
		fprintf(f, " 0x%02x,", buf[i]);
		if (i % 12 == 11 || i + 1 == n) fprintf(f, "\n");
	}
	fprintf(f, "};\n\n#endif /* ATMLIB_SHRUNK_SCORE_H */\n");
	return 0;
}
