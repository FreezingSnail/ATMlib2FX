/*
 * fx_image_core.c - layout/bitmap core for the FX data-image packer
 * (ATMlib2FX-hlh.10). See fx_image_core.h.
 */
#include "fx_image_core.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int fail(char *err, size_t errlen, const char *msg)
{
	if (err && errlen) {
		snprintf(err, errlen, "%s", msg);
	}
	return -1;
}

static int failf(char *err, size_t errlen, const char *fmt, unsigned a)
{
	if (err && errlen) {
		snprintf(err, errlen, fmt, a);
	}
	return -1;
}

void fx_bitmap_free(struct fx_bitmap *bm)
{
	if (bm) {
		free(bm->data);
		bm->data = NULL;
		bm->data_len = 0;
		bm->width = 0;
		bm->height = 0;
	}
}

static size_t bitmap_data_len_for(uint16_t width, uint16_t height)
{
	const size_t pages = (size_t)((height + 7u) / 8u);
	return pages * (size_t)width;
}

static int bitmap_alloc(struct fx_bitmap *out, uint16_t width, uint16_t height,
	char *err, size_t errlen)
{
	if (width == 0 || height == 0) {
		return fail(err, errlen, "bitmap dimensions must be non-zero");
	}
	const size_t dlen = bitmap_data_len_for(width, height);
	if (dlen == 0) {
		return fail(err, errlen, "bitmap data length overflow");
	}
	uint8_t *data = (uint8_t *)calloc(dlen, 1);
	if (!data) {
		return fail(err, errlen, "out of memory for bitmap");
	}
	out->width = width;
	out->height = height;
	out->data = data;
	out->data_len = dlen;
	return 0;
}

int fx_image_raw_to_bitmap(const uint8_t *raw, size_t raw_len,
	uint16_t width, uint16_t height,
	struct fx_bitmap *out, char *err, size_t errlen)
{
	if (bitmap_alloc(out, width, height, err, errlen) != 0) {
		return -1;
	}
	if (raw_len != out->data_len) {
		fx_bitmap_free(out);
		return failf(err, errlen,
			"raw bitmap length %u does not match width/height", (unsigned)raw_len);
	}
	memcpy(out->data, raw, raw_len);
	return 0;
}

int fx_image_fixture_bitmap(uint16_t width, uint16_t height,
	struct fx_bitmap *out, char *err, size_t errlen)
{
	if (bitmap_alloc(out, width, height, err, errlen) != 0) {
		return -1;
	}
	for (size_t i = 0; i < out->data_len; i++) {
		out->data[i] = (uint8_t)(((i * 7u + 3u) & 0xFFu) ^ (uint8_t)i);
	}
	return 0;
}

/* --- PBM (P1 ASCII / P4 binary) ----------------------------------------- */

struct token_reader {
	const uint8_t *p;
	const uint8_t *end;
};

static int pbm_skip(struct token_reader *r)
{
	for (;;) {
		while (r->p < r->end &&
		       (*r->p == ' ' || *r->p == '\t' || *r->p == '\n' ||
		        *r->p == '\r' || *r->p == '\f' || *r->p == '\v')) {
			r->p++;
		}
		if (r->p < r->end && *r->p == '#') {
			while (r->p < r->end && *r->p != '\n') {
				r->p++;
			}
			continue;
		}
		return 0;
	}
}

static int pbm_next_uint(struct token_reader *r, unsigned *out)
{
	pbm_skip(r);
	if (r->p >= r->end) {
		return -1;
	}
	unsigned v = 0;
	int any = 0;
	while (r->p < r->end && *r->p >= '0' && *r->p <= '9') {
		v = v * 10u + (unsigned)(*r->p - '0');
		if (v > 0xFFFFFFu) {
			return -1;
		}
		r->p++;
		any = 1;
	}
	if (!any) {
		return -1;
	}
	*out = v;
	return 0;
}

int fx_image_pbm_to_bitmap(const uint8_t *pbm, size_t len,
	struct fx_bitmap *out, char *err, size_t errlen)
{
	struct token_reader r = { pbm, pbm + len };
	unsigned magic_lo;

	pbm_skip(&r);
	if (r.end - r.p < 2 || r.p[0] != 'P' ||
	    (r.p[1] != '1' && r.p[1] != '4')) {
		return fail(err, errlen, "not a PBM image (expected P1 or P4 magic)");
	}
	magic_lo = (unsigned)(r.p[1] - '0');
	r.p += 2;

	unsigned w, h;
	if (pbm_next_uint(&r, &w) != 0 || pbm_next_uint(&r, &h) != 0) {
		return fail(err, errlen, "malformed PBM header (width/height)");
	}
	if (w == 0 || h == 0 || w > 0xFFFFu || h > 0xFFFFu) {
		return fail(err, errlen, "PBM dimensions out of range");
	}

	if (bitmap_alloc(out, (uint16_t)w, (uint16_t)h, err, errlen) != 0) {
		return -1;
	}

