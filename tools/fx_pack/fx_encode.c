/*
 * fx_encode.c - see fx_encode.h.
 *
 * The traversal logic is ported from the retained hlh.5 spike converter
 * (research/fx/tools/fx_compact_spike/fx_compile_compact.c) so the fixture
 * stream stays byte-identical, with these production additions:
 *   - reusable, file-agnostic API (no compiled-in song);
 *   - source-event admission diagnostics for every hard failure;
 *   - corrected long-delay scheduling (original library adds one tick);
 *   - explicit UTF-8 gap/length/bitmap validation and a structural validator.
 */
#include "fx_encode.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PATTERN_STACK_DEPTH (3)
#define GROUP_CAP (512)

#define ATM_CMD_BLK_DELAY (0x40)
#define ATM_CMD_BLK_IMMEDIATE (0x60)
#define ATM_CMD_BLK_1_PARAMETER (0x70)
#define ATM_CMD_BLK_N_PARAMETER (0x80)

#define ATM_CMD_I_PATTERN_END (0x61)
#define ATM_CMD_1P_SET_TEMPO (0x72)
#define ATM_CMD_NP_CALL (2)
#define ATM_CMD_NP_SET_LOOP_PATTERN (0)
#define ATM_CMD_NP_LONG_DELAY (5)

/* ------------------------------------------------------------------ */
/* primitives                                                         */

uint8_t fx_cmd_size(uint8_t id)
{
	if (id < ATM_CMD_BLK_DELAY)        return 1; /* note on/off            */
	if (id < ATM_CMD_BLK_IMMEDIATE)    return 1; /* immediate (delay)      */
	if (id < ATM_CMD_BLK_1_PARAMETER)  return 1; /* immediate              */
	if (id < ATM_CMD_BLK_N_PARAMETER)  return 2; /* one parameter byte     */
	return (uint8_t)(1 + (((id >> 4) & 0x07) + 1)); /* n parameter bytes  */
}

uint8_t fx_gap_nbytes(uint32_t gap)
{
	if (gap <= 0x7F)   return 1;
	if (gap <= 0x7EFF) return 2;
	if (gap <= 0xFFFF) return 3;
	return 0;
}

uint8_t *fx_put_gap(uint8_t *dst, uint32_t gap)
{
	if (gap <= 0x7F) {
		*dst++ = (uint8_t)gap;
	} else if (gap <= 0x7EFF) {
		*dst++ = (uint8_t)(0x80 | (gap >> 8));
		*dst++ = (uint8_t)(gap & 0xFF);
	} else {
		*dst++ = 0xFF;
		*dst++ = (uint8_t)((gap >> 8) & 0xFF);
		*dst++ = (uint8_t)(gap & 0xFF);
	}
	return dst;
}

int fx_decode_gap(const uint8_t *src, size_t avail, uint32_t *gap, uint32_t *used)
{
	uint8_t b0;
	if (avail < 1) return -1;
	b0 = src[0];
	if (b0 < 0x80) {
		if (gap) *gap = b0;
		if (used) *used = 1;
		return 0;
	}
	if (b0 != 0xFF) {
		if (avail < 2) return -1;
		if (gap) *gap = ((uint32_t)(b0 & 0x7F) << 8) | src[1];
		if (used) *used = 2;
		return 0;
	}
	if (avail < 3) return -1;
	if (gap) *gap = ((uint32_t)src[1] << 8) | src[2];
	if (used) *used = 3;
	return 0;
}

/* ------------------------------------------------------------------ */
/* traversal                                                          */

struct pat_state {
	const uint8_t *cmd;
	uint8_t pattern;
	uint8_t rep;
};

#define FX_DELAY_STOP (0xFFFFFFFFu)

struct chan {
	struct pat_state stack[PATTERN_STACK_DEPTH];
	uint8_t sp;
	uint32_t delay;   /* 32-bit so operand 0xFFFF + 1 schedules 65536     */
	uint8_t active;
};

static const uint8_t *pattern_start(const struct fx_score_patterns *sc,
				    uint8_t pattern_index)
{
	return sc->bytes + sc->pattern_offset[pattern_index];
}

static void chan_reset(const struct fx_score_patterns *sc, struct chan *c,
		       uint8_t entry)
{
	memset(c, 0, sizeof(*c));
	c->sp = 0;
	c->active = 1;
	c->stack[0].cmd = pattern_start(sc, entry);
	c->stack[0].pattern = entry;
	c->stack[0].rep = 0;
}

