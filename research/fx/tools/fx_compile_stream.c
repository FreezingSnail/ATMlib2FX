/*
 * fx_compile_stream.c - offline pattern/call/repeat expansion for the
 * ATMlib2FX "compiled FX stream" prototype (ATMlib2FX-aoe).
 *
 * Input : one ATMlib score (examples/arduino/songs/song01_sfx/song.h), music only.
 * Output: a single sequential, channel-interleaved byte stream that the device
 *         replays with a small fixed refill buffer and no pattern stacks.
 *
 * The converter re-implements only the *traversal* semantics of the original
 * library (delays, calls, call-repeats, returns/pattern-end and the song-stop
 * rule) plus the command byte sizes. Effects are NOT interpreted here: every
 * effect/note/volume command is copied verbatim, so the device decoder reuses
 * the original effect implementation unchanged. CALL and PATTERN_END/RETURN are
 * consumed for traversal and never emitted.
 *
 * Stream framing (provisional, judged by the spike):
 *   byte 0xF5                 magic/version
 *   then records until END:
 *     0x00 <n>               SKIP: advance 1+n music ticks with no commands
 *     0x10                   END: song finished
 *     0x01..0x0F <groups>    APPLY one tick; low nibble = channel bitmap
 *                            (bit0=ch0..bit3=ch3); per present channel, in
 *                            order: <len> then <len> command bytes
 *
 * This is a build tool, not a test harness: it is compiled and run by
 * research/fx/tools/build-fx-stream.sh. Documented in research/fx/fx-footprint-results.md.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>

/* Host build: PROGMEM is a no-op and the score struct is an ordinary object.
 * ATM_SCORE_FMT_FULL is normally provided by src/atm_synth.h; define it here so
 * the converter can include the score without pulling in the engine. */
#define PROGMEM
#define ATM_SCORE_FMT_FULL (0x3)
#define ATM_SCORE_FMT_MINIMAL_MONO (0x0)

#include "atm_cmd_constants.h"
#include "song.h"

#define CHANNEL_COUNT (4)
#define PATTERN_STACK_DEPTH (3)

#define STREAM_MAGIC (0xF5u)
#define STREAM_END (0x10u)
#define STREAM_SKIP (0x00u)

#define GROUP_CAP (512)

/* --- growable output stream ------------------------------------------ */
static uint8_t *g_out;
static size_t g_len, g_cap;

static void put(uint8_t b)
{
	if (g_len == g_cap) {
		g_cap = g_cap ? g_cap * 2 : 4096;
		g_out = realloc(g_out, g_cap);
		if (!g_out) { perror("realloc"); exit(1); }
	}
	g_out[g_len++] = b;
}

/* --- original command sizes ------------------------------------------ */
static uint8_t cmd_size(uint8_t id)
{
	if (id < ATM_CMD_BLK_DELAY)        return 1; /* note on/off            */
	if (id < ATM_CMD_BLK_IMMEDIATE)    return 1; /* delay                  */
	if (id < ATM_CMD_BLK_1_PARAMETER)  return 1; /* immediate              */
	if (id < ATM_CMD_BLK_N_PARAMETER)  return 2; /* one parameter byte     */
	return (uint8_t)(1 + (((id >> 4) & 0x07) + 1)); /* n parameter bytes  */
}

/* --- traversal state -------------------------------------------------- */
struct pat_state {
	const uint8_t *cmd;
	uint8_t pattern;
	uint8_t rep;
};

struct chan {
	struct pat_state stack[PATTERN_STACK_DEPTH];
	uint8_t sp;
	uint16_t delay;
	uint8_t active;
};

static struct chan g_ch[CHANNEL_COUNT];

static const uint8_t *pattern_start(uint8_t pattern_index)
{
	const uint8_t *base = (const uint8_t *)&score;
	return base + ((const struct score_data *)&score)->patterns_offset[pattern_index];
}

static void chan_reset(struct chan *c, uint8_t entry)
{
	memset(c, 0, sizeof(*c));
	c->sp = 0;
	c->active = 1;
	c->stack[0].cmd = pattern_start(entry);
	c->stack[0].pattern = entry;
	c->stack[0].rep = 0;
}

/* Append the commands a channel runs this tick into out[]. Returns the byte
 * count (0 when the channel is delayed). Traversal commands are consumed. */
