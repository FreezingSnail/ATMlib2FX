/*
 * fx_compile_sfx.c - offline encoder for the compact SFX overlay stream
 * (ATMlib2FX-hlh.9).
 *
 * Input : the single-channel MINIMAL_MONO SFX fixture
 *         (examples/arduino/songs/song01_sfx/song.h -> sfx1).
 * Output: a compact record stream in the exact format consumed by
 *         atm_fx_compact_play_sfx() (src/atm_fx_compact.c), plus a C header
 *         with the bytes in PROGMEM for the device sketch.
 *
 * Framing is the pinned compact format (see src/atm_fx_compact.h): 0xC0 magic,
 * then <len> <gap> <bitmap> <glen> <cmds...> per pass, then 0x00 END. The SFX
 * is mono, so every record names exactly the borrowed channel (bitmap = 1<<ch).
 * The original command bytes are copied verbatim; delay bytecode is resolved
 * offline into the shared gap field, identical to the music converter.
 *
 * Usage:
 *   fx_compile_sfx <channel_index> <out.bin> [out.h] [name]
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>

#define PROGMEM
#define ATM_SCORE_FMT_FULL (0x3)
#define ATM_SCORE_FMT_MINIMAL_MONO (0x0)

#include "atm_cmd_constants.h"
#include "song.h"

#define COMPACT_MAGIC (0xC0u)
#define COMPACT_END (0x00u)
#define MAX_PASSES (64)
#define GROUP_CAP (64)

static uint8_t cmd_size(uint8_t id)
{
	if (id < ATM_CMD_BLK_DELAY)        return 1;
	if (id < ATM_CMD_BLK_IMMEDIATE)    return 1;
	if (id < ATM_CMD_BLK_1_PARAMETER)  return 1;
	if (id < ATM_CMD_BLK_N_PARAMETER)  return 2;
	return (uint8_t)(1 + (((id >> 4) & 0x07) + 1));
}

struct pass {
	uint32_t tick;
	uint8_t glen;
	uint8_t g[GROUP_CAP];
};

static struct pass g_pass[MAX_PASSES];
static int g_npass;

int main(int argc, char **argv)
{
	if (argc < 3) {
		fprintf(stderr, "usage: %s <channel_index> <out.bin> [out.h] [name]\n",
			argv[0]);
		return 2;
	}
	const uint8_t channel_index = (uint8_t)atoi(argv[1]);
	const char *out_bin = argv[2];
	const char *out_hdr = argc > 3 ? argv[3] : NULL;
	const char *name = argc > 4 ? argv[4] : "sfx_compact_stream";

	if (channel_index >= 4) {
		fprintf(stderr, "fx_compile_sfx: channel %u out of range\n", channel_index);
		return 2;
	}

	const uint8_t *p = sfx1.pattern0;
	const uint8_t plen = (uint8_t)sizeof(sfx1.pattern0);
	uint8_t pos = 0;
	uint16_t delay = 0;
	uint32_t tick = 0;
	int stopped = 0;

	while (!stopped && pos < plen) {
		uint8_t group[GROUP_CAP];
		uint8_t glen = 0;

		while (delay == 0 && pos < plen) {
			const uint8_t id = p[pos];
			const uint8_t sz = cmd_size(id);

			if (id == ATM_CMD_I_PATTERN_END) {
				group[glen++] = id;
				pos = (uint8_t)(pos + sz);
				stopped = 1;
				break;
			} else if (id < ATM_CMD_BLK_DELAY) {
				group[glen++] = id;
				pos = (uint8_t)(pos + sz);
			} else if (id < ATM_CMD_BLK_IMMEDIATE) {
				delay = (uint16_t)(id - 63);
				pos = (uint8_t)(pos + sz);
			} else if (id < ATM_CMD_BLK_1_PARAMETER) {
				group[glen++] = id;
				pos = (uint8_t)(pos + sz);
			} else if (id < ATM_CMD_BLK_N_PARAMETER) {
				group[glen++] = id;
				group[glen++] = p[pos + 1];
				pos = (uint8_t)(pos + sz);
			} else {
				const uint8_t cid = (uint8_t)(id & 0x0F);
				const uint8_t csz = (uint8_t)(((id >> 4) & 0x07) + 1);
				if (cid == ATM_CMD_NP_LONG_DELAY) {
					delay = csz > 1
						? (uint16_t)(((uint16_t)p[pos + 1] << 8) | p[pos + 2])
						: p[pos + 1];
				} else {
					for (uint8_t k = 0; k < (uint8_t)(1 + csz); k++)
						group[glen++] = p[pos + k];
				}
				pos = (uint8_t)(pos + 1 + csz);
			}
			if (glen >= GROUP_CAP) {
				fprintf(stderr, "fx_compile_sfx: group overflow\n");
				return 2;
			}
		}

		if (glen) {
			if (g_npass >= MAX_PASSES) {
				fprintf(stderr, "fx_compile_sfx: too many passes\n");
				return 2;
			}
			struct pass *pp = &g_pass[g_npass++];
			pp->tick = tick;
			pp->glen = glen;
			memcpy(pp->g, group, glen);
		}

		tick++;
		if (delay != 0xFFFF) {
			delay--;
		}
	}

	/* Serialize. */
	uint8_t out[512];
	size_t n = 0;
	uint32_t max_record = 0;
	out[n++] = COMPACT_MAGIC;
	for (int i = 0; i < g_npass; i++) {
		const struct pass *pp = &g_pass[i];
		const uint32_t gap = (i + 1 < g_npass)
			? (g_pass[i + 1].tick - pp->tick - 1) : 0;
		uint8_t gapb[3];
		size_t gn;
		if (gap <= 0x7F) {
			gapb[0] = (uint8_t)gap; gn = 1;
		} else if (gap <= 0x7EFF) {
			gapb[0] = (uint8_t)(0x80 | (gap >> 8));
			gapb[1] = (uint8_t)(gap & 0xFF); gn = 2;
		} else {
			gapb[0] = 0xFF; gapb[1] = (uint8_t)((gap >> 8) & 0xFF);
			gapb[2] = (uint8_t)(gap & 0xFF); gn = 3;
		}
		const uint8_t bitmap = (uint8_t)(1u << channel_index);
		const uint32_t body = (uint32_t)gn + 1u + 1u + pp->glen;
		const uint32_t reclen = 1u + body;
		if (reclen > 255) {
			fprintf(stderr, "fx_compile_sfx: record > 255 bytes\n");
			return 2;
		}
		if (reclen > max_record) max_record = reclen;
		out[n++] = (uint8_t)reclen;
		for (size_t k = 0; k < gn; k++) out[n++] = gapb[k];
		out[n++] = bitmap;
		out[n++] = pp->glen;
		for (uint8_t k = 0; k < pp->glen; k++) out[n++] = pp->g[k];
	}
	out[n++] = COMPACT_END;

	FILE *f = fopen(out_bin, "wb");
	if (!f) { perror(out_bin); return 1; }
	if (fwrite(out, 1, n, f) != n) { perror("fwrite"); return 1; }
	fclose(f);

	if (out_hdr) {
		FILE *h = fopen(out_hdr, "w");
		if (!h) { perror(out_hdr); return 1; }
		fprintf(h, "/* generated by fx_compile_sfx.c "
			"(ATMlib2FX-hlh.9) - do not edit */\n");
		fprintf(h, "#ifndef SFX_COMPACT_STREAM_H\n#define SFX_COMPACT_STREAM_H\n");
		fprintf(h, "#include <stdint.h>\n");
		fprintf(h, "#ifndef PROGMEM\n#define PROGMEM\n#endif\n");
		fprintf(h, "#define SFX_COMPACT_CH %u\n", (unsigned)channel_index);
		fprintf(h, "#define SFX_COMPACT_STREAM_LEN %zu\n", n);
		fprintf(h, "static const uint8_t %s[SFX_COMPACT_STREAM_LEN] PROGMEM = {",
			name);
		for (size_t k = 0; k < n; k++) {
			if ((k % 12) == 0) fprintf(h, "\n\t");
			fprintf(h, "0x%02x,", out[k]);
		}
		fprintf(h, "\n};\n#endif\n");
		fclose(h);
	}

	fprintf(stderr, "fx_compile_sfx: channel=%u passes=%d bytes=%zu "
		"max_record=%u -> %s\n",
		(unsigned)channel_index, g_npass, n, (unsigned)max_record, out_bin);
	return 0;
}