static int fail_event(char *err, size_t errlen, const char *what,
		      int ch, uint8_t pattern, size_t offset, uint8_t command)
{
	if (err && errlen) {
		snprintf(err, errlen,
			 "%s (channel %d, pattern %u, score offset 0x%04zX, "
			 "command 0x%02X)",
			 what, ch, (unsigned)pattern, offset, (unsigned)command);
	}
	return -1;
}

/* Record the source of the first command a group emits this tick. */
static void mark_first(uint16_t n, size_t off, uint8_t pattern,
		       uint8_t *first_pattern, uint32_t *first_offset)
{
	if (n != 0) return;
	if (first_pattern) *first_pattern = pattern;
	if (first_offset) *first_offset = (uint32_t)off;
}

/* Append the musical commands a channel runs this tick into out[].
 * Traversal-only commands (delays, CALL/REPEAT, PATTERN_END/RETURN) are
 * consumed for scheduling; a genuine channel stop is emitted as 0x61.
 * Returns 0 on success, -1 on an admission failure with a source diagnostic. */
static int step_channel(const struct fx_score_patterns *sc, struct chan *c,
			int chidx, uint8_t *out, uint16_t *out_len,
			int tempo_override, uint8_t *first_pattern,
			uint32_t *first_offset, char *err, size_t errlen)
{
	uint16_t n = 0;

	if (first_pattern) *first_pattern = 0;
	if (first_offset) *first_offset = 0;

	while (c->delay == 0) {
		struct pat_state *ps = &c->stack[c->sp];
		const uint8_t *cmd_ptr = ps->cmd;
		size_t off;
		uint8_t id, sz;

		if (cmd_ptr < sc->bytes || cmd_ptr >= sc->bytes + sc->len) {
			return fail_event(err, errlen,
				"pattern ran past the end of the score",
				chidx, ps->pattern,
				(size_t)(cmd_ptr - sc->bytes), 0);
		}
		off = (size_t)(cmd_ptr - sc->bytes);
		id = cmd_ptr[0];
		sz = fx_cmd_size(id);
		if (off + sz > sc->len) {
			return fail_event(err, errlen,
				"command operands extend past the end of the score",
				chidx, ps->pattern, off, id);
		}

		if (id < ATM_CMD_BLK_DELAY) {
			/* note on/off */
			if (n + 1 > GROUP_CAP) {
				return fail_event(err, errlen,
					"channel group exceeds the encoder cap",
					chidx, ps->pattern, off, id);
			}
			mark_first(n, off, ps->pattern, first_pattern, first_offset);
			out[n++] = id;
			ps->cmd += sz;
		} else if (id < ATM_CMD_BLK_IMMEDIATE) {			/* short delay: traversal only */
			c->delay = (uint32_t)(id - 63);
			ps->cmd += sz;
		} else if (id < ATM_CMD_BLK_1_PARAMETER) {
			if (id == ATM_CMD_I_PATTERN_END) {
				/* shared PATTERN_END/RETURN/STOP semantics */
				if (ps->rep > 0) {
					ps->rep--;
					ps->cmd = pattern_start(sc, ps->pattern);
				} else if (c->sp == 0) {
					/* genuine channel stop: the device sees it */
					c->active = 0;
					c->delay = FX_DELAY_STOP;
					if (n + 1 > GROUP_CAP) {
						return fail_event(err, errlen,
							"channel group exceeds the encoder cap",
							chidx, ps->pattern, off, id);
					}
					mark_first(n, off, ps->pattern,
						   first_pattern, first_offset);
					out[n++] = ATM_CMD_I_PATTERN_END;
				} else {
					c->sp--;
				}
			} else {
				if (n + 1 > GROUP_CAP) {
					return fail_event(err, errlen,
						"channel group exceeds the encoder cap",
						chidx, ps->pattern, off, id);
				}
				mark_first(n, off, ps->pattern,
					   first_pattern, first_offset);
				out[n++] = id;
				ps->cmd += sz;
			}
		} else if (id < ATM_CMD_BLK_N_PARAMETER) {
			/* one parameter byte */
			if (n + 2 > GROUP_CAP) {
				return fail_event(err, errlen,
					"channel group exceeds the encoder cap",
					chidx, ps->pattern, off, id);
			}
			mark_first(n, off, ps->pattern, first_pattern, first_offset);
			out[n++] = id;
			out[n++] = cmd_ptr[1];
			if (tempo_override != 0 && id == ATM_CMD_1P_SET_TEMPO) {
				out[n - 1] = (uint8_t)tempo_override;
			}
			ps->cmd += sz;
		} else {
			const uint8_t cid = (uint8_t)(id & 0x0F);
			const uint8_t csz = (uint8_t)(((id >> 4) & 0x07) + 1);
			const uint8_t total = (uint8_t)(1 + csz);
			const uint8_t *advanced = cmd_ptr + total;

			if (cid == ATM_CMD_NP_CALL) {
				const uint8_t new_track = cmd_ptr[1];
				if (new_track >= sc->num_patterns) {
					return fail_event(err, errlen,
						"CALL target pattern is out of range",
						chidx, ps->pattern, off, id);
				}
				if (c->sp < PATTERN_STACK_DEPTH - 1 &&
				    new_track != ps->pattern) {
					/* parent resumes after the call operands */
					ps->cmd = advanced;
					c->sp++;
					c->stack[c->sp].cmd = pattern_start(sc, new_track);
					c->stack[c->sp].pattern = new_track;
					c->stack[c->sp].rep = csz > 1 ? cmd_ptr[2] : 0;
				} else {
					/* skipped call at the stack limit or to the
					 * current pattern: matches the original */
					ps->cmd = advanced;
				}
			} else if (cid == ATM_CMD_NP_SET_LOOP_PATTERN) {
				return fail_event(err, errlen,
					"SET_LOOP_PATTERN is not supported in finite v1",
					chidx, ps->pattern, off, id);
			} else if (cid == ATM_CMD_NP_LONG_DELAY) {
				/* traversal only. The original library stores
				 * operand+1, so the reschedule count is v+1. */
				const uint32_t v = csz > 1
					? ((uint32_t)cmd_ptr[1] << 8) | cmd_ptr[2]
					: cmd_ptr[1];
				c->delay = v + 1;
				ps->cmd = advanced;
			} else {
				/* effect command: copy verbatim */
				if (n + total > GROUP_CAP) {
					return fail_event(err, errlen,
						"channel group exceeds the encoder cap",
						chidx, ps->pattern, off, id);
				}
				mark_first(n, off, ps->pattern,
					   first_pattern, first_offset);
				for (uint8_t i = 0; i < total; i++)
					out[n++] = cmd_ptr[i];
				ps->cmd = advanced;
			}
		}
	}
	*out_len = n;
	return 0;
}

