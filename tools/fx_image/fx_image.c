/*
 * fx_image.c - maintainable FX data-image packer for the finite-v1 compact FX
 * music stream (ATMlib2FX-hlh.10, multi-stream mode ATMlib2FX-hlh.13).
 *
 * Single stream (unchanged, backwards compatible):
 *   fx_image --stream <bin> (--bitmap <img> | --fixture-bitmap)
 *            --out <fxdata.bin> [--meta <meta.json>] [--header <cfg.h>]
 *
 * Multi stream (one image, N named compact streams, optional bitmap):
 *   fx_image --stream <name>:<bin> [--stream <name>:<bin> ...]
 *            [--bitmap <img> | --fixture-bitmap]
 *            --out <fxdata.bin> [--meta <meta.json>] [--header <cfg.h>]
 *
 * Common options: [--bitmap-format auto|pbm|raw] [--width N --height N]
 *                 [--bitmap-header] [--chip-bytes N] [--page-bytes N]
 *
 * Replaces the fixed-fixture research/fx/tools/fx_make_fxdata.c (read-only
 * reference). See tools/fx_image/README.md and research/fx/fx-architecture-
 * decision.md ("hlh.6 review", item 4).
 *
 * No network, no installs, no git. Outputs are written under build/.
 */
#include "fx_image_core.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *kUsage =
	"usage: fx_image --stream <bin> (--bitmap <img> | --fixture-bitmap)\n"
	"                 --out <fxdata.bin> [--meta <meta.json>] [--header <cfg.h>]\n"
	"                 [--bitmap-format auto|pbm|raw] [--width N --height N]\n"
	"                 [--bitmap-header] [--chip-bytes N] [--page-bytes N]\n"
	"   or: fx_image --stream <name>:<bin> [--stream <name>:<bin> ...]\n"
	"                 [--bitmap <img> | --fixture-bitmap]\n"
	"                 --out <fxdata.bin> [--meta <meta.json>] [--header <cfg.h>]\n";

static int read_file(const char *path, uint8_t **out, size_t *out_len)
{
	FILE *f = fopen(path, "rb");
	if (!f) {
		return -1;
	}
	if (fseek(f, 0, SEEK_END) != 0) {
		fclose(f);
		return -1;
	}
	long sz = ftell(f);
	if (sz < 0) {
		fclose(f);
		return -1;
	}
	if (fseek(f, 0, SEEK_SET) != 0) {
		fclose(f);
		return -1;
	}
	uint8_t *buf = (uint8_t *)malloc((size_t)sz ? (size_t)sz : 1);
	if (!buf) {
		fclose(f);
		return -1;
	}
	if (sz > 0 && fread(buf, 1, (size_t)sz, f) != (size_t)sz) {
		free(buf);
		fclose(f);
		return -1;
	}
	fclose(f);
	*out = buf;
	*out_len = (size_t)sz;
	return 0;
}

static int write_file(const char *path, const uint8_t *data, size_t len)
{
	FILE *f = fopen(path, "wb");
	if (!f) {
		return -1;
	}
	int ok = (len == 0) || (fwrite(data, 1, len, f) == len);
	if (fclose(f) != 0) {
		ok = 0;
	}
	return ok ? 0 : -1;
}

static void json_escape(FILE *f, const char *s)
{
	for (; s && *s; s++) {
		if (*s == '"' || *s == '\\') {
			fputc('\\', f);
		}
		fputc(*s, f);
	}
}

static unsigned parse_u32(const char *s, int *ok)
{
	char *end = NULL;
	unsigned long v = strtoul(s, &end, 0);
	if (!s || *s == '\0' || (end && *end != '\0')) {
		*ok = 0;
		return 0;
	}
	*ok = 1;
	return (unsigned)v;
}

static const char *detect_format(const uint8_t *data, size_t len)
{
	if (len >= 2 && data[0] == 'P' && (data[1] == '1' || data[1] == '4')) {
		return "pbm";
	}
	return "raw";
}

