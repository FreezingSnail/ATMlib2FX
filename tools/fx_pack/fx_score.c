/*
 * fx_score.c - see fx_score.h.
 */
#include "fx_score.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ATM_CMD_BLK_DELAY 0x40
#define ATM_CMD_BLK_IMMEDIATE 0x60
#define ATM_CMD_BLK_1_PARAMETER 0x70
#define ATM_CMD_BLK_N_PARAMETER 0x80

/* modern command ids used by the legacy translation */
#define MOD_SET_VOLUME 0x74
#define MOD_ADD_TRANSPOSITION 0x71
#define MOD_SET_TRANSPOSITION 0x70
#define MOD_TRANSPOSITION_OFF 0x60
#define MOD_SET_TEMPO 0x72
#define MOD_CALL 0x82
#define MOD_CALL_REPEAT 0x92
#define MOD_SLIDE_ON 0x91
#define MOD_SLIDE_ADV_ON 0xA1
#define MOD_SLIDE_OFF 0x81
#define MOD_ARPEGGIO_ON 0x94
#define MOD_ARPEGGIO_OFF 0x63
#define MOD_NOTECUT_ON 0x84
#define MOD_NOISE_RETRIG_ON 0x75
#define MOD_NOISE_RETRIG_OFF 0x64
#define MOD_LFO_ON 0xA6
#define MOD_LFO_OFF 0x86
#define MOD_GLISSANDO_ON 0x83
#define MOD_GLISSANDO_OFF 0x62
#define MOD_STOP 0x61
#define MOD_SHORT_DELAY 0x40
#define MOD_U8_DELAY 0x85
#define MOD_U16_DELAY 0x95

struct buf {
	uint8_t *data;
	size_t len, cap;
};

static int buf_put(struct buf *b, uint8_t v)
{
	if (b->len + 1 > b->cap) {
		size_t cap = b->cap ? b->cap * 2 : 256;
		uint8_t *p = realloc(b->data, cap);
		if (!p) return -1;
		b->data = p;
		b->cap = cap;
	}
	b->data[b->len++] = v;
	return 0;
}