/* ------------------------------------------------------------------ */
/* growable byte buffer                                               */

struct bytes {
	uint8_t *data;
	size_t len, cap;
};

static int bytes_reserve(struct bytes *b, size_t extra)
{
	if (b->len + extra > b->cap) {
		size_t cap = b->cap ? b->cap : 1024;
		uint8_t *p;
		while (cap < b->len + extra) cap *= 2;
		p = realloc(b->data, cap);
		if (!p) return -1;
		b->data = p;
		b->cap = cap;
	}
	return 0;
}

/* ------------------------------------------------------------------ */
/* collected due passes (group bytes live in one arena)               */

struct pass {
	uint32_t tick;
	uint8_t bitmap;
	uint8_t glen[FX_ENC_CHANNELS];
	size_t goff[FX_ENC_CHANNELS];
	uint8_t src_pattern[FX_ENC_CHANNELS];
	uint32_t src_offset[FX_ENC_CHANNELS];
};

struct passes {
	struct pass *items;
	size_t count, cap;
	uint8_t *arena;
	size_t alen, acap;
};

static int passes_add(struct passes *ps, const uint32_t tick,
		      const uint8_t bitmap, const uint8_t glen[FX_ENC_CHANNELS],
		      const uint8_t src_pattern[FX_ENC_CHANNELS],
		      const uint32_t src_offset[FX_ENC_CHANNELS],
		      uint8_t groups[FX_ENC_CHANNELS][GROUP_CAP])
{
	struct pass *p;
	if (ps->count == ps->cap) {
		size_t cap = ps->cap ? ps->cap * 2 : 256;
		struct pass *items = realloc(ps->items, cap * sizeof(*items));
		if (!items) return -1;
		ps->items = items;
		ps->cap = cap;
	}
	p = &ps->items[ps->count++];
	memset(p, 0, sizeof(*p));
	p->tick = tick;
	p->bitmap = bitmap;
	for (int ch = 0; ch < FX_ENC_CHANNELS; ch++) {
		p->glen[ch] = glen[ch];
		p->src_pattern[ch] = src_pattern[ch];
		p->src_offset[ch] = src_offset[ch];
		p->goff[ch] = ps->alen;
		if (glen[ch]) {
			if (ps->alen + glen[ch] > ps->acap) {
				size_t cap = ps->acap ? ps->acap : 1024;
				uint8_t *a;
				while (cap < ps->alen + glen[ch]) cap *= 2;
				a = realloc(ps->arena, cap);
				if (!a) return -1;
				ps->arena = a;
				ps->acap = cap;
			}
			memcpy(ps->arena + ps->alen, groups[ch], glen[ch]);
			ps->alen += glen[ch];
		}
	}
	return 0;
}