/* Shared option set for both modes. */
struct fx_opts {
	const char *out_path;
	const char *meta_path;
	const char *header_path;
	const char *bitmap_path;
	const char *bitmap_format;
	int bitmap_set;
	int fixture;
	int bitmap_header;
	unsigned width, height;
	unsigned chip_bytes, page_bytes;
};

/* Non-zero if a stream of `len` bytes starts a global loop stream: the
 * finite-v1 loop extension uses version byte 0xC1, finite streams 0xC0
 * (research/fx/fx-architecture-decision.md, "hlh.8"). */
static int stream_is_loop(const uint8_t *data, size_t len)
{
	return len > 0 && data[0] == 0xC1;
}

/* Load and convert the bitmap input. `fixture` selects the built-in checker;
 * otherwise `path` must name a PBM or raw asset. On success fills `bm` and
 * *out_format. Returns 0, or -1 with a message in `err`. `bm` must be freed by
 * the caller with fx_bitmap_free() when this returns 0. */
static int load_bitmap(const struct fx_opts *o,
	struct fx_bitmap *bm, const char **out_format,
	char *err, size_t errlen)
{
	memset(bm, 0, sizeof(*bm));
	if (o->fixture) {
		*out_format = "fixture";
		if (fx_image_fixture_bitmap(32, 16, bm, err, errlen) != 0) {
			return -1;
		}
		return 0;
	}

	const char *path = o->bitmap_path;
	uint8_t *raw = NULL;
	size_t raw_len = 0;
	if (read_file(path, &raw, &raw_len) != 0) {
		snprintf(err, errlen, "cannot read bitmap %s", path);
		return -1;
	}

	const char *fmt = o->bitmap_format;
	if (!strcmp(fmt, "auto")) {
		fmt = detect_format(raw, raw_len);
	}
	*out_format = fmt;

	if (!strcmp(fmt, "pbm")) {
		int rc = fx_image_pbm_to_bitmap(raw, raw_len, bm, err, errlen);
		free(raw);
		return rc;
	}
	if (!strcmp(fmt, "raw")) {
		uint16_t w = (uint16_t)o->width, h = (uint16_t)o->height;
		if (o->bitmap_header) {
			if (raw_len < FX_IMAGE_BITMAP_HEADER_BYTES) {
				free(raw);
				snprintf(err, errlen, "raw bitmap header truncated");
				return -1;
			}
			w = (uint16_t)((raw[0] << 8) | raw[1]);
			h = (uint16_t)((raw[2] << 8) | raw[3]);
			raw += FX_IMAGE_BITMAP_HEADER_BYTES;
			raw_len -= FX_IMAGE_BITMAP_HEADER_BYTES;
		} else if (o->width == 0 || o->height == 0) {
			free(raw);
			snprintf(err, errlen,
				"raw bitmap needs --width and --height");
			return -1;
		}
		int rc = fx_image_raw_to_bitmap(raw, raw_len, w, h, bm, err, errlen);
		if (o->bitmap_header) {
			raw -= FX_IMAGE_BITMAP_HEADER_BYTES;
		}
		free(raw);
		return rc;
	}

	free(raw);
	snprintf(err, errlen, "unknown --bitmap-format %s", o->bitmap_format);
	return -1;
}

/* --- single-stream mode (legacy layout, unchanged) ------------------------ */