static uint16_t le16(const uint8_t *p)
{
	return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

static void set_err(char *err, size_t errlen, const char *msg)
{
	if (err && errlen) snprintf(err, errlen, "%s", msg);
}

/* ------------------------------------------------------------------ */
/* module validation                                                  */

static int parse_modern(const uint8_t *in, size_t len, struct fx_score *out,
			char *err, size_t errlen)
{
	uint8_t np, nc;
	size_t header;

	if (len < 2) {
		set_err(err, errlen, "ATM_SCORE_FMT_FULL: score is shorter than the 2-byte header");
		return -1;
	}
	if (in[0] != 0x03) {
		char msg[160];
		snprintf(msg, sizeof(msg),
			 "expected ATM_SCORE_FMT_FULL (0x03) at score byte 0, "
			 "got 0x%02X", (unsigned)in[0]);
		set_err(err, errlen, msg);
		return -1;
	}
	np = in[1];
	if (np == 0) {
		set_err(err, errlen,
			"ATM_SCORE_FMT_FULL: pattern count at score byte 1 is 0");
		return -1;
	}
	header = (size_t)2 + (size_t)2 * np;
	if (len < header + 1) {
		set_err(err, errlen,
			"ATM_SCORE_FMT_FULL: score is truncated before the "
			"channel-info count");
		return -1;
	}
	nc = in[header];
	if (nc != FX_ENC_CHANNELS) {
		char msg[160];
		snprintf(msg, sizeof(msg),
			 "ATM_SCORE_FMT_FULL: channel count at score byte %zu "
			 "is %u; finite v1 requires %d", header,
			 (unsigned)nc, FX_ENC_CHANNELS);
		set_err(err, errlen, msg);
		return -1;
	}
	if (len < header + 1 + FX_ENC_CHANNELS) {
		set_err(err, errlen,
			"ATM_SCORE_FMT_FULL: score is truncated in the entry "
			"pattern array");
		return -1;
	}

	out->bytes = malloc(len ? len : 1);
	out->pattern_offset = malloc(sizeof(uint32_t) * np);
	if (!out->bytes || !out->pattern_offset) {
		set_err(err, errlen, "out of memory");
		return -1;
	}
	memcpy(out->bytes, in, len);
	out->len = len;
	out->num_patterns = np;
	out->num_channels = nc;
	out->source_len = len;
	out->source_format = FX_SCORE_MODERN_FULL;
	snprintf(out->format_name, sizeof(out->format_name), "ATM_SCORE_FMT_FULL");
	for (uint8_t i = 0; i < np; i++) {
		uint32_t off = le16(in + 2 + 2 * (size_t)i);
		if (off >= len) {
			char msg[160];
			snprintf(msg, sizeof(msg),
				 "ATM_SCORE_FMT_FULL: pattern %u offset 0x%04X "
				 "is outside the %zu-byte score",
				 (unsigned)i, (unsigned)off, len);
			set_err(err, errlen, msg);
			return -1;
		}
		out->pattern_offset[i] = off;
	}
	for (int ch = 0; ch < FX_ENC_CHANNELS; ch++) {
		out->entry[ch] = in[header + 1 + (size_t)ch];
		if (out->entry[ch] >= np) {
			char msg[160];
			snprintf(msg, sizeof(msg),
				 "ATM_SCORE_FMT_FULL: channel %d entry pattern %u "
				 "is out of range (pattern count %u)",
				 ch, (unsigned)out->entry[ch], (unsigned)np);
			set_err(err, errlen, msg);
			return -1;
		}
	}
	return 0;
}

/* ------------------------------------------------------------------ */
/* legacy v1 translation                                              */

static int emit_delay(struct buf *b, uint32_t n, int pat, size_t off,
		      char *err, size_t errlen)
{
	if (n == 0) {
		char msg[160];
		snprintf(msg, sizeof(msg),
			 "legacy delay of 0 at pattern %d offset 0x%04zX",
			 pat, off);
		set_err(err, errlen, msg);
		return -1;
	}
	if (n <= 32) {
		return buf_put(b, (uint8_t)(MOD_SHORT_DELAY + (n - 1)));
	}
	if (n <= 256) {
		if (buf_put(b, MOD_U8_DELAY)) return -1;
		return buf_put(b, (uint8_t)(n - 1));
	}
	if (n <= 65536) {
		if (buf_put(b, MOD_U16_DELAY)) return -1;
		if (buf_put(b, (uint8_t)((n - 1) >> 8))) return -1;
		return buf_put(b, (uint8_t)((n - 1) & 0xFF));
	}
	{
		char msg[160];
		snprintf(msg, sizeof(msg),
			 "legacy delay %u at pattern %d offset 0x%04zX exceeds "
			 "the 65536-tick finite-v1 schedule",
			 (unsigned)n, pat, off);
		set_err(err, errlen, msg);
		return -1;
	}
}

static int put_many(struct buf *b, const uint8_t *p, size_t n)
{
	for (size_t i = 0; i < n; i++)
		if (buf_put(b, p[i]) != 0) return -1;
	return 0;
}

static int legacy_vle(const uint8_t *src, size_t pos, size_t end,
		      uint32_t *value, size_t *consumed)
{
	uint32_t q = 0;
	uint8_t d;
	size_t n = 0;

	do {
		if (pos + n >= end) return -1;
		d = src[pos + n];
		n++;
		q = (q << 7) | (d & 0x7F);
	} while (d & 0x80);
	*value = q;
	*consumed = n;
	return 0;
}

static int translate_legacy_pattern(const uint8_t *src, size_t start, size_t end,
				    int pat, uint8_t num_patterns,
				    struct buf *out, char *err, size_t errlen)
{
	size_t p = start;

	while (p < end) {
		const uint8_t id = src[p];
		const size_t off = p;
		const size_t left = end - p;

		if (id < ATM_CMD_BLK_DELAY) {
			if (buf_put(out, id) != 0) return -1;
			p += 1;
		} else if (id < 0xA0) { /* 0x40..0x9F: pre-2.0 setup FX */
			const uint8_t sub = (uint8_t)(id - ATM_CMD_BLK_DELAY);
			switch (sub) {
			case 0: /* set volume */
				if (left < 2) goto truncated;
				if (put_many(out, (uint8_t[]){MOD_SET_VOLUME, src[p + 1]}, 2)) return -1;
				p += 2;
				break;
			case 1: /* volume slide on */
				if (left < 2) goto truncated;
				if (put_many(out, (uint8_t[]){MOD_SLIDE_ON, 0x00, src[p + 1]}, 3)) return -1;
				p += 2;
				break;
			case 2: /* volume slide on advanced */
				if (left < 3) goto truncated;
				if (put_many(out, (uint8_t[]){MOD_SLIDE_ADV_ON, 0x00, src[p + 1], src[p + 2]}, 4)) return -1;
				p += 3;
				break;
			case 3: /* volume slide off */
				if (put_many(out, (uint8_t[]){MOD_SLIDE_OFF, 0x00}, 2)) return -1;
				p += 1;
				break;
			case 4: /* frequency slide on */
				if (left < 2) goto truncated;
				if (put_many(out, (uint8_t[]){MOD_SLIDE_ON, 0x01, src[p + 1]}, 3)) return -1;
				p += 2;
				break;
			case 5: /* frequency slide on advanced */
				if (left < 3) goto truncated;
				if (put_many(out, (uint8_t[]){MOD_SLIDE_ADV_ON, 0x01, src[p + 1], src[p + 2]}, 4)) return -1;
				p += 3;
				break;
			case 6: /* frequency slide off */
				if (put_many(out, (uint8_t[]){MOD_SLIDE_OFF, 0x01}, 2)) return -1;
				p += 1;
				break;
			case 7: /* arpeggio on: (notes, timing) -> modern (timing, notes) */
				if (left < 3) goto truncated;
				if (put_many(out, (uint8_t[]){MOD_ARPEGGIO_ON, src[p + 2], src[p + 1]}, 3)) return -1;
				p += 3;
				break;
			case 8: /* arpeggio off */
				if (buf_put(out, MOD_ARPEGGIO_OFF) != 0) return -1;
				p += 1;
				break;
			case 9: /* noise retrig on */
				if (left < 2) goto truncated;
				if (put_many(out, (uint8_t[]){MOD_NOISE_RETRIG_ON, src[p + 1]}, 2)) return -1;
				p += 2;
				break;
			case 10: /* noise retrig off */
				if (buf_put(out, MOD_NOISE_RETRIG_OFF) != 0) return -1;
				p += 1;
				break;
			case 11: /* add transposition */
				if (left < 2) goto truncated;
				if (put_many(out, (uint8_t[]){MOD_ADD_TRANSPOSITION, src[p + 1]}, 2)) return -1;
				p += 2;
				break;
			case 12: /* set transposition */
				if (left < 2) goto truncated;
				if (put_many(out, (uint8_t[]){MOD_SET_TRANSPOSITION, src[p + 1]}, 2)) return -1;
				p += 2;
				break;
			case 13: /* transposition off */
				if (buf_put(out, MOD_TRANSPOSITION_OFF) != 0) return -1;
				p += 1;
				break;
			case 14: /* tremolo on: (depth, config) */
				if (left < 3) goto truncated;
				if (put_many(out, (uint8_t[]){MOD_LFO_ON, 0x00, src[p + 1], src[p + 2]}, 4)) return -1;
				p += 3;
				break;
			case 15: /* tremolo off */
				if (put_many(out, (uint8_t[]){MOD_LFO_OFF, 0x00}, 2)) return -1;
				p += 1;
				break;
			case 16: /* vibrato on */
				if (left < 3) goto truncated;
				if (put_many(out, (uint8_t[]){MOD_LFO_ON, 0x01, src[p + 1], src[p + 2]}, 4)) return -1;
				p += 3;
				break;
			case 17: /* vibrato off */
				if (put_many(out, (uint8_t[]){MOD_LFO_OFF, 0x01}, 2)) return -1;
				p += 1;
				break;
			case 18: /* glissando on */
				if (left < 2) goto truncated;
				if (put_many(out, (uint8_t[]){MOD_GLISSANDO_ON, src[p + 1]}, 2)) return -1;
				p += 2;
				break;
			case 19: /* glissando off */
				if (buf_put(out, MOD_GLISSANDO_OFF) != 0) return -1;
				p += 1;
				break;
			case 20: /* note cut on: (timing) */
				if (left < 2) goto truncated;
				if (put_many(out, (uint8_t[]){MOD_NOTECUT_ON, src[p + 1]}, 2)) return -1;
				p += 2;
				break;
			case 21: /* note cut off */
				if (buf_put(out, MOD_ARPEGGIO_OFF) != 0) return -1;
				p += 1;
				break;
			case 93: /* set tempo */
				if (left < 2) goto truncated;
				if (put_many(out, (uint8_t[]){MOD_SET_TEMPO, src[p + 1]}, 2)) return -1;
				p += 2;
				break;
			case 94: {
				char msg[200];
				snprintf(msg, sizeof(msg),
					 "legacy GOTO ADVANCED (0x%02X) at pattern %d "
					 "offset 0x%04zX is not supported in finite v1",
					 (unsigned)id, pat, off);
				set_err(err, errlen, msg);
				return -1;
			}
			case 95: /* stop channel -> shared PATTERN_END */
				if (buf_put(out, MOD_STOP) != 0) return -1;
				p += 1;
				break;
			default: {
				char msg[200];
				snprintf(msg, sizeof(msg),
					 "legacy setup-FX opcode 0x%02X at pattern %d "
					 "offset 0x%04zX is not supported",
					 (unsigned)id, pat, off);
				set_err(err, errlen, msg);
				return -1;
			}
			}
		} else if (id < 224) { /* 0xA0..0xDF: delay 1..64 */
			if (emit_delay(out, (uint32_t)(id - 159), pat, off, err, errlen))
				return -1;
			p += 1;
		} else if (id == 224) { /* long delay: VLE + 129 */
			uint32_t v = 0;
			size_t used = 0;
			if (legacy_vle(src, p + 1, end, &v, &used) != 0) goto truncated;
			if (emit_delay(out, v + 129, pat, off, err, errlen)) return -1;
			p += 1 + used;
		} else if (id < 252) {
			char msg[200];
			snprintf(msg, sizeof(msg),
				 "legacy reserved opcode 0x%02X at pattern %d "
				 "offset 0x%04zX is not supported",
				 (unsigned)id, pat, off);
			set_err(err, errlen, msg);
			return -1;
		} else if (id == 252) { /* CALL track */
			if (left < 2) goto truncated;
			if (src[p + 1] >= num_patterns) {
				char msg[200];
				snprintf(msg, sizeof(msg),
					 "legacy CALL target track %u at pattern %d "
					 "offset 0x%04zX is out of range (pattern count %u)",
					 (unsigned)src[p + 1], pat, off,
					 (unsigned)num_patterns);
				set_err(err, errlen, msg);
				return -1;
			}
			if (put_many(out, (uint8_t[]){MOD_CALL, src[p + 1]}, 2)) return -1;
			p += 2;
		} else if (id == 253) { /* CALL REPEAT count, track */
			if (left < 3) goto truncated;
			if (src[p + 2] >= num_patterns) {
				char msg[200];
				snprintf(msg, sizeof(msg),
					 "legacy CALL REPEAT target track %u at pattern %d "
					 "offset 0x%04zX is out of range (pattern count %u)",
					 (unsigned)src[p + 2], pat, off,
					 (unsigned)num_patterns);
				set_err(err, errlen, msg);
				return -1;
			}
			if (put_many(out, (uint8_t[]){MOD_CALL_REPEAT, src[p + 2], src[p + 1]}, 3)) return -1;
			p += 3;
		} else if (id == 254) { /* RETURN */
			if (buf_put(out, MOD_STOP) != 0) return -1;
			p += 1;
		} else { /* 255: embedded data */
			char msg[200];
			snprintf(msg, sizeof(msg),
				 "legacy EMBEDDED DATA (0xFF) at pattern %d "
				 "offset 0x%04zX is not supported in finite v1",
				 pat, off);
			set_err(err, errlen, msg);
			return -1;
		}
	}
	return 0;

truncated:
	{
		char msg[200];
		snprintf(msg, sizeof(msg),
			 "legacy command 0x%02X at pattern %d offset 0x%04zX "
			 "has operands past the pattern end",
			 (unsigned)src[p], pat, p);
		set_err(err, errlen, msg);
	}
	return -1;
}

static int parse_legacy(const uint8_t *in, size_t len, struct fx_score *out,
			char *err, size_t errlen)
{
	uint8_t np;
	size_t header, data_start;
	uint32_t *abs_off = NULL;
	uint32_t *new_off = NULL;
	struct buf translated;
	struct buf header_buf;
	int rc = -1;

	memset(&translated, 0, sizeof(translated));
	memset(&header_buf, 0, sizeof(header_buf));

	if (len < 1) {
		set_err(err, errlen, "legacy v1: score is empty");
		return -1;
	}
	np = in[0];
	if (np == 0) {
		set_err(err, errlen,
			"legacy v1: track count at score byte 0 is 0");
		return -1;
	}
	header = (size_t)1 + (size_t)2 * np + FX_ENC_CHANNELS;
	if (len < header) {
		set_err(err, errlen,
			"legacy v1: score is truncated before the track data");
		return -1;
	}
	data_start = header;

	abs_off = malloc(sizeof(uint32_t) * np);
	new_off = malloc(sizeof(uint32_t) * np);
	if (!abs_off || !new_off) {
		set_err(err, errlen, "out of memory");
		goto out;
	}
	for (uint8_t i = 0; i < np; i++) {
		uint32_t rel = le16(in + 1 + 2 * (size_t)i);
		if (data_start + rel >= len) {
			char msg[200];
			snprintf(msg, sizeof(msg),
				 "legacy v1: track %u offset 0x%04X is outside "
				 "the %zu-byte score", (unsigned)i,
				 (unsigned)rel, len);
			set_err(err, errlen, msg);
			goto out;
		}
		abs_off[i] = (uint32_t)(data_start + rel);
	}
	for (uint8_t i = 0; i < np; i++) {
		for (uint8_t j = 0; j < np; j++) {
			if (i != j && abs_off[i] == abs_off[j]) {
				char msg[200];
				snprintf(msg, sizeof(msg),
					 "legacy v1: tracks %u and %u share the "
					 "same start offset 0x%04X",
					 (unsigned)i, (unsigned)j,
					 (unsigned)abs_off[i]);
				set_err(err, errlen, msg);
				goto out;
			}
		}
	}

	/* Translate each track extent into one modern pattern buffer. */
	for (uint8_t i = 0; i < np; i++) {
		size_t start = abs_off[i];
		size_t end = len;
		for (uint8_t j = 0; j < np; j++) {
			if (abs_off[j] > start && abs_off[j] < end)
				end = abs_off[j];
		}
		new_off[i] = (uint32_t)((size_t)7 + 2 * np + translated.len);
		if (translate_legacy_pattern(in, start, end, (int)i, np,
					     &translated, err, errlen) != 0)
			goto out;
	}

	/* Build the modern full-format header + translated pattern data. */
	{
		const size_t h = (size_t)7 + 2 * np;
		if (buf_put(&header_buf, 0x03) != 0) goto oom;
		if (buf_put(&header_buf, np) != 0) goto oom;
		for (uint8_t i = 0; i < np; i++) {
			if (buf_put(&header_buf, (uint8_t)(new_off[i] & 0xFF)) != 0) goto oom;
			if (buf_put(&header_buf, (uint8_t)((new_off[i] >> 8) & 0xFF)) != 0) goto oom;
		}
		if (buf_put(&header_buf, FX_ENC_CHANNELS) != 0) goto oom;
		for (int ch = 0; ch < FX_ENC_CHANNELS; ch++) {
			uint8_t entry = in[1 + 2 * (size_t)np + (size_t)ch];
			if (entry >= np) {
				char msg[200];
				snprintf(msg, sizeof(msg),
					 "legacy v1: channel %d entry track %u is "
					 "out of range (track count %u)",
					 ch, (unsigned)entry, (unsigned)np);
				set_err(err, errlen, msg);
				goto out;
			}
			if (buf_put(&header_buf, entry) != 0) goto oom;
		}
		if (header_buf.len != h) goto oom;

		out->len = h + translated.len;
		out->bytes = malloc(out->len ? out->len : 1);
		out->pattern_offset = malloc(sizeof(uint32_t) * np);
		if (!out->bytes || !out->pattern_offset) goto oom;
		memcpy(out->bytes, header_buf.data, h);
		memcpy(out->bytes + h, translated.data, translated.len);
		for (uint8_t i = 0; i < np; i++)
			out->pattern_offset[i] = new_off[i];
		out->num_patterns = np;
		out->num_channels = FX_ENC_CHANNELS;
		out->source_len = len;
		out->source_format = FX_SCORE_LEGACY_V1;
		snprintf(out->format_name, sizeof(out->format_name),
			 "legacy-v1 (pre-2.0)");
		for (int ch = 0; ch < FX_ENC_CHANNELS; ch++)
			out->entry[ch] = in[1 + 2 * (size_t)np + (size_t)ch];
	}
	rc = 0;
	goto out;

oom:
	set_err(err, errlen, "out of memory");

out:
	free(abs_off);
	free(new_off);
	free(translated.data);
	free(header_buf.data);
	return rc;
}

/* ------------------------------------------------------------------ */

int fx_score_parse(const uint8_t *input, size_t input_len,
		   enum fx_score_format want, struct fx_score *out,
		   char *err, size_t errlen)
{
	memset(out, 0, sizeof(*out));
	if (!input || input_len == 0) {
		set_err(err, errlen, "empty score");
		return -1;
	}
	if (want == FX_SCORE_MODERN_FULL) {
		return parse_modern(input, input_len, out, err, errlen);
	}
	if (want == FX_SCORE_LEGACY_V1) {
		return parse_legacy(input, input_len, out, err, errlen);
	}

	/* Auto: prefer the modern full header when it validates. */
	{
		char modern_err[256] = "";
		if (parse_modern(input, input_len, out, modern_err,
				 sizeof(modern_err)) == 0)
			return 0;
		if (out->bytes) { free(out->bytes); out->bytes = NULL; }
		if (out->pattern_offset) {
			free(out->pattern_offset);
			out->pattern_offset = NULL;
		}
		{
			char legacy_err[256] = "";
			if (parse_legacy(input, input_len, out, legacy_err,
					 sizeof(legacy_err)) == 0)
				return 0;
			if (out->bytes) { free(out->bytes); out->bytes = NULL; }
			if (out->pattern_offset) {
				free(out->pattern_offset);
				out->pattern_offset = NULL;
			}
			if (err && errlen) {
				snprintf(err, errlen,
					 "score is neither ATM_SCORE_FMT_FULL nor "
					 "legacy v1: [%s] / [%s]",
					 modern_err, legacy_err);
			}
		}
	}
	return -1;
}

void fx_score_free(struct fx_score *score)
{
	if (!score) return;
	free(score->bytes);
	free(score->pattern_offset);
	score->bytes = NULL;
	score->pattern_offset = NULL;
	score->len = 0;
}

struct fx_score_patterns fx_score_view(const struct fx_score *score)
{
	struct fx_score_patterns view;
	view.bytes = score->bytes;
	view.len = score->len;
	view.num_channels = score->num_channels;
	view.num_patterns = score->num_patterns;
	for (int ch = 0; ch < FX_ENC_CHANNELS; ch++)
		view.entry[ch] = score->entry[ch];
	view.pattern_offset = score->pattern_offset;
	view.format_name = score->format_name;
	return view;
}

int fx_score_format_from_name(const char *name)
{
	if (!name) return FX_SCORE_AUTO;
	if (!strcmp(name, "auto")) return FX_SCORE_AUTO;
	if (!strcmp(name, "modern") || !strcmp(name, "full") ||
	    !strcmp(name, "ATM_SCORE_FMT_FULL"))
		return FX_SCORE_MODERN_FULL;
	if (!strcmp(name, "legacy") || !strcmp(name, "legacy-v1"))
		return FX_SCORE_LEGACY_V1;
	return -1;
}