/* ------------------------------------------------------------------ */
/* structural validation (mirrors the device preflight)               */

int fx_stream_validate(const uint8_t *stream, size_t len, uint16_t ring,
		       char *err, size_t errlen)
{
	size_t pos;

	if (!stream || len < 2) {
		if (err) snprintf(err, errlen, "stream is too short (%zu bytes)", len);
		return -1;
	}
	if (stream[0] != FX_ENC_STREAM_MAGIC) {
		if (err) snprintf(err, errlen,
			"bad stream magic 0x%02X (expected 0x%02X)",
			(unsigned)stream[0], (unsigned)FX_ENC_STREAM_MAGIC);
		return -1;
	}

	pos = 1;
	while (pos < len) {
		const uint8_t *rec = stream + pos;
		uint8_t reclen = rec[0];
		uint32_t gap, used, p;

		if (reclen == FX_ENC_STREAM_END) {
			if (pos + 1 != len) {
				if (err) snprintf(err, errlen,
					"END byte at stream offset 0x%04zX is not "
					"the end of the stream", pos);
				return -1;
			}
			return 0;
		}
		if (reclen < 5) {
			if (err) snprintf(err, errlen,
				"record length %u < 5 at stream offset 0x%04zX",
				(unsigned)reclen, pos);
			return -1;
		}
		if (reclen > ring) {
			if (err) snprintf(err, errlen,
				"record length %u > ring %u at stream offset 0x%04zX",
				(unsigned)reclen, (unsigned)ring, pos);
			return -1;
		}
		if (pos + reclen > len) {
			if (err) snprintf(err, errlen,
				"record at stream offset 0x%04zX extends past "
				"the stream end", pos);
			return -1;
		}

		p = 1;
		if (fx_decode_gap(rec + p, reclen - p, &gap, &used) != 0) {
			if (err) snprintf(err, errlen,
				"truncated gap varint at stream offset 0x%04zX",
				pos);
			return -1;
		}
		p += used;
		if (p >= reclen) {
			if (err) snprintf(err, errlen,
				"record at stream offset 0x%04zX has no bitmap", pos);
			return -1;
		}
		{
			uint8_t bitmap = rec[p++];
			if (bitmap == 0) {
				if (err) snprintf(err, errlen,
					"record bitmap 0 (nonprogressing) at "
					"stream offset 0x%04zX", pos);
				return -1;
			}
			if (bitmap & 0xF0) {
				if (err) snprintf(err, errlen,
					"record bitmap 0x%02X > 15 at stream "
					"offset 0x%04zX", (unsigned)bitmap, pos);
				return -1;
			}
			for (uint8_t ch = 0; ch < FX_ENC_CHANNELS; ch++) {
				if (!(bitmap & (1u << ch))) continue;
				if (p >= reclen) {
					if (err) snprintf(err, errlen,
						"record at stream offset 0x%04zX "
						"missing group length for channel %u",
						pos, (unsigned)ch);
					return -1;
				}
				{
					uint8_t glen = rec[p++];
					uint32_t end;
					if (glen == 0) {
						if (err) snprintf(err, errlen,
							"record at stream offset "
							"0x%04zX has glen 0 for channel %u",
							pos, (unsigned)ch);
						return -1;
					}
					end = p + glen;
					if (end > reclen) {
						if (err) snprintf(err, errlen,
							"record at stream offset "
							"0x%04zX group length for "
							"channel %u overflows the record",
							pos, (unsigned)ch);
						return -1;
					}
					while (p < end) {
						uint8_t id = rec[p];
						uint8_t sz = fx_cmd_size(id);
						if (p + sz > end) {
							if (err) snprintf(err, errlen,
								"record at stream "
								"offset 0x%04zX command "
								"0x%02X overflows the "
								"channel %u group",
								pos, (unsigned)id,
								(unsigned)ch);
							return -1;
						}
						p += sz;
					}
				}
			}
			if (p != reclen) {
				if (err) snprintf(err, errlen,
					"record at stream offset 0x%04zX has %u "
					"trailing bytes", pos,
					(unsigned)(reclen - p));
				return -1;
			}
		}
		pos += reclen;
	}

	if (err) snprintf(err, errlen, "stream has no END record");
	return -1;
}

