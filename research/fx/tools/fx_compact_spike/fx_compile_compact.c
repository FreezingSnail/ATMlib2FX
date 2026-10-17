/*
 * fx_compile_compact.c - offline converter for the compact directly-consumed
 * FX music spike (ATMlib2FX-hlh.5).
 *
 * Input : one ATMlib score (examples/arduino/songs/song01_sfx/song.h), music only.
 * Output: a single sequential, channel-interleaved byte stream with complete
 *         "due-pass" records and one shared tick gap per record.
 *
 * Relationship to the retained 64-byte-ring prototype (research/fx/tools/fx_compile_stream.c):
 *   - Both resolve pattern calls / call-repeats / returns / delays offline and
 *     copy every note/effect/volume command verbatim, so the device reuses the
 *     unchanged effect implementation.
 *   - The compact format additionally drops the per-channel *delay* bytecode
 *     (traversal only) and replaces the per-tick APPLY/SKIP split with one
 *     shared gap per record. A record's commands run at the current music tick;
 *     its gap says how many effect-only ticks elapse before the next record's
 *     commands. This merges what the old format spent on a SKIP record + a
 *     per-channel delay command into a single bounded gap field.
 *
 * Provisional compact framing (judged by the spike, not a frozen ABI):
 *   byte 0xC0                magic/version header (skipped by the decoder)
 *   then records until END:
 *     <len> <body>           len = total record length in bytes, len >= 5
 *                            0x00 means END (len byte only)
 *     body := <gap> <bitmap> <groups>
 *       <gap>    effect-only ticks between this pass and the next pass
 *                (next_tick - current_tick - 1; 0 = adjacent passes)
 *       <bitmap> bit0=ch0 .. bit3=ch3; exactly the channels with commands now
 *       <groups> for each set channel in order: <glen> then <glen> cmd bytes
 *
 * gap encoding (unsigned, 0..65535):
 *   g <= 0x7F         -> [g]                          1 byte
 *   g <= 0x7EFF       -> [0x80 | (g>>8)] [g & 0xFF]   2 bytes
 *   else              -> [0xFF] [g>>8] [g & 0xFF]     3 bytes
 * A pass record carries at least one channel (bitmap != 0); the device rejects
 * a zero-channel pass as nonprogressing.
 *
 * This is a build tool, not a test harness: it is compiled and run by
 * research/fx/tools/build-fx-compact.sh and research/fx/fx_compact_spike/trace/run-trace.sh.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>

/* Host build: PROGMEM is a no-op and the score struct is an ordinary object. */
#define PROGMEM
#define ATM_SCORE_FMT_FULL (0x3)
#define ATM_SCORE_FMT_MINIMAL_MONO (0x0)

#include "atm_cmd_constants.h"
#include "song.h"

#define CHANNEL_COUNT (4)
#define PATTERN_STACK_DEPTH (3)

#define COMPACT_MAGIC (0xC0u)
#define COMPACT_END (0x00u)

#define GROUP_CAP (512)
#define MAX_TICKS (8192)

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

/* Append the *musical* commands a channel runs this tick into out[]. Traversal
 * commands (delay long/short, PATTERN_END/RETURN, CALL) are consumed for
 * scheduling and not emitted; a genuine channel stop is emitted as the
 * original ATM_CMD_I_STOP. Returns the byte count (0 when the channel is
 * delayed or executed only a delay). */
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
			c->delay = (uint16_t)(id - 63);   /* short delay: traversal only */
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
					"fx_compile_compact: SET_LOOP_PATTERN unsupported "
					"(global-loop correctness is out of scope)\n");
				exit(2);
			} else if (cid == ATM_CMD_NP_LONG_DELAY) {
				/* traversal only: set the reschedule, do not emit */
				const uint32_t v = csz > 1
					? ((uint32_t)cmd_ptr[1] << 8) | cmd_ptr[2]
					: cmd_ptr[1];
				c->delay = (uint16_t)v;
				ps->cmd = advanced;
			} else {
				for (uint8_t i = 0; i < (uint8_t)(1 + csz); i++)
					out[n++] = cmd_ptr[i];    /* effect command */
				ps->cmd = advanced;
			}
		}
	}
	return n;
}

/* --- collected due passes -------------------------------------------- */
struct pass {
	uint32_t tick;
	uint8_t bitmap;
	uint8_t glen[CHANNEL_COUNT];
	uint8_t g[CHANNEL_COUNT][GROUP_CAP];
};

static struct pass *g_pass;
static size_t g_npass, g_cappass;

