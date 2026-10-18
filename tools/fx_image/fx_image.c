/*
 * fx_image.c - maintainable FX data-image packer for the finite-v1 compact FX
 * music stream (ATMlib2FX-hlh.10).
 *
 * Usage: fx_image --stream <bin> (--bitmap <img> | --fixture-bitmap)
 *                 --out <fxdata.bin> [--meta <meta.json>] [--header <cfg.h>]
 *                 [--bitmap-format auto|pbm|raw] [--width N --height N]
 *                 [--bitmap-header] [--chip-bytes N] [--page-bytes N]
 *
 * Replaces the fixed-fixture research/fx/tools/fx_make_fxdata.c (read-only
 * reference): the bitmap is a real image input (netpbm P1/P4, or a raw
 * page-major 1bpp asset), and layout/metadata are owned here. See
 * tools/fx_image/README.md and research/fx/fx-architecture-decision.md.
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
	"                 [--bitmap-header] [--chip-bytes N] [--page-bytes N]\n";

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

int main(int argc, char **argv)
{
	const char *stream_path = NULL;
	const char *bitmap_path = NULL;
	const char *out_path = NULL;
	const char *meta_path = NULL;
	const char *header_path = NULL;
	const char *bitmap_format = "auto";
	int fixture = 0;
	int bitmap_header = 0;
	unsigned width = 0, height = 0;
	unsigned chip_bytes = FX_IMAGE_CHIP_BYTES_DEFAULT;
	unsigned page_bytes = FX_IMAGE_PAGE_BYTES_DEFAULT;

	for (int i = 1; i < argc; i++) {
		const char *a = argv[i];
		int ok = 1;
		if (!strcmp(a, "--help") || !strcmp(a, "-h")) {
			fputs(kUsage, stdout);
			return 0;
		} else if (!strcmp(a, "--stream") && i + 1 < argc) stream_path = argv[++i];
		else if (!strcmp(a, "--bitmap") && i + 1 < argc) bitmap_path = argv[++i];
		else if (!strcmp(a, "--out") && i + 1 < argc) out_path = argv[++i];
		else if (!strcmp(a, "--meta") && i + 1 < argc) meta_path = argv[++i];
		else if (!strcmp(a, "--header") && i + 1 < argc) header_path = argv[++i];
		else if (!strcmp(a, "--bitmap-format") && i + 1 < argc) bitmap_format = argv[++i];
		else if (!strcmp(a, "--fixture-bitmap")) fixture = 1;
		else if (!strcmp(a, "--bitmap-header")) bitmap_header = 1;
		else if (!strcmp(a, "--width") && i + 1 < argc) width = parse_u32(argv[++i], &ok);
		else if (!strcmp(a, "--height") && i + 1 < argc) height = parse_u32(argv[++i], &ok);
		else if (!strcmp(a, "--chip-bytes") && i + 1 < argc) chip_bytes = parse_u32(argv[++i], &ok);
		else if (!strcmp(a, "--page-bytes") && i + 1 < argc) page_bytes = parse_u32(argv[++i], &ok);
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

	if (!stream_path || !out_path || (!fixture && !bitmap_path) ||
	    (fixture && bitmap_path)) {
		fputs(kUsage, stderr);
		return 2;
	}

	char err[256];
	err[0] = '\0';

	/* --- stream ---------------------------------------------------------- */
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

	/* --- bitmap ---------------------------------------------------------- */
	struct fx_bitmap bm;
	memset(&bm, 0, sizeof(bm));
	const char *bm_format = "fixture";
	if (fixture) {
		if (fx_image_fixture_bitmap(32, 16, &bm, err, sizeof(err)) != 0) {
			fprintf(stderr, "fx_image: %s\n", err);
			free(stream);
			return 1;
		}
	} else {
		uint8_t *raw = NULL;
		size_t raw_len = 0;
		if (read_file(bitmap_path, &raw, &raw_len) != 0) {
			fprintf(stderr, "fx_image: cannot read bitmap %s\n", bitmap_path);
			free(stream);
			return 1;
		}
		bm_format = bitmap_format;
		if (!strcmp(bitmap_format, "auto")) {
			bm_format = detect_format(raw, raw_len);
		}
		if (!strcmp(bm_format, "pbm")) {
			if (fx_image_pbm_to_bitmap(raw, raw_len, &bm, err, sizeof(err)) != 0) {
				fprintf(stderr, "fx_image: %s\n", err);
				free(raw);
				free(stream);
				return 1;
			}
		} else if (!strcmp(bm_format, "raw")) {
			uint16_t w = (uint16_t)width, h = (uint16_t)height;
			if (bitmap_header) {
				if (raw_len < FX_IMAGE_BITMAP_HEADER_BYTES) {
					fprintf(stderr, "fx_image: raw bitmap header truncated\n");
					free(raw);
					free(stream);
					return 1;
				}
				w = (uint16_t)((raw[0] << 8) | raw[1]);
				h = (uint16_t)((raw[2] << 8) | raw[3]);
				raw += FX_IMAGE_BITMAP_HEADER_BYTES;
				raw_len -= FX_IMAGE_BITMAP_HEADER_BYTES;
			} else if (width == 0 || height == 0) {
				fprintf(stderr, "fx_image: raw bitmap needs --width and --height\n");
				free(raw);
				free(stream);
				return 1;
			}
			int rc = fx_image_raw_to_bitmap(raw, raw_len, w, h, &bm, err, sizeof(err));
			if (bitmap_header) {
				raw -= FX_IMAGE_BITMAP_HEADER_BYTES;
			}
			if (rc != 0) {
				fprintf(stderr, "fx_image: %s\n", err);
				free(raw);
				free(stream);
				return 1;
			}
		} else {
			fprintf(stderr, "fx_image: unknown --bitmap-format %s\n", bitmap_format);
			free(raw);
			free(stream);
			return 1;
		}
		free(raw);
	}

	/* --- compose and place ---------------------------------------------- */
	struct fx_layout L;
	if (fx_image_layout((uint32_t)stream_bytes, (uint32_t)bm.data_len,
		    chip_bytes, page_bytes, &L, err, sizeof(err)) != 0) {
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

	if (write_file(out_path, image, image_len) != 0) {
		fprintf(stderr, "fx_image: cannot write %s\n", out_path);
		free(image);
		fx_bitmap_free(&bm);
		free(stream);
		return 1;
	}

	/* --- stdout metadata (key=value, reference-compatible names) --------- */
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

	/* --- optional JSON metadata ----------------------------------------- */
	if (meta_path) {
		FILE *f = fopen(meta_path, "wb");
		if (!f) {
			fprintf(stderr, "fx_image: cannot write %s\n", meta_path);
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
		json_escape(f, bitmap_path ? bitmap_path : "(fixture)");
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
			fprintf(stderr, "fx_image: error writing %s\n", meta_path);
			free(image);
			fx_bitmap_free(&bm);
			free(stream);
			return 1;
		}
	}

	/* --- optional C header ---------------------------------------------- */
	if (header_path) {
		FILE *f = fopen(header_path, "wb");
		if (!f) {
			fprintf(stderr, "fx_image: cannot write %s\n", header_path);
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
			fprintf(stderr, "fx_image: error writing %s\n", header_path);
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