/* ------------------------------------------------------------------ */
/* encoder                                                            */

static int set_result_error(struct fx_encode_result *out, const char *msg)
{
	snprintf(out->error, sizeof(out->error), "%s", msg);
	return -1;
}

int fx_encode(const struct fx_score_patterns *sc,
	      const struct fx_encode_options *opt,
	      struct fx_encode_result *out)
{
	struct chan chans[FX_ENC_CHANNELS];
	uint8_t groups[FX_ENC_CHANNELS][GROUP_CAP];
	uint16_t glen[FX_ENC_CHANNELS];
	uint8_t glen8[FX_ENC_CHANNELS];
	struct passes passes;
	struct bytes stream;
	uint8_t *tick_bytes = NULL;
	uint32_t tick_cap;
	long ticks = 0;
	uint32_t payload_total = 0, max_group = 0, max_record = 0;
	uint32_t framing_total = 0;
	int stopped_at = -1;
	int rc = -1;

	memset(out, 0, sizeof(*out));
	memset(&passes, 0, sizeof(passes));
	memset(&stream, 0, sizeof(stream));

	if (!sc || !sc->bytes || !sc->pattern_offset) {
		return set_result_error(out, "no score supplied to the encoder");
	}
	if (sc->num_channels != FX_ENC_CHANNELS) {
		char msg[128];
		snprintf(msg, sizeof(msg),
			 "expected %d channels, got %u",
			 FX_ENC_CHANNELS, (unsigned)sc->num_channels);
		return set_result_error(out, msg);
	}
	if (sc->num_patterns == 0) {
		return set_result_error(out, "score has no patterns");
	}
	for (uint8_t i = 0; i < sc->num_patterns; i++) {
		if (sc->pattern_offset[i] >= sc->len) {
			char msg[160];
			snprintf(msg, sizeof(msg),
				 "pattern %u offset 0x%04X is outside the "
				 "score (%zu bytes)",
				 (unsigned)i, (unsigned)sc->pattern_offset[i],
				 sc->len);
			return set_result_error(out, msg);
		}
	}
	for (int ch = 0; ch < FX_ENC_CHANNELS; ch++) {
		if (sc->entry[ch] >= sc->num_patterns) {
			char msg[160];
			snprintf(msg, sizeof(msg),
				 "channel %d entry pattern %u is out of range "
				 "(num_patterns %u)", ch, (unsigned)sc->entry[ch],
				 (unsigned)sc->num_patterns);
			return set_result_error(out, msg);
		}
	}

	tick_cap = opt->tick_cap ? opt->tick_cap : FX_ENC_DEFAULT_TICKS;
	if (opt->ring < 5 || opt->ring > 256) {
		return set_result_error(out,
			"ring must be in [5, 256] (finite-v1 admission limit)");
	}

	tick_bytes = calloc((size_t)tick_cap + 1, 1);
	if (!tick_bytes) return set_result_error(out, "out of memory");

	for (int ch = 0; ch < FX_ENC_CHANNELS; ch++)
		chan_reset(sc, &chans[ch], sc->entry[ch]);