	if (magic_lo == 1u) {
		/* P1: ASCII 0/1 tokens, row-major, white(0)/black(1). */
		unsigned val = 0;
		for (unsigned y = 0; y < h; y++) {
			for (unsigned x = 0; x < w; x++) {
				if (pbm_next_uint(&r, &val) != 0) {
					fx_bitmap_free(out);
					return fail(err, errlen, "P1 image has too few pixels");
				}
				if (val) {
					out->data[(y >> 3) * w + x] |=
						(uint8_t)(1u << (y & 7u));
				}
			}
		}
	} else {
		/* P4: binary, rows padded to whole bytes, MSB is leftmost pixel. */
		pbm_skip(&r);
		const size_t row_bytes = (size_t)((w + 7u) / 8u);
		if ((size_t)(r.end - r.p) < row_bytes * h) {
			fx_bitmap_free(out);
			return fail(err, errlen, "P4 image has too few bytes");
		}
		for (unsigned y = 0; y < h; y++) {
			const uint8_t *row = r.p + (size_t)y * row_bytes;
			for (unsigned x = 0; x < w; x++) {
				const unsigned bit =
					(unsigned)((row[x >> 3] >> (7u - (x & 7u))) & 1u);
				if (bit) {
					out->data[(y >> 3) * w + x] |=
						(uint8_t)(1u << (y & 7u));
				}
			}
		}
	}
	return 0;
}

/* --- layout -------------------------------------------------------------- */

int fx_image_layout(uint32_t stream_len, uint32_t bitmap_data_len,
	uint32_t chip_bytes, uint32_t page_bytes,
	struct fx_layout *out, char *err, size_t errlen)
{
	if (page_bytes == 0 || (page_bytes & (page_bytes - 1u)) != 0) {
		return fail(err, errlen, "page size must be a non-zero power of two");
	}
	if (stream_len == 0) {
		return fail(err, errlen, "stream is empty");
	}
	if (bitmap_data_len == 0) {
		return fail(err, errlen, "bitmap data is empty");
	}

	uint64_t image_len = (uint64_t)stream_len + FX_IMAGE_BITMAP_HEADER_BYTES +
		(uint64_t)bitmap_data_len;
	uint64_t data_bytes = (image_len + page_bytes - 1u) /
		page_bytes * page_bytes;
	if (data_bytes > chip_bytes) {
		return fail(err, errlen, "image does not fit the FX chip");
	}

	uint32_t data_offset = (uint32_t)(chip_bytes - data_bytes);
	if (data_offset % page_bytes != 0) {
		return fail(err, errlen, "data base is not page aligned");
	}

	memset(out, 0, sizeof(*out));
	out->stream_len = stream_len;
	out->bitmap_offset = stream_len;              /* data-section relative */
	out->bitmap_data_len = bitmap_data_len;
	out->bitmap_len = FX_IMAGE_BITMAP_HEADER_BYTES + bitmap_data_len;
	out->image_len = (uint32_t)image_len;
	out->data_bytes = (uint32_t)data_bytes;
	out->data_offset = data_offset;
	out->data_page = data_offset / page_bytes;    /* single page add */
	out->abs_stream_addr = data_offset;           /* + relative offset 0 */
	out->abs_stream_end = data_offset + stream_len;
	out->abs_bitmap_addr = data_offset + out->bitmap_offset;
	out->abs_bitmap_end = data_offset + out->image_len;
	out->chip_bytes = chip_bytes;
	out->page_bytes = page_bytes;
	out->fits_24bit = (out->abs_bitmap_end <= 0x01000000u) &&
		(chip_bytes <= 0x01000000u) &&
		(out->data_offset <= 0xFFFFFFu) ? 1u : 0u;
	return 0;
}

int fx_image_compose(const uint8_t *stream, uint32_t stream_len,
	const struct fx_bitmap *bm,
	uint8_t **image_out, size_t *image_len_out,
	char *err, size_t errlen)
{
	if (!stream || stream_len == 0) {
		return fail(err, errlen, "stream is empty");
	}
	if (!bm || !bm->data || bm->data_len == 0) {
		return fail(err, errlen, "bitmap is empty");
	}

	const size_t image_len = (size_t)stream_len +
		FX_IMAGE_BITMAP_HEADER_BYTES + bm->data_len;
	uint8_t *image = (uint8_t *)malloc(image_len);
	if (!image) {
		return fail(err, errlen, "out of memory for image");
	}

	uint8_t *p = image;
	memcpy(p, stream, stream_len);
	p += stream_len;
	p[0] = (uint8_t)(bm->width >> 8);
	p[1] = (uint8_t)(bm->width & 0xFF);
	p[2] = (uint8_t)(bm->height >> 8);
	p[3] = (uint8_t)(bm->height & 0xFF);
	p += FX_IMAGE_BITMAP_HEADER_BYTES;
	memcpy(p, bm->data, bm->data_len);

	*image_out = image;
	*image_len_out = image_len;
	return 0;
}

/* --- multi-stream layout and composition --------------------------------- */