static struct pass *pass_add(void)
{
	if (g_npass == g_cappass) {
		g_cappass = g_cappass ? g_cappass * 2 : 512;
		g_pass = realloc(g_pass, g_cappass * sizeof(*g_pass));
		if (!g_pass) { perror("realloc"); exit(1); }
	}
	struct pass *p = &g_pass[g_npass++];
	memset(p, 0, sizeof(*p));
	return p;
}

static uint8_t gap_nbytes(uint32_t g)
{
	if (g <= 0x7F)   return 1;
	if (g <= 0x7EFF) return 2;
	return 3;
}

static void put_gap(uint32_t g)
{
	if (g <= 0x7F) {
		put((uint8_t)g);
	} else if (g <= 0x7EFF) {
		put((uint8_t)(0x80 | (g >> 8)));
		put((uint8_t)(g & 0xFF));
	} else {
		put(0xFF);
		put((uint8_t)((g >> 8) & 0xFF));
		put((uint8_t)(g & 0xFF));
	}
}

/* --- gap-codec boundary self-test ------------------------------------ */
static int decode_gap_mem(const uint8_t *b, uint32_t *g, uint32_t *used)
{
	uint8_t b0 = b[0];
	if (b0 < 0x80) { *g = b0; *used = 1; return 0; }
	if (b0 != 0xFF) { *g = ((uint32_t)(b0 & 0x7F) << 8) | b[1]; *used = 2; return 0; }
	*g = ((uint32_t)b[1] << 8) | b[2]; *used = 3; return 0;
}

static int selftest(void)
{
	static const uint32_t vals[] = { 0, 1, 32, 33, 127, 128, 255, 256, 257,
		0x7EFE, 0x7EFF, 0x7F00, 65534, 65535 };
	for (size_t i = 0; i < sizeof(vals) / sizeof(vals[0]); i++) {
		uint8_t buf[4];
		uint32_t g = 0, used = 0;
		size_t olen = g_len;
		put_gap(vals[i]);
		size_t n = g_len - olen;
		if (n != gap_nbytes(vals[i])) {
			fprintf(stderr, "selftest: gap %u size mismatch %zu != %u\n",
				(unsigned)vals[i], n, gap_nbytes(vals[i]));
			return 1;
		}
		memcpy(buf, g_out + olen, n);
		g_len = olen;
		if (decode_gap_mem(buf, &g, &used) || g != vals[i] || used != n) {
			fprintf(stderr, "selftest: gap %u round-trip failed\n",
				(unsigned)vals[i]);
			return 1;
		}
	}
	printf("selftest: gap codec OK (%zu values)\n",
		sizeof(vals) / sizeof(vals[0]));
	return 0;
}