	while (ticks < (long)tick_cap) {
		uint8_t bitmap = 0;
		uint32_t group_bytes = 0;
		uint8_t src_pattern[FX_ENC_CHANNELS] = { 0, 0, 0, 0 };
		uint32_t src_offset[FX_ENC_CHANNELS] = { 0, 0, 0, 0 };

		for (int ch = 0; ch < FX_ENC_CHANNELS; ch++) {
			glen[ch] = 0;
			if (step_channel(sc, &chans[ch], ch, groups[ch],
					 &glen[ch], opt->tempo_override,
					 &src_pattern[ch], &src_offset[ch],
					 out->error, sizeof(out->error)) != 0) {
				out->stream = stream.data;
				out->stream_len = stream.len;
				free(tick_bytes);
				free(passes.items);
				free(passes.arena);
				return -1;
			}
		}

		for (int ch = 0; ch < FX_ENC_CHANNELS; ch++) {
			if (glen[ch]) {
				if (glen[ch] > 255) {
					snprintf(out->error, sizeof(out->error),
						 "tick %u channel %d group is %u "
						 "bytes > 255 (record would exceed "
						 "the one-byte length field)",
						 (unsigned)ticks, ch,
						 (unsigned)glen[ch]);
					rc = -1;
					goto done;
				}
				glen8[ch] = (uint8_t)glen[ch];
				bitmap |= (uint8_t)(1u << ch);
				group_bytes += glen[ch];
			} else {
				glen8[ch] = 0;
			}
		}
		if (bitmap != 0) {
			if (passes_add(&passes, (uint32_t)ticks, bitmap, glen8,
				       src_pattern, src_offset, groups) != 0) {
				rc = set_result_error(out, "out of memory");
				goto done;
			}
			payload_total += group_bytes;
			if (group_bytes > max_group) max_group = group_bytes;
		}

		ticks++;

		{
			uint8_t any_active = 0;
			for (int ch = 0; ch < FX_ENC_CHANNELS; ch++)
				if (chans[ch].active) any_active = 1;
			if (!any_active) {
				stopped_at = (int)ticks;
				break;
			}
		}

		for (int ch = 0; ch < FX_ENC_CHANNELS; ch++)
			if (chans[ch].delay != FX_DELAY_STOP) chans[ch].delay--;
	}

	/* --- serialize --- */
	if (bytes_reserve(&stream, 1) != 0) {
		rc = set_result_error(out, "out of memory");
		goto done;
	}
	stream.data[stream.len++] = FX_ENC_STREAM_MAGIC;

	for (size_t i = 0; i < passes.count; i++) {
		const struct pass *p = &passes.items[i];
		uint32_t gap;
		uint32_t body;
		uint32_t reclen;
		uint8_t bitmap = p->bitmap;

		/* gap = effect-only ticks strictly between this pass and the next */
		if (i + 1 < passes.count) {
			uint32_t next = passes.items[i + 1].tick;
			if (next <= p->tick) {
				rc = set_result_error(out,
					"internal error: pass ticks are not increasing");
				goto done;
			}
			gap = next - p->tick - 1;
		} else {
			gap = 0;
		}
		if (fx_gap_nbytes(gap) == 0) {
			size_t used;
			snprintf(out->error, sizeof(out->error),
				 "gap %u between tick %u and the next pass "
				 "exceeds the 65535 varint maximum",
				 (unsigned)gap, (unsigned)p->tick);
			used = strlen(out->error);
			if (i + 1 < passes.count) {
				const struct pass *nx = &passes.items[i + 1];
				for (int ch = 0; ch < FX_ENC_CHANNELS; ch++) {
					if (!(nx->bitmap & (1u << ch))) continue;
					snprintf(out->error + used,
						 sizeof(out->error) - used,
						 " (next pass tick %u channel %d "
						 "pattern %u offset 0x%04X)",
						 (unsigned)nx->tick, ch,
						 (unsigned)nx->src_pattern[ch],
						 (unsigned)nx->src_offset[ch]);
					break;
				}
			}
			rc = -1;
			goto done;
		}
		if (bitmap == 0) {
			snprintf(out->error, sizeof(out->error),
				 "pass at tick %u has bitmap 0 (nonprogressing)",
				 (unsigned)p->tick);
			rc = -1;
			goto done;
		}
		if (bitmap & 0xF0) {
			snprintf(out->error, sizeof(out->error),
				 "pass at tick %u has bitmap 0x%02X > 15",
				 (unsigned)p->tick, (unsigned)bitmap);
			rc = -1;
			goto done;
		}

		body = (uint32_t)fx_gap_nbytes(gap) + 1;
		for (int ch = 0; ch < FX_ENC_CHANNELS; ch++) {
			if (!(bitmap & (1u << ch))) continue;
			if (p->glen[ch] == 0) {
				snprintf(out->error, sizeof(out->error),
					 "tick %u channel %d has glen 0 with "
					 "bitmap bit set", (unsigned)p->tick, ch);
				rc = -1;
				goto done;
			}
			body += 1u + p->glen[ch];
		}
		reclen = 1 + body;

		if (reclen < 5) {
			snprintf(out->error, sizeof(out->error),
				 "record at tick %u is %u bytes < 5",
				 (unsigned)p->tick, (unsigned)reclen);
			rc = -1;
			goto done;
		}
		if (reclen > opt->ring) {
			size_t used;
			snprintf(out->error, sizeof(out->error),
				 "record at tick %u is %u bytes > ring %u "
				 "(channels", (unsigned)p->tick, (unsigned)reclen,
				 (unsigned)opt->ring);
			used = strlen(out->error);
			for (int ch = 0; ch < FX_ENC_CHANNELS; ch++) {
				if (!(bitmap & (1u << ch))) continue;
				used += (size_t)snprintf(
					out->error + used,
					sizeof(out->error) - used,
					" %d:%uB pattern %u offset 0x%04X", ch,
					(unsigned)p->glen[ch],
					(unsigned)p->src_pattern[ch],
					(unsigned)p->src_offset[ch]);
			}
			snprintf(out->error + used,
				 sizeof(out->error) - used, ")");
			rc = -1;
			goto done;
		}
		if (reclen > 255) {
			snprintf(out->error, sizeof(out->error),
				 "record at tick %u is %u bytes > 255",
				 (unsigned)p->tick, (unsigned)reclen);
			rc = -1;
			goto done;
		}

		if (bytes_reserve(&stream, reclen) != 0) {
			rc = set_result_error(out, "out of memory");
			goto done;
		}
		stream.data[stream.len++] = (uint8_t)reclen;
		{
			uint8_t *w = fx_put_gap(stream.data + stream.len, gap);
			stream.len = (size_t)(w - stream.data);
		}
		stream.data[stream.len++] = bitmap;
		for (int ch = 0; ch < FX_ENC_CHANNELS; ch++) {
			if (!(bitmap & (1u << ch))) continue;
			stream.data[stream.len++] = p->glen[ch];
			memcpy(stream.data + stream.len,
			       passes.arena + p->goff[ch], p->glen[ch]);
			stream.len += p->glen[ch];
		}
		if (reclen > max_record) max_record = reclen;
		framing_total += reclen;
		if (p->tick <= (uint32_t)tick_cap)
			tick_bytes[p->tick] = (uint8_t)reclen;
	}