static uint16_t step_channel(struct chan *c, uint8_t *out, int tempo_override)
{
	uint16_t n = 0;

	while (c->delay == 0) {
		struct pat_state *ps = &c->stack[c->sp];
		const uint8_t *cmd_ptr = ps->cmd;
		uint8_t id = cmd_ptr[0];
		uint8_t sz = cmd_size(id);

		if (id < ATM_CMD_BLK_DELAY) {
			out[n++] = id;                    /* note on/off */
			ps->cmd += sz;
		} else if (id < ATM_CMD_BLK_IMMEDIATE) {
			c->delay = (uint16_t)(id - 63);   /* delay */
			out[n++] = id;
			ps->cmd += sz;
		} else if (id < ATM_CMD_BLK_1_PARAMETER) {
			if (id == ATM_CMD_I_PATTERN_END) {
				/* traversal only; the pointer advance is discarded */
				if (ps->rep > 0) {
					ps->rep--;
					ps->cmd = pattern_start(ps->pattern);
				} else if (c->sp == 0) {
					/* genuine channel stop: the device must see it */
					c->active = 0;
					c->delay = 0xFFFF;
					out[n++] = ATM_CMD_I_STOP;
				} else {
					c->sp--;
				}
			} else {
				out[n++] = id;                /* e.g. TRANSPOSITION_OFF */
				ps->cmd += sz;
			}
		} else if (id < ATM_CMD_BLK_N_PARAMETER) {
			out[n++] = id;                    /* one parameter byte */
			out[n++] = cmd_ptr[1];
			if (tempo_override != 0 && id == ATM_CMD_1P_SET_TEMPO)
				out[n - 1] = (uint8_t)tempo_override;
			ps->cmd += sz;
		} else {
			uint8_t cid = id & 0x0F;
			uint8_t csz = (uint8_t)(((id >> 4) & 0x07) + 1);
			const uint8_t *advanced = cmd_ptr + 1 + csz;

			if (cid == ATM_CMD_NP_CALL) {
				uint8_t new_track = cmd_ptr[1];
				if (c->sp < PATTERN_STACK_DEPTH - 1 &&
				    new_track != ps->pattern) {
					/* parent resumes after the call operands */
					ps->cmd = advanced;
					c->sp++;
					c->stack[c->sp].cmd = pattern_start(new_track);
					c->stack[c->sp].pattern = new_track;
					c->stack[c->sp].rep = csz > 1 ? cmd_ptr[2] : 0;
				} else {
					ps->cmd = advanced;       /* call skipped */
				}
			} else if (cid == ATM_CMD_NP_SET_LOOP_PATTERN) {
				fprintf(stderr,
					"fx_compile_stream: SET_LOOP_PATTERN unsupported "
					"(global-loop correctness is out of scope)\n");
				exit(2);
			} else {
				for (uint8_t i = 0; i < (uint8_t)(1 + csz); i++)
					out[n++] = cmd_ptr[i];    /* effect command */
				ps->cmd = advanced;
			}
		}
	}
	return n;
}

int main(int argc, char **argv)
{
	const char *out_path = "build/fx-port/fx-stream/spike_stream.bin";
	int tempo_override = 0;
	long tick_cap = 8192;

	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "--out") && i + 1 < argc) out_path = argv[++i];
		else if (!strcmp(argv[i], "--tempo") && i + 1 < argc) tempo_override = atoi(argv[++i]);
		else if (!strcmp(argv[i], "--ticks") && i + 1 < argc) tick_cap = atol(argv[++i]);
		else { fprintf(stderr, "fx_compile_stream: unknown arg %s\n", argv[i]); return 2; }
	}

	if (score.fmt != ATM_SCORE_FMT_FULL) {
		fprintf(stderr, "fx_compile_stream: expected ATM_SCORE_FMT_FULL, got 0x%02x\n", score.fmt);
		return 2;
	}
	if (score.num_channels != CHANNEL_COUNT) {
		fprintf(stderr, "fx_compile_stream: expected %d channels, got %u\n",
			CHANNEL_COUNT, score.num_channels);
		return 2;
	}

	for (int ch = 0; ch < CHANNEL_COUNT; ch++)
		chan_reset(&g_ch[ch], score.start_patterns[ch]);

	put(STREAM_MAGIC);

	uint8_t group[CHANNEL_COUNT][GROUP_CAP];
	uint16_t glen[CHANNEL_COUNT];
	uint8_t *tick_bytes = calloc((size_t)tick_cap + 1, 1); /* decoder-accurate bytes per tick */

	long ticks = 0;
	uint32_t max_group = 0;   /* max total command bytes across channels */
	uint32_t max_frame = 0;   /* control + length bytes + command bytes  */
	uint32_t payload_total = 0, frame_total = 0, skip_records = 0;
	uint32_t apply_records = 0;
	uint32_t skip_run = 0, skip_pos = 0;
	int stopped_at = -1;

	/* flush accumulated silent ticks as run-length SKIP records */
