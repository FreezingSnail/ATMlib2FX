/*
 * fx_image_core.h - maintainable FX data-image packing for the finite-v1
 * compact FX music stream (ATMlib2FX-hlh.10).
 *
 * Productionizes the retired fixed-fixture packer; the retained reference
 * implementation for parity tests is tests/fx_image/reference/fx_make_fxdata.c.
 * Instead of a hard-coded test bitmap, the caller supplies a stream binary plus
 * a real bitmap/image input, and the tool owns the layout, data-page placement,
 * 24-bit extent arithmetic and metadata.
 *
 * Ownership and layout follow the pinned contract in
 * research/fx/fx-architecture-decision.md ("hlh.6 review", item 4):
 *   - offset/length the caller passes to the decoder are data-section-relative
 *     24-bit values; the fetch callback receives relative offsets;
 *   - the data page is added exactly once (as the data-section base);
 *   - all device reads are bounds-checked against stream_end.
 *
 * Image layout (what absim / the W25Q128 holds), identical in shape to the
 * reference packer:
 *
 *   [ stream bytes ][ bitmap header (4 B) ][ page-major 1bpp bitmap ]
 *
 * Nothing here touches src/, tools/fx_pack/ or research/.
 */
#ifndef FX_IMAGE_CORE_H
#define FX_IMAGE_CORE_H

#include <stddef.h>
#include <stdint.h>

/* Default W25Q128 chip size and the page size FX::begin() takes. */
#define FX_IMAGE_CHIP_BYTES_DEFAULT (16u * 1024u * 1024u)
#define FX_IMAGE_PAGE_BYTES_DEFAULT (256u)

/* FX bitmap header: [width_hi width_lo height_hi height_lo], little-endian. */
#define FX_IMAGE_BITMAP_HEADER_BYTES (4u)

/* Maximum number of named streams in one multi-stream image. */
#define FX_IMAGE_MAX_STREAMS (64u)

/* A parsed/constructed FX 1bpp bitmap. `data` is owned by the struct and must
 * be released with fx_bitmap_free(). */
struct fx_bitmap {
	uint16_t width;    /* columns; one byte per column per page */
	uint16_t height;   /* rows in pixels */
	uint8_t *data;     /* page-major 1bpp, ((height+7)/8)*width bytes */
	size_t data_len;
};

/* Placement of the data section on the chip and its 24-bit extents. */
struct fx_layout {
	uint32_t stream_len;
	uint32_t bitmap_offset;   /* == stream_len, data-section relative */
	uint32_t bitmap_data_len;
	uint32_t bitmap_len;      /* header + data */
	uint32_t image_len;
	uint32_t data_bytes;      /* image_len rounded up to a whole page */
	uint32_t data_offset;     /* chip-relative base of the data section */
	uint32_t data_page;       /* FX::begin(page) argument */
	uint32_t abs_stream_addr;
	uint32_t abs_stream_end;  /* one past the last stream byte */
	uint32_t abs_bitmap_addr;
	uint32_t abs_bitmap_end;  /* one past the last image byte */
	uint32_t chip_bytes;
	uint32_t page_bytes;
	uint8_t  fits_24bit;      /* all absolute addresses fit in 24 bits */
};

/* --- bitmap construction ------------------------------------------------- */

/* Convert an ASCII P1 or binary P4 netpbm (PBM) image into FX page-major 1bpp.
 * Pixel (x, y) of value 1 (black) sets bit (y & 7) of byte
 * ((y >> 3) * width + x). */
int fx_image_pbm_to_bitmap(const uint8_t *pbm, size_t len,
	struct fx_bitmap *out, char *err, size_t errlen);

/* Wrap already page-major 1bpp bytes (`raw_len` must equal
 * ((height+7)/8)*width). The bytes are copied. */
int fx_image_raw_to_bitmap(const uint8_t *raw, size_t raw_len,
	uint16_t width, uint16_t height,
	struct fx_bitmap *out, char *err, size_t errlen);

