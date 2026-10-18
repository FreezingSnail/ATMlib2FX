/*
 * shrink_core.h - reusable offline song-shrink engine for ATMlib2 bytecode
 * (ATMlib2FX-hlh.3).
 *
 * This is host-only build tooling. It re-implements the score traversal
 * semantics of the original library (the same model as
 * research/fx/tools/fx_compile_stream.c) and never touches the device code.
 *
 * The engine works on the packed ATMlib2 score layout used by the current
 * library (ATM_SCORE_FMT_FULL / FULL_MONO):
 *
 *   byte 0      fmt (bit0 = entry pattern array, bit1 = pattern table)
 *   byte 1      num_patterns
 *   word[n]     patterns_offset[n]   (little endian, from score base)
 *   byte        num_channels
 *   byte[m]     start_patterns[m]    (entry pattern per channel)
 *   ...         pattern bodies
 *
 * A pattern body is a sequence of commands that always terminates with
 * ATM_CMD_I_PATTERN_END (0x61, also RETURN/STOP: it pops the call stack or
 * stops the channel when the stack is empty).
 *
 * Transforms implemented (per ATMlib2FX-hlh.3):
 *   1. shrink_loop_normalize()  - loop idiom detection / normalization.
 *   2. shrink_inline_single_use()- inline single-use patterns with L <= 5.
 *   3. shrink_share_runs()      - share repeated command runs via CALL.
 *
 * All transforms are value preserving for playback; the call-nesting depth is
 * rejected if it would exceed ATM_PATTERN_STACK_DEPTH (3).
 */
#ifndef ATM_SHRINK_CORE_H
#define ATM_SHRINK_CORE_H

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>

#define SHRINK_OK 0
#define SHRINK_ERR_FORMAT (-1)
#define SHRINK_ERR_RANGE  (-2)

/* Mirrors src/atm_synth.h (ATM_PATTERN_STACK_DEPTH). */
#define SHRINK_STACK_DEPTH 3

#define SHRINK_MAX_PATTERNS 96
#define SHRINK_MAX_PATLEN   4096
#define SHRINK_MAX_CHANNELS 4

/* Command opcodes (see src/atm_cmd_constants.h). */
#define SHRINK_CMD_TERM        0x61u /* PATTERN_END / RETURN / STOP */
#define SHRINK_CMD_SET_TEMPO   0x72u /* single parameter             */
#define SHRINK_CMD_ADD_TEMPO   0x73u /* single parameter             */
#define SHRINK_CMD_LOOP        0x80u /* ATM_CMD_P_SET_LOOP_PATTERN   */
#define SHRINK_CMD_CALL        0x82u /* ATM_CMD_P_CALL               */
#define SHRINK_CMD_CALL_REPEAT 0x92u /* ATM_CMD_P_CALL_REPEAT        */

/* Inline cost threshold: pattern table entry (2) + RETURN (1) + CALL (2). */
#define SHRINK_INLINE_MAX_LEN 5

struct shrink_pat {
	uint8_t b[SHRINK_MAX_PATLEN];
	int len;
	int alive;
	int shared; /* created by the run-sharing pass           */
	int use;    /* static CALL/CALL_REPEAT reference count    */
	int use_call;/* the single reference is a plain CALL?     */
};

struct shrink_score {
	uint8_t fmt;
	uint8_t num_channels;
	uint8_t start[SHRINK_MAX_CHANNELS];
	int npat;
	struct shrink_pat pat[SHRINK_MAX_PATTERNS];

	/* minimal-mono SFX (unchanged; emitted alongside) */
	int have_sfx;
	uint8_t sfx_fmt;
	uint8_t sfx_pattern[SHRINK_MAX_PATLEN];
	int sfx_len;

	/* last transform report (set by shrink_loop_normalize) */
	int loop_present;
	int loop_normalized;
};

/* Command byte size, exactly as the library decoder consumes it. */
uint8_t shrink_cmd_size(uint8_t id);

/* Parse a packed score blob (not an sfx). Returns SHRINK_OK or SHRINK_ERR_*. */
int shrink_parse(struct shrink_score *s, const uint8_t *blob, size_t len);

/* Parse a minimal-mono SFX blob (fmt byte + single pattern body). */
void shrink_parse_sfx(struct shrink_score *s, const uint8_t *blob, size_t len);

/* True when the score uses a format this engine can rewrite (bit1 set). */
int shrink_format_capable(const struct shrink_score *s);

/* Transforms. Each returns the number of bytes saved (>=0). */
int shrink_loop_normalize(struct shrink_score *s);
int shrink_inline_single_use(struct shrink_score *s);
int shrink_share_runs(struct shrink_score *s);

/* Drop dead patterns, remap CALL / CALL_REPEAT and SET_LOOP_PATTERN operands
 * plus entry points, and validate the result. Call once after all transforms
 * and before metrics/emit. Returns SHRINK_OK or SHRINK_ERR_RANGE when a
 * pattern reference would dangle. */
int shrink_finalize(struct shrink_score *s);

/* Structural validity of a finalized score: every pattern reference is in
 * range and alive, every channel entry point is valid, every body decodes
 * fully. Returns SHRINK_OK or SHRINK_ERR_RANGE. shrink_finalize() runs this
 * as its post-condition assert. */
int shrink_validate(const struct shrink_score *s);

/* Metrics. */
int shrink_header_bytes(const struct shrink_score *s);
int shrink_pattern_bytes(const struct shrink_score *s);
int shrink_score_bytes(const struct shrink_score *s); /* header + bodies     */
int shrink_pattern_count(const struct shrink_score *s);
int shrink_max_depth(const struct shrink_score *s);   /* max pstack index    */

/* Emit a packed score blob (returns byte count, or 0 if it does not fit). */
size_t shrink_emit_blob(const struct shrink_score *s, uint8_t *buf, size_t cap);

/* Emit a drop-in song.h (defines `score` and, when present, `sfx1`).
 * `name` is used in the provenance comment. Returns 0 on success. */
int shrink_emit_header(const struct shrink_score *s, FILE *f, const char *name);

/* Emit a packed `const uint8_t score[] PROGMEM` header (the tools/atm-music
 * generated-score layout), for consumers that use `(const uint8_t *)score`. */
int shrink_emit_flat_header(const struct shrink_score *s, FILE *f, const char *name);

#endif /* ATM_SHRINK_CORE_H */