static int run_single(const char *stream_path, const struct fx_opts *o,
	int have_bitmap)
{
	char err[256];
	err[0] = '\0';

	if (!stream_path) {
		fputs(kUsage, stderr);
		return 2;
	}
	if (!have_bitmap) {
		fputs(kUsage, stderr);
		return 2;
	}

	uint8_t *stream = NULL;
	size_t stream_bytes = 0;
	if (read_file(stream_path, &stream, &stream_bytes) != 0) {
		fprintf(stderr, "fx_image: cannot read stream %s\n", stream_path);
		return 1;
	}
	if (stream_bytes == 0) {
		fprintf(stderr, "fx_image: stream %s is empty\n", stream_path);
		free(stream);
		return 1;
	}
	if (stream_bytes > 0xFFFFFFu) {
		fprintf(stderr, "fx_image: stream is larger than a 24-bit extent\n");
		free(stream);
		return 1;
	}

	struct fx_bitmap bm;
	const char *bm_format = "fixture";
	if (load_bitmap(o, &bm, &bm_format, err, sizeof(err)) != 0) {
		fprintf(stderr, "fx_image: %s\n", err);
		free(stream);
		return 1;
	}

	struct fx_layout L;
	if (fx_image_layout((uint32_t)stream_bytes, (uint32_t)bm.data_len,
		    o->chip_bytes, o->page_bytes, &L, err, sizeof(err)) != 0) {
		fprintf(stderr, "fx_image: %s\n", err);
		fx_bitmap_free(&bm);
		free(stream);
		return 1;
	}

	uint8_t *image = NULL;
	size_t image_len = 0;
	if (fx_image_compose(stream, (uint32_t)stream_bytes, &bm, &image, &image_len,
		    err, sizeof(err)) != 0) {
		fprintf(stderr, "fx_image: %s\n", err);
		fx_bitmap_free(&bm);
		free(stream);
		return 1;
	}

	if (write_file(o->out_path, image, image_len) != 0) {
		fprintf(stderr, "fx_image: cannot write %s\n", o->out_path);
		free(image);
		fx_bitmap_free(&bm);
		free(stream);
		return 1;
	}

	printf("tool=fx_image\n");
	printf("contract=finite-v1 compact directly-consumed stream\n");
	printf("stream_offset=0\n");
	printf("stream_len=%u\n", L.stream_len);
	printf("stream_end=%u\n", L.stream_len);
	printf("bitmap_offset=%u\n", L.bitmap_offset);
	printf("bitmap_width=%u\n", bm.width);
	printf("bitmap_height=%u\n", bm.height);
	printf("bitmap_data_len=%u\n", L.bitmap_data_len);
	printf("bitmap_len=%u\n", L.bitmap_len);
	printf("image_len=%u\n", L.image_len);
	printf("data_bytes=%u\n", L.data_bytes);
	printf("data_offset=%u\n", L.data_offset);
	printf("data_page=%u\n", L.data_page);
	printf("abs_stream_addr=%u\n", L.abs_stream_addr);
	printf("abs_stream_end=%u\n", L.abs_stream_end);
	printf("abs_bitmap_addr=%u\n", L.abs_bitmap_addr);
	printf("abs_bitmap_end=%u\n", L.abs_bitmap_end);
	printf("chip_bytes=%u\n", L.chip_bytes);
	printf("page_bytes=%u\n", L.page_bytes);
	printf("fits_24bit=%u\n", L.fits_24bit);

	if (o->meta_path) {
		FILE *f = fopen(o->meta_path, "wb");
		if (!f) {
			fprintf(stderr, "fx_image: cannot write %s\n", o->meta_path);
			free(image);
			fx_bitmap_free(&bm);
			free(stream);
			return 1;
		}
		fprintf(f, "{\n");
		fprintf(f, "  \"tool\": \"fx_image\",\n");
		fprintf(f, "  \"contract\": \"finite-v1 compact directly-consumed stream\",\n");
		fprintf(f, "  \"input\": {\n");
		fprintf(f, "    \"stream\": {\"path\": \"");
		json_escape(f, stream_path);
		fprintf(f, "\", \"bytes\": %u},\n", L.stream_len);
		fprintf(f, "    \"bitmap\": {\"path\": \"");
		json_escape(f, o->fixture ? "(fixture)" : o->bitmap_path);
		fprintf(f, "\", \"format\": \"%s\", \"width\": %u, \"height\": %u, "
			"\"data_bytes\": %u}\n",
			bm_format, bm.width, bm.height, L.bitmap_data_len);
		fprintf(f, "  },\n");
		fprintf(f, "  \"options\": {\"chip_bytes\": %u, \"page_bytes\": %u},\n",
			L.chip_bytes, L.page_bytes);
		fprintf(f, "  \"layout\": {\n");
		fprintf(f, "    \"image_bytes\": %u,\n", L.image_len);
		fprintf(f, "    \"data_bytes\": %u,\n", L.data_bytes);
		fprintf(f, "    \"data_offset\": %u,\n", L.data_offset);
		fprintf(f, "    \"data_page\": %u,\n", L.data_page);
		fprintf(f, "    \"stream\": {\"offset\": 0, \"length\": %u, \"end\": %u, "
			"\"abs_addr\": %u, \"abs_end\": %u},\n",
			L.stream_len, L.stream_len, L.abs_stream_addr, L.abs_stream_end);
		fprintf(f, "    \"bitmap\": {\"offset\": %u, \"header_bytes\": %u, "
			"\"data_bytes\": %u, \"length\": %u, \"end\": %u, "
			"\"abs_addr\": %u, \"abs_end\": %u}\n",
			L.bitmap_offset, FX_IMAGE_BITMAP_HEADER_BYTES,
			L.bitmap_data_len, L.bitmap_len, L.image_len,
			L.abs_bitmap_addr, L.abs_bitmap_end);
		fprintf(f, "  },\n");
		fprintf(f, "  \"bounds\": {\"chip_bytes\": %u, \"image_abs_end\": %u, "
			"\"fits_24bit\": %s}\n",
			L.chip_bytes, L.abs_bitmap_end, L.fits_24bit ? "true" : "false");
		fprintf(f, "}\n");
		if (fclose(f) != 0) {
			fprintf(stderr, "fx_image: error writing %s\n", o->meta_path);
			free(image);
			fx_bitmap_free(&bm);
			free(stream);
			return 1;
		}
	}

	if (o->header_path) {
		FILE *f = fopen(o->header_path, "wb");
		if (!f) {
			fprintf(stderr, "fx_image: cannot write %s\n", o->header_path);
			free(image);
			fx_bitmap_free(&bm);
			free(stream);
			return 1;
		}
		fprintf(f, "/* Generated by fx_image (ATMlib2FX-hlh.10). Do not edit. */\n");
		fprintf(f, "#ifndef FX_IMAGE_CONFIG_H\n#define FX_IMAGE_CONFIG_H\n\n");
		fprintf(f, "#define FX_DATA_PAGE %u\n", L.data_page);
		fprintf(f, "#define FX_BITMAP_OFFSET %u\n", L.bitmap_offset);
		fprintf(f, "#define FX_BITMAP_WIDTH %u\n", bm.width);
		fprintf(f, "#define FX_BITMAP_HEIGHT %u\n", bm.height);
		fprintf(f, "#define FX_STREAM_OFFSET 0\n");
		fprintf(f, "#define FX_STREAM_LEN %u\n", L.stream_len);
		fprintf(f, "#define FX_IMAGE_BYTES %u\n", L.image_len);
		fprintf(f, "\n#endif /* FX_IMAGE_CONFIG_H */\n");
		if (fclose(f) != 0) {
			fprintf(stderr, "fx_image: error writing %s\n", o->header_path);
			free(image);
			fx_bitmap_free(&bm);
			free(stream);
			return 1;
		}
	}

	free(image);
	fx_bitmap_free(&bm);
	free(stream);
	return 0;
}

