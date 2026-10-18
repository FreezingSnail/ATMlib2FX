/*
 * fx_score.h - score loading for the ATMlib2FX compact converter
 * (ATMlib2FX-hlh.7).
 *
 * Two finite-v1 inputs are supported:
 *
 *   1. ATM_SCORE_FMT_FULL (0x03): the current library/authoring layout
 *      (<fmt> <pattern-count> <u16 LE offsets> <channel-count> <entries>
 *      <patterns>). Command bytes use the modern ATMlib encoding.
 *
 *   2. Legacy ATMlib v1 raw tracker layout (the pre-2.0 "Song music[]" form):
 *      <track-count> <u16 LE offsets relative to pattern-data start>
 *      <4 entry tracks> <tracks>. Commands use the pre-2.0 encoding; the
 *      loader translates them to the modern encoding so the shared encoder
 *      and device decoder are unchanged. Volume/slide magnitudes are copied
 *      numerically (the pre-2.0 volume range was 0..63).
 *
 * Both loaders produce a modern-encoded flat score plus absolute per-pattern
 * offsets. Everything outside this input matrix is rejected with a diagnostic
 * that names the offending header field or source event.
 */
#ifndef FX_SCORE_H
#define FX_SCORE_H

#include <stddef.h>
#include <stdint.h>

#include "fx_encode.h"

enum fx_score_format {
	FX_SCORE_AUTO = 0,
	FX_SCORE_MODERN_FULL = 1,
	FX_SCORE_LEGACY_V1 = 2
};

struct fx_score {
	enum fx_score_format source_format;
	char format_name[32];
	uint8_t *bytes;      /* modern-encoded flat score (owned)             */
	size_t len;
	uint8_t num_patterns;
	uint8_t num_channels;
	uint8_t entry[FX_ENC_CHANNELS];
	uint32_t *pattern_offset; /* absolute offsets into bytes (owned)      */
	size_t source_len;        /* original input length                   */
};

/* Parse `input` into `out`. `want` selects auto-detection or a forced format.
 * Returns 0 on success, else non-zero with `err` naming the offending field. */
int fx_score_parse(const uint8_t *input, size_t input_len,
		   enum fx_score_format want, struct fx_score *out,
		   char *err, size_t errlen);

void fx_score_free(struct fx_score *score);

/* View for fx_encode(). Valid until fx_score_free(). */
struct fx_score_patterns fx_score_view(const struct fx_score *score);

/* Parse a format name (for --format). Returns -1 on an unknown name. */
int fx_score_format_from_name(const char *name);

#endif /* FX_SCORE_H */