/* Deterministic built-in bitmap matching the reference packer's checker
 * (byte i = ((i*7+3)&0xFF) ^ i). Used for the selftest and as a fallback. */
int fx_image_fixture_bitmap(uint16_t width, uint16_t height,
	struct fx_bitmap *out, char *err, size_t errlen);

void fx_bitmap_free(struct fx_bitmap *bm);

/* --- layout and composition ---------------------------------------------- */

/* Compute the data-section placement and the data-section-relative 24-bit
 * extents. `stream_len` is the compact stream length; `bitmap_data_len` is the
 * page-major bitmap payload length (header excluded). The image is placed at
 * the top of the chip, rounded up to a page. */
int fx_image_layout(uint32_t stream_len, uint32_t bitmap_data_len,
	uint32_t chip_bytes, uint32_t page_bytes,
	struct fx_layout *out, char *err, size_t errlen);

/* Allocate and fill the fxdata image: [stream][bitmap header][bitmap data].
 * Caller frees *image_out. */
int fx_image_compose(const uint8_t *stream, uint32_t stream_len,
	const struct fx_bitmap *bm,
	uint8_t **image_out, size_t *image_len_out,
	char *err, size_t errlen);

/* --- multi-stream layout and composition --------------------------------- */

/* Placement of a multi-stream data section. The N streams are packed densely
 * in input order starting at data-section-relative offset 0; an optional
 * bitmap follows the last stream. This keeps a one-stream image byte-identical
 * to the legacy single-stream layout ([stream][bitmap header][bitmap data]).
 * Offsets/lengths are data-section-relative 24-bit values; the data page is
 * added exactly once by the caller. There is no per-stream padding; a stream
 * may start at any byte offset. */
struct fx_multi_layout {
	uint32_t stream_count;
	uint32_t stream_offset[FX_IMAGE_MAX_STREAMS];
	uint32_t stream_len[FX_IMAGE_MAX_STREAMS];
	uint8_t  has_bitmap;
	uint32_t bitmap_offset;   /* == sum(stream_len), data-section relative */
	uint32_t bitmap_data_len; /* 0 when absent */
	uint32_t bitmap_len;      /* header + data, 0 when absent */
	uint32_t image_len;
	uint32_t data_bytes;      /* image_len rounded up to a whole page */
	uint32_t data_offset;     /* chip-relative base of the data section */
	uint32_t data_page;       /* FX::begin(page) argument */
	uint32_t abs_bitmap_end;  /* one past the last image byte */
	uint32_t chip_bytes;
	uint32_t page_bytes;
	uint8_t  fits_24bit;
};

/* Compute the multi-stream placement and extents. `stream_lens[0..count)` are
 * the compact stream lengths in input order. `has_bitmap` selects whether a
 * bitmap region follows the streams (`bitmap_data_len` is its page-major
 * payload length, header excluded). Rejects an empty stream list, too many
 * streams, empty/oversize (> 24-bit) streams, an empty bitmap, a non-power-of-
 * two page, and an image that does not fit the chip. */
int fx_image_layout_multi(const uint32_t *stream_lens, uint32_t stream_count,
	int has_bitmap, uint32_t bitmap_data_len,
	uint32_t chip_bytes, uint32_t page_bytes,
	struct fx_multi_layout *out, char *err, size_t errlen);

/* Allocate and fill a multi-stream image:
 *   [stream0][stream1]...[streamN-1][bitmap header][bitmap data]
 * Each `streams[i]` must have `stream_lens[i] > 0` bytes; `bm` may be NULL for
 * a streams-only image. Caller frees *image_out. */
int fx_image_compose_multi(const uint8_t *const *streams,
	const uint32_t *stream_lens, uint32_t stream_count,
	const struct fx_bitmap *bm,
	uint8_t **image_out, size_t *image_len_out,
	char *err, size_t errlen);

#endif /* FX_IMAGE_CORE_H */