/* --- multi-stream mode --------------------------------------------------- */

static int run_multi(char **names, const char **paths, uint32_t count,
	const struct fx_opts *o, int have_bitmap)
{
	char err[256];
	err[0] = '\0';
	int rc = 1;
	uint8_t *bufs[FX_IMAGE_MAX_STREAMS];
	const uint8_t *ptrs[FX_IMAGE_MAX_STREAMS];
	uint32_t lens[FX_IMAGE_MAX_STREAMS];
	memset(bufs, 0, sizeof(bufs));
	memset(ptrs, 0, sizeof(ptrs));
	memset(lens, 0, sizeof(lens));

	/* Duplicate names are rejected; names are the sketch-side identifiers. */
	for (uint32_t i = 0; i < count; i++) {
		for (uint32_t j = i + 1; j < count; j++) {
			if (!strcmp(names[i], names[j])) {
				fprintf(stderr,
					"fx_image: duplicate stream name '%s'\n",
					names[i]);
				goto done;
			}
		}
	}

	for (uint32_t i = 0; i < count; i++) {
		size_t n = 0;
		if (read_file(paths[i], &bufs[i], &n) != 0) {
			fprintf(stderr, "fx_image: cannot read stream %s\n", paths[i]);
			goto done;
		}
		if (n == 0) {
			fprintf(stderr, "fx_image: stream %s is empty\n", paths[i]);
			goto done;
		}
		if (n > 0xFFFFFFu) {
			fprintf(stderr,
				"fx_image: stream %s is larger than a 24-bit extent\n",
				paths[i]);
			goto done;
		}
		ptrs[i] = bufs[i];
		lens[i] = (uint32_t)n;
	}

	struct fx_bitmap bm;
	const char *bm_format = "fixture";
	int has_bitmap = 0;
	if (have_bitmap) {
		if (load_bitmap(o, &bm, &bm_format, err,
			    sizeof(err)) != 0) {
			fprintf(stderr, "fx_image: %s\n", err);
			goto done;
		}
		has_bitmap = 1;
	}

	struct fx_multi_layout M;
	if (fx_image_layout_multi(lens, count, has_bitmap,
		    has_bitmap ? (uint32_t)bm.data_len : 0,
		    o->chip_bytes, o->page_bytes, &M, err, sizeof(err)) != 0) {
		fprintf(stderr, "fx_image: %s\n", err);
		if (has_bitmap) {
			fx_bitmap_free(&bm);
		}
		goto done;
	}

	uint8_t *image = NULL;
	size_t image_len = 0;
	if (fx_image_compose_multi(ptrs, lens, count, has_bitmap ? &bm : NULL,
		    &image, &image_len, err, sizeof(err)) != 0) {
		fprintf(stderr, "fx_image: %s\n", err);
		if (has_bitmap) {
			fx_bitmap_free(&bm);
		}
		goto done;
	}

	if (write_file(o->out_path, image, image_len) != 0) {
		fprintf(stderr, "fx_image: cannot write %s\n", o->out_path);
		free(image);
		if (has_bitmap) {
			fx_bitmap_free(&bm);
		}
		goto done;
	}

	/* --- stdout metadata --- */
	printf("tool=fx_image\n");
	printf("contract=finite-v1 compact directly-consumed stream\n");
	printf("stream_count=%u\n", count);
	for (uint32_t i = 0; i < count; i++) {
		printf("stream%u_name=%s\n", i, names[i]);
		printf("stream%u_offset=%u\n", i, M.stream_offset[i]);
		printf("stream%u_len=%u\n", i, M.stream_len[i]);
		printf("stream%u_loop=%d\n", i, stream_is_loop(ptrs[i], lens[i]));
	}
	printf("bitmap=%d\n", has_bitmap);
	if (has_bitmap) {
		printf("bitmap_offset=%u\n", M.bitmap_offset);
		printf("bitmap_width=%u\n", bm.width);
		printf("bitmap_height=%u\n", bm.height);
		printf("bitmap_data_len=%u\n", M.bitmap_data_len);
		printf("bitmap_len=%u\n", M.bitmap_len);
	}
	printf("image_len=%u\n", M.image_len);
	printf("data_bytes=%u\n", M.data_bytes);
	printf("data_offset=%u\n", M.data_offset);
	printf("data_page=%u\n", M.data_page);
	for (uint32_t i = 0; i < count; i++) {
		printf("abs_stream%u_addr=%u\n", i,
			M.data_offset + M.stream_offset[i]);
		printf("abs_stream%u_end=%u\n", i,
			M.data_offset + M.stream_offset[i] + M.stream_len[i]);
	}
	if (has_bitmap) {
		printf("abs_bitmap_addr=%u\n", M.data_offset + M.bitmap_offset);
	}
	printf("abs_image_end=%u\n", M.abs_bitmap_end);
	printf("chip_bytes=%u\n", M.chip_bytes);
	printf("page_bytes=%u\n", M.page_bytes);
	printf("fits_24bit=%u\n", M.fits_24bit);

	/* --- optional JSON metadata --- */
	if (o->meta_path) {
		FILE *f = fopen(o->meta_path, "wb");
		if (!f) {
			fprintf(stderr, "fx_image: cannot write %s\n", o->meta_path);
			free(image);
			if (has_bitmap) {
				fx_bitmap_free(&bm);
			}
			goto done;
		}
		fprintf(f, "{\n");
		fprintf(f, "  \"tool\": \"fx_image\",\n");
		fprintf(f, "  \"contract\": \"finite-v1 compact directly-consumed stream\",\n");
		fprintf(f, "  \"input\": {\n");
		fprintf(f, "    \"streams\": [\n");
		for (uint32_t i = 0; i < count; i++) {
			fprintf(f, "      {\"name\": \"");
			json_escape(f, names[i]);
			fprintf(f, "\", \"path\": \"");
			json_escape(f, paths[i]);
			fprintf(f, "\", \"bytes\": %u, \"loop\": %d}%s\n",
				lens[i], stream_is_loop(ptrs[i], lens[i]),
				(i + 1 < count) ? "," : "");
		}
		fprintf(f, "    ],\n");
		if (has_bitmap) {
			fprintf(f, "    \"bitmap\": {\"path\": \"");
			json_escape(f, o->fixture ? "(fixture)" : "(input)");
			fprintf(f, "\", \"width\": %u, \"height\": %u, "
				"\"data_bytes\": %u}\n",
				bm.width, bm.height, M.bitmap_data_len);
		} else {
			fprintf(f, "    \"bitmap\": null\n");
		}
		fprintf(f, "  },\n");
		fprintf(f, "  \"options\": {\"chip_bytes\": %u, \"page_bytes\": %u},\n",
			M.chip_bytes, M.page_bytes);
		fprintf(f, "  \"layout\": {\n");
		fprintf(f, "    \"image_bytes\": %u,\n", M.image_len);
		fprintf(f, "    \"data_bytes\": %u,\n", M.data_bytes);
		fprintf(f, "    \"data_offset\": %u,\n", M.data_offset);
		fprintf(f, "    \"data_page\": %u,\n", M.data_page);
		fprintf(f, "    \"streams\": [\n");
		for (uint32_t i = 0; i < count; i++) {
			fprintf(f, "      {\"index\": %u, \"name\": \"", i);
			json_escape(f, names[i]);
			fprintf(f, "\", \"offset\": %u, \"length\": %u, "
				"\"end\": %u, \"abs_addr\": %u, \"abs_end\": %u, "
				"\"loop\": %d}%s\n",
				M.stream_offset[i], M.stream_len[i],
				M.stream_offset[i] + M.stream_len[i],
				M.data_offset + M.stream_offset[i],
				M.data_offset + M.stream_offset[i] + M.stream_len[i],
				stream_is_loop(ptrs[i], lens[i]),
				(i + 1 < count) ? "," : "");
		}
		fprintf(f, "    ],\n");
		if (has_bitmap) {
			fprintf(f, "    \"bitmap\": {\"offset\": %u, "
				"\"header_bytes\": %u, \"data_bytes\": %u, "
				"\"length\": %u, \"end\": %u, \"abs_addr\": %u, "
				"\"abs_end\": %u}\n",
				M.bitmap_offset, FX_IMAGE_BITMAP_HEADER_BYTES,
				M.bitmap_data_len, M.bitmap_len, M.image_len,
				M.data_offset + M.bitmap_offset,
				M.abs_bitmap_end);
		} else {
			fprintf(f, "    \"bitmap\": null\n");
		}
		fprintf(f, "  },\n");
		fprintf(f, "  \"bounds\": {\"chip_bytes\": %u, \"image_abs_end\": %u, "
			"\"fits_24bit\": %s}\n",
			M.chip_bytes, M.abs_bitmap_end, M.fits_24bit ? "true" : "false");
		fprintf(f, "}\n");
		if (fclose(f) != 0) {
			fprintf(stderr, "fx_image: error writing %s\n", o->meta_path);
			free(image);
			if (has_bitmap) {
				fx_bitmap_free(&bm);
			}
			goto done;
		}
	}

	/* --- optional C header (indexed per-stream symbols) --- */
	if (o->header_path) {
		FILE *f = fopen(o->header_path, "wb");
		if (!f) {
			fprintf(stderr, "fx_image: cannot write %s\n", o->header_path);
			free(image);
			if (has_bitmap) {
				fx_bitmap_free(&bm);
			}
			goto done;
		}
		fprintf(f, "/* Generated by fx_image (ATMlib2FX-hlh.13). Do not edit. */\n");
		fprintf(f, "#ifndef FX_IMAGE_CONFIG_H\n#define FX_IMAGE_CONFIG_H\n\n");
		fprintf(f, "#define FX_DATA_PAGE %u\n", M.data_page);
		fprintf(f, "#define FX_STREAM_COUNT %u\n", count);
		fprintf(f, "#define FX_IMAGE_HAS_BITMAP %d\n", has_bitmap);
		fprintf(f, "#define FX_IMAGE_BYTES %u\n\n", M.image_len);
		for (uint32_t i = 0; i < count; i++) {
			fprintf(f, "/* stream %u: \"%s\" (%s) */\n", i, names[i],
				stream_is_loop(ptrs[i], lens[i]) ? "loop" : "finite");
			fprintf(f, "#define FX_STREAM_%u_OFFSET %u\n", i,
				M.stream_offset[i]);
			fprintf(f, "#define FX_STREAM_%u_LEN %u\n", i,
				M.stream_len[i]);
			fprintf(f, "#define FX_STREAM_%u_LOOP %d\n", i,
				stream_is_loop(ptrs[i], lens[i]));
		}
		if (has_bitmap) {
			fprintf(f, "\n#define FX_BITMAP_OFFSET %u\n", M.bitmap_offset);
			fprintf(f, "#define FX_BITMAP_WIDTH %u\n", bm.width);
			fprintf(f, "#define FX_BITMAP_HEIGHT %u\n", bm.height);
		}
		fprintf(f, "\n#endif /* FX_IMAGE_CONFIG_H */\n");
		if (fclose(f) != 0) {
			fprintf(stderr, "fx_image: error writing %s\n", o->header_path);
			free(image);
			if (has_bitmap) {
				fx_bitmap_free(&bm);
			}
			goto done;
		}
	}

	free(image);
	if (has_bitmap) {
		fx_bitmap_free(&bm);
	}
	rc = 0;

done:
	for (uint32_t i = 0; i < count; i++) {
		free(bufs[i]);
	}
	return rc;
}