	if (bytes_reserve(&stream, 1) != 0) {
		rc = set_result_error(out, "out of memory");
		goto done;
	}
	stream.data[stream.len++] = FX_ENC_STREAM_END;
	if (stopped_at >= 0 && stopped_at <= (int)tick_cap)
		tick_bytes[stopped_at] = 1;

	{
		long ticks_span = stopped_at >= 0 ? stopped_at : ticks;
		for (int k = 1; k <= FX_ENC_MAX_WINDOW; k++) {
			uint64_t sum = 0;
			for (long i = 0; i < ticks_span; i++) {
				sum += tick_bytes[i];
				if (i >= k) sum -= tick_bytes[i - k];
				if (i >= k - 1 && sum > out->meta.max_window[k]) {
					out->meta.max_window[k] = (uint32_t)sum;
					out->meta.max_window_at[k] = i - k + 1;
				}
			}
		}
		out->meta.ticks_span = (uint32_t)ticks_span;
	}
	out->meta.stopped_at = stopped_at;
	out->meta.passes = (uint32_t)passes.count;
	out->meta.payload_bytes = payload_total;
	out->meta.max_group = max_group;
	out->meta.max_record = max_record;
	out->meta.framing_bytes = framing_total;
	out->stream = stream.data;
	out->stream_len = stream.len;
	stream.data = NULL;
	stream.len = stream.cap = 0;

	/* Defense in depth: the emitted bytes must pass the same admission
	 * checks the device applies. */
	if (fx_stream_validate(out->stream, out->stream_len, opt->ring,
			       out->error, sizeof(out->error)) != 0) {
		rc = -1;
		goto done;
	}
	rc = 0;

done:
	free(tick_bytes);
	free(passes.items);
	free(passes.arena);
	free(stream.data);
	if (rc != 0) {
		free(out->stream);
		out->stream = NULL;
		out->stream_len = 0;
	}
	return rc;
}

void fx_encode_result_free(struct fx_encode_result *out)
{
	if (!out) return;
	free(out->stream);
	out->stream = NULL;
	out->stream_len = 0;
}