#define FLUSH_SKIPS()                                                    \
	do {                                                                 \
		while (skip_run > 0) {                                           \
			uint32_t n = skip_run > 256 ? 256 : skip_run;                \
			put(STREAM_SKIP);                                            \
			put((uint8_t)(n - 1));                                       \
			frame_total += 2;                                            \
			skip_records++;                                              \
			skip_run -= n;                                               \
		}                                                                \
	} while (0)

	while (ticks < tick_cap) {
		for (int ch = 0; ch < CHANNEL_COUNT; ch++)
			glen[ch] = step_channel(&g_ch[ch], group[ch], tempo_override);

		uint8_t ctl = 0;
		uint32_t group_bytes = 0;
		for (int ch = 0; ch < CHANNEL_COUNT; ch++) {
			if (glen[ch]) { ctl |= (uint8_t)(1u << ch); group_bytes += glen[ch]; }
		}

		if (ctl == 0) {
			skip_run++;
			tick_bytes[ticks] = (skip_pos % 256 == 0) ? 2 : 0;
			skip_pos++;
		} else {
			FLUSH_SKIPS();
			skip_pos = 0;
			put(ctl);
			uint32_t frame_bytes = 1;
			for (int ch = 0; ch < CHANNEL_COUNT; ch++) {
				if (!(ctl & (1u << ch))) continue;
				put((uint8_t)glen[ch]);
				for (uint16_t i = 0; i < glen[ch]; i++) put(group[ch][i]);
				frame_bytes += 1u + glen[ch];
			}
			frame_total += frame_bytes;
			if (frame_bytes > max_frame) max_frame = frame_bytes;
			if (group_bytes > max_group) max_group = group_bytes;
			payload_total += group_bytes;
			apply_records++;
			tick_bytes[ticks] = (uint8_t)frame_bytes;
		}

		ticks++;

		uint8_t any_active = 0;
		for (int ch = 0; ch < CHANNEL_COUNT; ch++)
			if (g_ch[ch].active) any_active = 1;
		if (!any_active) { stopped_at = (int)ticks; break; }

		for (int ch = 0; ch < CHANNEL_COUNT; ch++)
			if (g_ch[ch].delay != 0xFFFF) g_ch[ch].delay--;
	}
	FLUSH_SKIPS();
#undef FLUSH_SKIPS

	/* Window analysis: maximum decoder-consumed stream bytes over K
	 * consecutive ticks. Sizes the refill ring against the longest complete
	 * service interval (measured separately at 52 fps). */
	uint32_t max_window[17] = {0};
	long max_window_at[17] = {-1};
	for (int k = 1; k <= 16; k++) {
		uint64_t sum = 0;
		for (long i = 0; i < ticks; i++) {
			sum += tick_bytes[i];
			if (i >= k) sum -= tick_bytes[i - k];
			if (i >= k - 1 && sum > max_window[k]) {
				max_window[k] = (uint32_t)sum;
				max_window_at[k] = i - k + 1;
			}
		}
	}

	put(STREAM_END);

	FILE *f = fopen(out_path, "wb");
	if (!f) { perror(out_path); return 1; }
	if (fwrite(g_out, 1, g_len, f) != g_len) { perror("fwrite"); return 1; }
	fclose(f);

	fprintf(stderr,
		"fx_compile_stream: ticks=%ld stopped_at=%d stream_bytes=%zu "
		"payload_bytes=%u frame_bytes=%u max_group=%u max_frame=%u "
		"apply_records=%u skip_records=%u tempo=%s -> %s\n",
		ticks, stopped_at, g_len, payload_total, frame_total, max_group, max_frame,
		apply_records, skip_records, tempo_override ? "override" : "authored", out_path);

	printf("window_bytes");
	for (int k = 1; k <= 16; k++) printf(",%d:%u@%ld", k, max_window[k], max_window_at[k]);
	printf("\n");

	free(tick_bytes);
	free(g_out);
	return 0;
}