int main(int argc, char **argv)
{
	char *names[FX_IMAGE_MAX_STREAMS];
	const char *stream_paths[FX_IMAGE_MAX_STREAMS];
	uint32_t stream_count = 0;
	int stream_named = 0;
	int stream_unnamed = 0;

	struct fx_opts o;
	memset(&o, 0, sizeof(o));
	o.bitmap_format = "auto";
	o.chip_bytes = FX_IMAGE_CHIP_BYTES_DEFAULT;
	o.page_bytes = FX_IMAGE_PAGE_BYTES_DEFAULT;
	int have_bitmap = 0;

	for (int i = 1; i < argc; i++) {
		const char *a = argv[i];
		int ok = 1;
		if (!strcmp(a, "--help") || !strcmp(a, "-h")) {
			fputs(kUsage, stdout);
			return 0;
		} else if (!strcmp(a, "--stream") && i + 1 < argc) {
			char *val = argv[++i];
			char *colon = strchr(val, ':');
			if (stream_count >= FX_IMAGE_MAX_STREAMS) {
				fprintf(stderr, "fx_image: too many --stream\n");
				return 2;
			}
			if (colon) {
				*colon = '\0';
				names[stream_count] = val;
				stream_paths[stream_count] = colon + 1;
				stream_named = 1;
			} else {
				names[stream_count] = NULL;
				stream_paths[stream_count] = val;
				stream_unnamed = 1;
			}
			stream_count++;
		}
		else if (!strcmp(a, "--bitmap") && i + 1 < argc) {
			o.bitmap_path = argv[++i];
			o.bitmap_set = 1;
			have_bitmap = 1;
		}
		else if (!strcmp(a, "--out") && i + 1 < argc) o.out_path = argv[++i];
		else if (!strcmp(a, "--meta") && i + 1 < argc) o.meta_path = argv[++i];
		else if (!strcmp(a, "--header") && i + 1 < argc) o.header_path = argv[++i];
		else if (!strcmp(a, "--bitmap-format") && i + 1 < argc) o.bitmap_format = argv[++i];
		else if (!strcmp(a, "--fixture-bitmap")) { o.fixture = 1; have_bitmap = 1; }
		else if (!strcmp(a, "--bitmap-header")) o.bitmap_header = 1;
		else if (!strcmp(a, "--width") && i + 1 < argc) o.width = parse_u32(argv[++i], &ok);
		else if (!strcmp(a, "--height") && i + 1 < argc) o.height = parse_u32(argv[++i], &ok);
		else if (!strcmp(a, "--chip-bytes") && i + 1 < argc) o.chip_bytes = parse_u32(argv[++i], &ok);
		else if (!strcmp(a, "--page-bytes") && i + 1 < argc) o.page_bytes = parse_u32(argv[++i], &ok);
		else {
			fprintf(stderr, "fx_image: unknown argument %s\n", a);
			fputs(kUsage, stderr);
			return 2;
		}
		if (!ok) {
			fprintf(stderr, "fx_image: bad numeric value for %s\n", a);
			return 2;
		}
	}

	if (!o.out_path || stream_count == 0) {
		fputs(kUsage, stderr);
		return 2;
	}
	if (stream_named && stream_unnamed) {
		fprintf(stderr,
			"fx_image: cannot mix named (name:path) and plain --stream\n");
		fputs(kUsage, stderr);
		return 2;
	}
	if (o.fixture && o.bitmap_set) {
		fputs(kUsage, stderr);
		return 2;
	}

	if (!stream_named) {
		/* Single-stream mode: --stream PATH and a required bitmap. */
		if (stream_count != 1) {
			fputs(kUsage, stderr);
			return 2;
		}
		return run_single(stream_paths[0], &o, have_bitmap);
	}

	/* Multi-stream mode: validate names, then pack. */
	for (uint32_t i = 0; i < stream_count; i++) {
		const char *nm = names[i];
		size_t len = strlen(nm);
		if (len == 0 || len > 63) {
			fprintf(stderr, "fx_image: bad stream name '%s'\n", nm);
			return 2;
		}
		for (const char *p = nm; *p; p++) {
			int c = (unsigned char)*p;
			int okc = (c >= 'A' && c <= 'Z') ||
				(c >= 'a' && c <= 'z') ||
				(c >= '0' && c <= '9') || c == '_';
			if (!okc) {
				fprintf(stderr, "fx_image: bad stream name '%s'\n", nm);
				return 2;
			}
		}
	}
	return run_multi(names, stream_paths, stream_count, &o, have_bitmap);
}
