/*
 * fx_encode.h - reusable offline encoder for the pinned compact directly
 * consumed FX music stream (finite v1, ATMlib2FX-hlh.7).
 *
 * The encoder takes a *modern-encoded* ATM_SCORE_FMT_FULL pattern model
 * (pattern bytes, absolute pattern offsets, four entry tracks) and emits the
 * pinned compact stream plus conversion metadata. It does not read files or
 * know anything about the on-disk score header; the host CLI
 * (tools/fx_pack/fx_pack.c) and the future JSON authoring adapter
 * (ATMlib2FX-3ii.3) share this layer.
 *
 * Pinned framing (research/fx/fx-architecture-decision.md, "hlh.6 review"):
 *   byte 0xC0
 *   then records until END:
 *     <len> <body>            len = record length in bytes (>= 5); 0x00 = END
 *     body := <gap> <bitmap> <groups>
 *       <gap>    effect-only ticks between this pass and the next
 *       <bitmap> bit0=ch0 .. bit3=ch3 (1..15)
 *       <groups> per set channel, in order: <glen> then <glen> command bytes
 *   gap varint: <=0x7F one byte; <=0x7EFF two bytes (0x80|hi7, lo8);
 *               otherwise three bytes (0xFF, hi8, lo8); maximum 65535.
 *
 * All integers little-endian, one byte each. Command bytes use the modern
 * ATMlib encoding (src/atm_cmd_constants.h). CALL/CALL_REPEAT/RETURN and
 * delays are resolved offline.
 *
 * Global-loop extension (ATMlib2FX-hlh.8, opt-in via
 * `fx_encode_options.allow_loops`): when a score issues SET_LOOP_PATTERN and
 * would restart the original engine's all-stopped loop, the encoder emits a
 * loop-capable stream instead. The framing is identical except for the header:
 *
 *   byte 0xC1
 *   u24 LE loop_start_rel   byte offset of the first loop-region record from
 *                           byte 0 (>= the 4-byte header); records follow
 *   then records until END (0x00); END is the loop boundary, not a stop.
 *
 * Record bitmap, loop mode only: bits 0..3 are the command channels; bits
 * 4..7 are the restart mask. A non-zero restart mask means the record is the
 * original engine's all-stopped pass: after applying it the decoder re-arms
 * those channels in the same tick (the immediate second pass). A bitmap of 0
 * is an effect-only pass (no commands, no restart).
 *
 * The loop region [loop_start_rel, stream_len-1) must fit the admission ring
 * so a device can pin it and replay it with no further fetch (no underrun at
 * the wrap). A region whose records all carry gap 0 would replay in a
 * same-tick chain that never yields a tick, so it is rejected. Finite streams
 * still start with 0xC0 and are byte-identical to the finite-v1 output.
 */
#ifndef FX_ENCODE_H
#define FX_ENCODE_H

#include <stddef.h>
#include <stdint.h>

#define FX_ENC_CHANNELS (4)
#define FX_ENC_DEFAULT_RING (32)
#define FX_ENC_DEFAULT_TICKS (8192)
#define FX_ENC_MAX_WINDOW (8)
#define FX_ENC_ERR_LEN (512)

/* Detection/validation hook used by the host decoders. */
#define FX_ENC_STREAM_MAGIC (0xC0u)
#define FX_ENC_STREAM_MAGIC_LOOP (0xC1u)
#define FX_ENC_LOOP_HEADER (4u) /* magic + u24 little-endian loop_start_rel */
#define FX_ENC_STREAM_END (0x00u)

struct fx_score_patterns {
	const uint8_t *bytes;      /* flat modern full-format score bytes      */
	size_t len;                /* length of `bytes`                         */
	uint8_t num_channels;      /* must be FX_ENC_CHANNELS                   */
	uint8_t num_patterns;      /* >= 1                                     */
	uint8_t entry[FX_ENC_CHANNELS];
	const uint32_t *pattern_offset; /* absolute offsets into `bytes`        */
	const char *format_name;   /* e.g. "ATM_SCORE_FMT_FULL" / "legacy-v1"   */
};

struct fx_encode_options {
	uint16_t ring;        /* admission ring size in bytes (default 32)   */
	uint32_t tick_cap;    /* conversion tick cap (default 8192)          */
	int tempo_override;   /* 0 = authored; else SET_TEMPO operand value  */
	int allow_loops;      /* 0 = finite v1 (reject SET_LOOP_PATTERN)     */
};

struct fx_encode_meta {
	uint32_t ticks_span;      /* conversion span (stopped tick or cap)    */
	int32_t stopped_at;       /* tick where all channels stopped, or -1   */
	uint32_t passes;          /* emitted due-pass records                  */
	uint32_t payload_bytes;   /* command bytes across all groups            */
	uint32_t max_group;       /* largest total command bytes in one pass   */
	uint32_t max_record;      /* largest complete record                    */
	uint32_t framing_bytes;   /* sum of record lengths (magic/END excluded)*/
	uint32_t max_window[FX_ENC_MAX_WINDOW + 1]; /* 1..8 tick byte windows */
	int64_t max_window_at[FX_ENC_MAX_WINDOW + 1]; /* first tick of window */
	/* Global-loop extension (ATMlib2FX-hlh.8). All zero/negative when the
	 * emitted stream is finite (magic 0xC0). */
	int has_loop;
	int32_t loop_start_offset; /* byte offset of the first loop record    */
	uint32_t intro_ticks;      /* ticks before the loop region            */
	uint32_t cycle_ticks;      /* loop period in ticks                    */
	uint32_t intro_passes;     /* records before loop_start_offset        */
	uint32_t loop_passes;      /* records in the loop region              */
};

struct fx_encode_result {
	uint8_t *stream;
	size_t stream_len;
	struct fx_encode_meta meta;
	char error[FX_ENC_ERR_LEN];
};

/* --- primitive helpers (also exercised by tests/fx_pack) ----------------- */

/* Byte length of a modern ATMlib command (matches src decoder). */
uint8_t fx_cmd_size(uint8_t id);

/* Gap codec. fx_gap_nbytes returns 0 for gaps > 65535 (admission failure). */
uint8_t fx_gap_nbytes(uint32_t gap);
uint8_t *fx_put_gap(uint8_t *dst, uint32_t gap);
int fx_decode_gap(const uint8_t *src, size_t avail, uint32_t *gap, uint32_t *used);

/* Structural validation identical to the device preflight. Returns 0 when the
 * stream is well formed, else non-zero with a diagnostic naming the stream
 * offset and field. */
int fx_stream_validate(const uint8_t *stream, size_t len, uint16_t ring,
		       char *err, size_t errlen);

/* --- encoder ------------------------------------------------------------- */

/* Encode `score` into `out`. Returns 0 on success. On admission or conversion
 * failure returns non-zero and fills out->error with a diagnostic that names
 * the channel, pattern index, score offset and command byte where relevant. */
int fx_encode(const struct fx_score_patterns *score,
	      const struct fx_encode_options *options,
	      struct fx_encode_result *out);

void fx_encode_result_free(struct fx_encode_result *out);

#endif /* FX_ENCODE_H */