int main(int argc, char **argv)
{
	const char *out_path = "build/fx-port/compact/compact_stream.bin";
	int tempo_override = 0;
	long tick_cap = MAX_TICKS;

	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "--out") && i + 1 < argc) out_path = argv[++i];
		else if (!strcmp(argv[i], "--tempo") && i + 1 < argc) tempo_override = atoi(argv[++i]);
		else if (!strcmp(argv[i], "--ticks") && i + 1 < argc) tick_cap = atol(argv[++i]);
		else if (!strcmp(argv[i], "--selftest")) return selftest();
		else { fprintf(stderr, "fx_compile_compact: unknown arg %s\n", argv[i]); return 2; }
	}

	if (score.fmt != ATM_SCORE_FMT_FULL) {
		fprintf(stderr, "fx_compile_compact: expected ATM_SCORE_FMT_FULL, got 0x%02x\n", score.fmt);
		return 2;
	}
	if (score.num_channels != CHANNEL_COUNT) {
		fprintf(stderr, "fx_compile_compact: expected %d channels, got %u\n",
			CHANNEL_COUNT, score.num_channels);
		return 2;
	}

	for (int ch = 0; ch < CHANNEL_COUNT; ch++)
		chan_reset(&g_ch[ch], score.start_patterns[ch]);

	uint8_t group[CHANNEL_COUNT][GROUP_CAP];
	uint16_t glen[CHANNEL_COUNT];
	static uint8_t tick_bytes[MAX_TICKS + 1];
	memset(tick_bytes, 0, sizeof(tick_bytes));

	long ticks = 0;
	uint32_t payload_total = 0;
	uint32_t max_group = 0;
	int stopped_at = -1;

	while (ticks < tick_cap) {
		for (int ch = 0; ch < CHANNEL_COUNT; ch++)
			glen[ch] = step_channel(&g_ch[ch], group[ch], tempo_override);

		uint8_t ctl = 0;
		uint32_t group_bytes = 0;
		for (int ch = 0; ch < CHANNEL_COUNT; ch++) {
			if (glen[ch]) { ctl |= (uint8_t)(1u << ch); group_bytes += glen[ch]; }
		}
		if (ctl != 0) {
			struct pass *p = pass_add();
			p->tick = (uint32_t)ticks;
			p->bitmap = ctl;
			for (int ch = 0; ch < CHANNEL_COUNT; ch++) {
				p->glen[ch] = (uint8_t)glen[ch];
				memcpy(p->g[ch], group[ch], glen[ch]);
			}
			payload_total += group_bytes;
			if (group_bytes > max_group) max_group = group_bytes;
		}

		ticks++;

		uint8_t any_active = 0;
		for (int ch = 0; ch < CHANNEL_COUNT; ch++)
			if (g_ch[ch].active) any_active = 1;
		if (!any_active) { stopped_at = (int)ticks; break; }

		for (int ch = 0; ch < CHANNEL_COUNT; ch++)
			if (g_ch[ch].delay != 0xFFFF) g_ch[ch].delay--;
	}

	/* --- serialize passes with shared gaps --------------------------- */
	put(COMPACT_MAGIC);
	uint32_t max_record = 0;
	uint32_t framing_total = 0;
	for (size_t i = 0; i < g_npass; i++) {
		struct pass *p = &g_pass[i];
		/* gap = number of effect-only ticks strictly between this pass and
		 * the next (next_tick - current_tick - 1). 0 means adjacent passes. */
		uint32_t gap = (i + 1 < g_npass)
			? (g_pass[i + 1].tick - p->tick - 1) : 0;
		uint32_t body = gap_nbytes(gap) + 1;
		for (int ch = 0; ch < CHANNEL_COUNT; ch++)
			if (p->bitmap & (1u << ch)) body += 1u + p->glen[ch];
		uint32_t reclen = 1 + body;
		if (reclen > 255) {
			fprintf(stderr,
				"fx_compile_compact: record at tick %u is %u bytes > 255\n",
				(unsigned)p->tick, (unsigned)reclen);
			return 2;
		}
		put((uint8_t)reclen);
		put_gap(gap);
		put(p->bitmap);
		for (int ch = 0; ch < CHANNEL_COUNT; ch++) {
			if (!(p->bitmap & (1u << ch))) continue;
			put(p->glen[ch]);
			for (uint16_t k = 0; k < p->glen[ch]; k++) put(p->g[ch][k]);
		}
		if (reclen > max_record) max_record = reclen;
		framing_total += reclen;
		if (p->tick <= (uint32_t)tick_cap) tick_bytes[p->tick] = (uint8_t)reclen;
	}
	put(COMPACT_END);
	/* END byte counts toward the decoder-consumed window at the tick it is read */
	if (stopped_at >= 0 && stopped_at <= (int)tick_cap)
		tick_bytes[stopped_at] = 1;

	FILE *f = fopen(out_path, "wb");
	if (!f) { perror(out_path); return 1; }
	if (fwrite(g_out, 1, g_len, f) != g_len) { perror("fwrite"); return 1; }
	fclose(f);

	long ticks_span = stopped_at >= 0 ? stopped_at : ticks;
	uint32_t max_window[9] = {0};
	long max_window_at[9] = {-1};
	for (int k = 1; k <= 8; k++) {
		uint64_t sum = 0;
		for (long i = 0; i < ticks_span; i++) {
			sum += tick_bytes[i];
			if (i >= k) sum -= tick_bytes[i - k];
			if (i >= k - 1 && sum > max_window[k]) {
				max_window[k] = (uint32_t)sum;
				max_window_at[k] = i - k + 1;
			}
		}
	}

	fprintf(stderr,
		"fx_compile_compact: ticks=%ld stopped_at=%d stream_bytes=%zu "
		"passes=%zu payload_bytes=%u max_group=%u max_record=%u "
		"framing_bytes=%u tempo=%s -> %s\n",
		ticks_span, stopped_at, g_len, g_npass, payload_total, max_group,
		max_record, framing_total, tempo_override ? "override" : "authored", out_path);

	printf("window_bytes");
	for (int k = 1; k <= 8; k++) printf(",%d:%u@%ld", k, max_window[k], max_window_at[k]);
	printf("\n");

	free(g_pass);
	free(g_out);
	return 0;
}