int fx_image_layout_multi(const uint32_t *stream_lens, uint32_t stream_count,
	int has_bitmap, uint32_t bitmap_data_len,
	uint32_t chip_bytes, uint32_t page_bytes,
	struct fx_multi_layout *out, char *err, size_t errlen)
{
	if (page_bytes == 0 || (page_bytes & (page_bytes - 1u)) != 0) {
		return fail(err, errlen, "page size must be a non-zero power of two");
	}
	if (!stream_lens || stream_count == 0) {
		return fail(err, errlen, "no streams");
	}
	if (stream_count > FX_IMAGE_MAX_STREAMS) {
		return fail(err, errlen, "too many streams");
	}

	uint64_t rel = 0;
	for (uint32_t i = 0; i < stream_count; i++) {
		if (stream_lens[i] == 0) {
			return failf(err, errlen, "stream %u is empty", i);
		}
		if (stream_lens[i] > 0xFFFFFFu) {
			return failf(err, errlen,
				"stream %u is larger than a 24-bit extent", i);
		}
		rel += stream_lens[i];
	}

	uint64_t image_len = rel;
	uint32_t bitmap_offset = 0;
	uint32_t bitmap_len = 0;
	if (has_bitmap) {
		if (bitmap_data_len == 0) {
			return fail(err, errlen, "bitmap data is empty");
		}
		bitmap_offset = (uint32_t)rel;
		bitmap_len = FX_IMAGE_BITMAP_HEADER_BYTES + bitmap_data_len;
		image_len += bitmap_len;
	}

	uint64_t data_bytes = (image_len + page_bytes - 1u) /
		page_bytes * page_bytes;
	if (data_bytes > chip_bytes) {
		return fail(err, errlen, "image does not fit the FX chip");
	}

	uint32_t data_offset = (uint32_t)(chip_bytes - data_bytes);
	if (data_offset % page_bytes != 0) {
		return fail(err, errlen, "data base is not page aligned");
	}

	memset(out, 0, sizeof(*out));
	out->stream_count = stream_count;
	uint64_t off = 0;
	for (uint32_t i = 0; i < stream_count; i++) {
		out->stream_offset[i] = (uint32_t)off;
		out->stream_len[i] = stream_lens[i];
		off += stream_lens[i];
	}
	out->has_bitmap = has_bitmap ? 1u : 0u;
	out->bitmap_offset = bitmap_offset;
	out->bitmap_data_len = has_bitmap ? bitmap_data_len : 0;
	out->bitmap_len = bitmap_len;
	out->image_len = (uint32_t)image_len;
	out->data_bytes = (uint32_t)data_bytes;
	out->data_offset = data_offset;
	out->data_page = data_offset / page_bytes;
	out->abs_bitmap_end = data_offset + (uint32_t)image_len;
	out->chip_bytes = chip_bytes;
	out->page_bytes = page_bytes;
	out->fits_24bit = (out->abs_bitmap_end <= 0x01000000u) &&
		(chip_bytes <= 0x01000000u) &&
		(data_offset <= 0xFFFFFFu) ? 1u : 0u;
	return 0;
}

int fx_image_compose_multi(const uint8_t *const *streams,
	const uint32_t *stream_lens, uint32_t stream_count,
	const struct fx_bitmap *bm,
	uint8_t **image_out, size_t *image_len_out,
	char *err, size_t errlen)
{
	if (!streams || !stream_lens || stream_count == 0) {
		return fail(err, errlen, "no streams");
	}
	if (stream_count > FX_IMAGE_MAX_STREAMS) {
		return fail(err, errlen, "too many streams");
	}

	uint64_t total = 0;
	for (uint32_t i = 0; i < stream_count; i++) {
		if (!streams[i] || stream_lens[i] == 0) {
			return failf(err, errlen, "stream %u is empty", i);
		}
		total += stream_lens[i];
	}

	size_t bitmap_len = 0;
	if (bm) {
		if (!bm->data || bm->data_len == 0) {
			return fail(err, errlen, "bitmap is empty");
		}
		bitmap_len = FX_IMAGE_BITMAP_HEADER_BYTES + bm->data_len;
	}

	const size_t image_len = (size_t)total + bitmap_len;
	uint8_t *image = (uint8_t *)malloc(image_len);
	if (!image) {
		return fail(err, errlen, "out of memory for image");
	}

	uint8_t *p = image;
	for (uint32_t i = 0; i < stream_count; i++) {
		memcpy(p, streams[i], stream_lens[i]);
		p += stream_lens[i];
	}
	if (bm) {
		p[0] = (uint8_t)(bm->width >> 8);
		p[1] = (uint8_t)(bm->width & 0xFF);
		p[2] = (uint8_t)(bm->height >> 8);
		p[3] = (uint8_t)(bm->height & 0xFF);
		p += FX_IMAGE_BITMAP_HEADER_BYTES;
		memcpy(p, bm->data, bm->data_len);
	}

	*image_out = image;
	*image_len_out = image_len;
	return 0;
}
