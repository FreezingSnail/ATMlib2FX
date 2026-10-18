/*
 * fx_image_test.c - host selftest for the FX data-image packer core
 * (ATMlib2FX-hlh.10).
 *
 * Pure C, no framework: builds tools/fx_image/fx_image_core.c and exercises the
 * bitmap parsing/conversion, the data-section placement, the single-page 24-bit
 * extent arithmetic and the compose/header bytes. Shell-driven end-to-end and
 * CLI checks live in tests/fx_image/run-tests.sh.
 *
 * Usage: fx_image_test
 */
#include "fx_image_core.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures = 0;
static int checks = 0;

#define CHECK(cond, ...) do { \
	checks++; \
	if (!(cond)) { \
		failures++; \
		printf("FAIL %s:%d: ", __FILE__, __LINE__); \
		printf(__VA_ARGS__); \
		printf("\n"); \
	} \
} while (0)

static void test_layout_reference(void)
{
	char err[256];
	struct fx_layout L;
	int rc = fx_image_layout(1572, 64, FX_IMAGE_CHIP_BYTES_DEFAULT,
		FX_IMAGE_PAGE_BYTES_DEFAULT, &L, err, sizeof(err));
	CHECK(rc == 0, "layout reference failed: %s", err);
	CHECK(L.stream_len == 1572, "stream_len %u", L.stream_len);
	CHECK(L.bitmap_offset == 1572, "bitmap_offset %u", L.bitmap_offset);
	CHECK(L.bitmap_data_len == 64, "bitmap_data_len %u", L.bitmap_data_len);
	CHECK(L.bitmap_len == 68, "bitmap_len %u", L.bitmap_len);
	CHECK(L.image_len == 1640, "image_len %u", L.image_len);
	CHECK(L.data_bytes == 1792, "data_bytes %u", L.data_bytes);
	/* Reference fx_make_fxdata printed data_page=65529 / abs=16775424. */
	CHECK(L.data_page == 65529, "data_page %u", L.data_page);
	CHECK(L.data_offset == 16775424, "data_offset %u", L.data_offset);
	CHECK(L.abs_stream_addr == 16775424, "abs_stream_addr %u", L.abs_stream_addr);
	CHECK(L.abs_stream_end == 16776996, "abs_stream_end %u", L.abs_stream_end);
	CHECK(L.abs_bitmap_addr == 16776996, "abs_bitmap_addr %u", L.abs_bitmap_addr);
	CHECK(L.abs_bitmap_end == 16777064, "abs_bitmap_end %u", L.abs_bitmap_end);
	CHECK(L.fits_24bit == 1, "fits_24bit %u", L.fits_24bit);
}

static void test_single_page_add(void)
{
	char err[256];
	struct fx_layout L;
	/* The data page is added exactly once: every absolute address equals the
	 * data-section base plus the data-section-relative offset. */
	CHECK(fx_image_layout(1000, 100, FX_IMAGE_CHIP_BYTES_DEFAULT, 256,
		&L, err, sizeof(err)) == 0, "layout failed: %s", err);
	CHECK(L.data_offset == L.data_page * L.page_bytes,
		"page add mismatch: %u != %u*%u",
		L.data_offset, L.data_page, L.page_bytes);
	CHECK(L.abs_stream_addr == L.data_offset + 0, "stream add");
	CHECK(L.abs_stream_end == L.data_offset + L.stream_len, "stream end add");
	CHECK(L.abs_bitmap_addr == L.data_offset + L.bitmap_offset, "bitmap add");
	CHECK(L.abs_bitmap_end == L.data_offset + L.image_len, "bitmap end add");
}

static void test_page_boundary_exact(void)
{
	char err[256];
	struct fx_layout L;
	/* stream + header + bitmap_data = 1024 exactly -> data_bytes == image. */
	CHECK(fx_image_layout(1000, 20, 16u * 1024u * 1024u, 256, &L, err,
		sizeof(err)) == 0, "layout failed: %s", err);
	CHECK(L.image_len == 1024, "image_len %u", L.image_len);
	CHECK(L.data_bytes == 1024, "data_bytes %u", L.data_bytes);
	/* one byte over -> next page. */
	CHECK(fx_image_layout(1001, 20, 16u * 1024u * 1024u, 256, &L, err,
		sizeof(err)) == 0, "layout failed: %s", err);
	CHECK(L.data_bytes == 1280, "data_bytes %u", L.data_bytes);
}

static void test_layout_rejections(void)
{
	char err[256];
	struct fx_layout L;
	CHECK(fx_image_layout(0, 64, 16u * 1024u * 1024u, 256, &L, err,
		sizeof(err)) != 0, "empty stream accepted");
	CHECK(fx_image_layout(10, 0, 16u * 1024u * 1024u, 256, &L, err,
		sizeof(err)) != 0, "empty bitmap accepted");
	CHECK(fx_image_layout(10, 10, 16u * 1024u * 1024u, 200, &L, err,
		sizeof(err)) != 0, "non-power-of-two page accepted");
	CHECK(fx_image_layout(0xFFFFFF, 0xFFFFFF, 16u * 1024u * 1024u, 256,
		&L, err, sizeof(err)) != 0, "oversize image accepted");
}

static void test_fixture_bitmap(void)
{
	char err[256];
	struct fx_bitmap bm;
	CHECK(fx_image_fixture_bitmap(32, 16, &bm, err, sizeof(err)) == 0,
		"fixture failed: %s", err);
	CHECK(bm.width == 32 && bm.height == 16, "fixture dims");
	CHECK(bm.data_len == 64, "fixture data_len %zu", bm.data_len);
	for (size_t i = 0; i < bm.data_len; i++) {
		uint8_t want = (uint8_t)(((i * 7u + 3u) & 0xFFu) ^ (uint8_t)i);
		if (bm.data[i] != want) {
			CHECK(0, "fixture byte %zu = %u want %u", i, bm.data[i], want);
			break;
		}
	}
	fx_bitmap_free(&bm);
	/* Determinism. */
	struct fx_bitmap bm2;
	CHECK(fx_image_fixture_bitmap(32, 16, &bm2, err, sizeof(err)) == 0,
		"fixture2 failed");
	CHECK(bm2.data_len == 64, "fixture2 len");
	fx_bitmap_free(&bm2);
}

static void test_raw_bitmap(void)
{
	char err[256];
	uint8_t raw[4] = { 0xAA, 0x55, 0x0F, 0xF0 };
	struct fx_bitmap bm;
	/* width 4, height 8 -> pages = 1, data = 4 bytes. */
	CHECK(fx_image_raw_to_bitmap(raw, sizeof(raw), 4, 8, &bm, err,
		sizeof(err)) == 0, "raw failed: %s", err);
	CHECK(bm.data_len == 4 && memcmp(bm.data, raw, 4) == 0, "raw copy");
	fx_bitmap_free(&bm);
	CHECK(fx_image_raw_to_bitmap(raw, 3, 4, 8, &bm, err, sizeof(err)) != 0,
		"raw length mismatch accepted");
}

/* 8x8 image: black at (x=1,y=0) and (x=2,y=3). */
static void test_pbm_p1(void)
{
	char err[256];
	const char *p1 =
		"P1\n# comment\n8 8\n"
		"0 1 0 0 0 0 0 0\n"
		"0 0 0 0 0 0 0 0\n"
		"0 0 0 0 0 0 0 0\n"
		"0 0 1 0 0 0 0 0\n"
		"0 0 0 0 0 0 0 0\n"
		"0 0 0 0 0 0 0 0\n"
		"0 0 0 0 0 0 0 0\n"
		"0 0 0 0 0 0 0 0\n";
	struct fx_bitmap bm;
	CHECK(fx_image_pbm_to_bitmap((const uint8_t *)p1, strlen(p1), &bm, err,
		sizeof(err)) == 0, "P1 parse failed: %s", err);
	CHECK(bm.width == 8 && bm.height == 8, "P1 dims %u x %u", bm.width, bm.height);
	CHECK(bm.data_len == 8, "P1 data_len %zu", bm.data_len);
	CHECK(bm.data[1] == 0x01, "P1 byte1 0x%02x", bm.data[1]);
	CHECK(bm.data[2] == 0x08, "P1 byte2 0x%02x", bm.data[2]);
	fx_bitmap_free(&bm);
}

static void test_pbm_p4_matches_p1(void)
{
	char err[256];
	/* Same 8x8 image, packed rows, MSB leftmost. */
	uint8_t p4[] = {
		'P', '4', '\n', '8', ' ', '8', '\n',
		0x40, 0x00, 0x00, 0x20, 0x00, 0x00, 0x00, 0x00
	};
	struct fx_bitmap bm;
	CHECK(fx_image_pbm_to_bitmap(p4, sizeof(p4), &bm, err, sizeof(err)) == 0,
		"P4 parse failed: %s", err);
	CHECK(bm.width == 8 && bm.height == 8, "P4 dims");
	CHECK(bm.data[1] == 0x01 && bm.data[2] == 0x08,
		"P4 bytes %02x %02x", bm.data[1], bm.data[2]);
	fx_bitmap_free(&bm);
}

static void test_pbm_rejections(void)
{
	char err[256];
	struct fx_bitmap bm;
	const char *bad_magic = "P2\n8 8\n0 0 0 0\n";
	CHECK(fx_image_pbm_to_bitmap((const uint8_t *)bad_magic,
		strlen(bad_magic), &bm, err, sizeof(err)) != 0, "P2 accepted");
	const char *short_p1 = "P1\n8 8\n0 1 0\n";
	CHECK(fx_image_pbm_to_bitmap((const uint8_t *)short_p1,
		strlen(short_p1), &bm, err, sizeof(err)) != 0, "short P1 accepted");
	const char *zero = "P1\n0 8\n";
	CHECK(fx_image_pbm_to_bitmap((const uint8_t *)zero, strlen(zero), &bm,
		err, sizeof(err)) != 0, "zero width accepted");
}

static void test_compose(void)
{
	char err[256];
	uint8_t stream[8] = { 0xC0, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x00 };
	struct fx_bitmap bm;
	CHECK(fx_image_fixture_bitmap(32, 16, &bm, err, sizeof(err)) == 0,
		"fixture failed");
	uint8_t *image = NULL;
	size_t image_len = 0;
	CHECK(fx_image_compose(stream, sizeof(stream), &bm, &image, &image_len,
		err, sizeof(err)) == 0, "compose failed: %s", err);
	CHECK(image_len == sizeof(stream) + 4 + bm.data_len, "compose len %zu",
		image_len);
	CHECK(memcmp(image, stream, sizeof(stream)) == 0, "compose stream copy");
	/* Bitmap header, little endian width/height. */
	CHECK(image[8] == 0x00 && image[9] == 32, "header width %02x %02x",
		image[8], image[9]);
	CHECK(image[10] == 0x00 && image[11] == 16, "header height %02x %02x",
		image[10], image[11]);
	CHECK(memcmp(image + 12, bm.data, bm.data_len) == 0, "compose bitmap copy");
	/* layout's image_len must equal the composed length. */
	struct fx_layout L;
	CHECK(fx_image_layout(sizeof(stream), (uint32_t)bm.data_len,
		FX_IMAGE_CHIP_BYTES_DEFAULT, FX_IMAGE_PAGE_BYTES_DEFAULT,
		&L, err, sizeof(err)) == 0, "layout failed");
	CHECK((size_t)L.image_len == image_len, "layout/compose len mismatch");
	free(image);
	fx_bitmap_free(&bm);
}

/* --- multi-stream mode ----------------------------------------------------- */

/* Three streams packed densely in input order then the bitmap. */
static void test_multi_layout_offsets(void)
{
	char err[256];
	struct fx_multi_layout M;
	uint32_t lens[3] = { 5, 7, 3 };
	CHECK(fx_image_layout_multi(lens, 3, 1, 64,
		FX_IMAGE_CHIP_BYTES_DEFAULT, FX_IMAGE_PAGE_BYTES_DEFAULT,
		&M, err, sizeof(err)) == 0, "multi layout failed: %s", err);
	CHECK(M.stream_count == 3, "count %u", M.stream_count);
	CHECK(M.stream_offset[0] == 0, "off0 %u", M.stream_offset[0]);
	CHECK(M.stream_offset[1] == 5, "off1 %u", M.stream_offset[1]);
	CHECK(M.stream_offset[2] == 12, "off2 %u", M.stream_offset[2]);
	CHECK(M.stream_len[0] == 5 && M.stream_len[1] == 7 &&
		M.stream_len[2] == 3, "lens");
	CHECK(M.has_bitmap == 1, "has_bitmap %u", M.has_bitmap);
	CHECK(M.bitmap_offset == 15, "bitmap_offset %u", M.bitmap_offset);
	CHECK(M.bitmap_len == 68, "bitmap_len %u", M.bitmap_len);
	CHECK(M.image_len == 83, "image_len %u", M.image_len);
	CHECK(M.data_bytes == 256, "data_bytes %u", M.data_bytes);
	/* The page is added exactly once; every abs address is base+relative. */
	CHECK(M.data_offset % M.page_bytes == 0, "data base not page aligned");
	CHECK(M.abs_bitmap_end == M.data_offset + M.image_len,
		"abs end %u", M.abs_bitmap_end);
	CHECK(M.abs_bitmap_end <= 0x01000000u, "abs end 24-bit");
	CHECK(M.fits_24bit == 1, "fits_24bit %u", M.fits_24bit);
}

/* A one-stream image must match the legacy single-stream layout byte-for-byte
 * (single mode is the golden). */
static void test_multi_equals_single(void)
{
	char err[256];
	struct fx_layout L;
	struct fx_multi_layout M;
	uint32_t lens[1] = { 1572 };
	CHECK(fx_image_layout(1572, 64, FX_IMAGE_CHIP_BYTES_DEFAULT,
		FX_IMAGE_PAGE_BYTES_DEFAULT, &L, err, sizeof(err)) == 0,
		"single layout failed");
	CHECK(fx_image_layout_multi(lens, 1, 1, 64,
		FX_IMAGE_CHIP_BYTES_DEFAULT, FX_IMAGE_PAGE_BYTES_DEFAULT,
		&M, err, sizeof(err)) == 0, "multi layout failed");
	CHECK(M.stream_offset[0] == 0, "off0 %u", M.stream_offset[0]);
	CHECK(M.stream_len[0] == L.stream_len, "len");
	CHECK(M.bitmap_offset == L.bitmap_offset, "bitmap_offset");
	CHECK(M.image_len == L.image_len, "image_len");
	CHECK(M.data_bytes == L.data_bytes, "data_bytes");
	CHECK(M.data_offset == L.data_offset, "data_offset");
	CHECK(M.data_page == L.data_page, "data_page");
	CHECK(M.abs_bitmap_end == L.abs_bitmap_end, "abs end");

	/* Compose bytes: [stream][bitmap header][bitmap data]. */
	uint8_t stream[8] = { 0xC0, 1, 2, 3, 4, 5, 6, 7 };
	struct fx_bitmap bm;
	CHECK(fx_image_fixture_bitmap(32, 16, &bm, err, sizeof(err)) == 0,
		"fixture failed");
	uint8_t *img1 = NULL, *img2 = NULL;
	size_t n1 = 0, n2 = 0;
	CHECK(fx_image_compose(stream, sizeof(stream), &bm, &img1, &n1,
		err, sizeof(err)) == 0, "compose single failed");
	const uint8_t *streams[1] = { stream };
	uint32_t ls[1] = { sizeof(stream) };
	CHECK(fx_image_compose_multi(streams, ls, 1, &bm, &img2, &n2,
		err, sizeof(err)) == 0, "compose multi failed");
	CHECK(n1 == n2, "compose len %zu %zu", n1, n2);
	CHECK(memcmp(img1, img2, n1) == 0, "compose single/multi differ");
	free(img1);
	free(img2);
	fx_bitmap_free(&bm);
}

/* Byte parity of each embedded stream against its source, and determinism. */
static void test_multi_parity_and_determinism(void)
{
	char err[256];
	uint8_t a[4] = { 0xC0, 0xAA, 0xBB, 0x00 };
	uint8_t b[6] = { 0xC1, 1, 2, 3, 4, 5 };
	uint8_t c[2] = { 0xC0, 0x7F };
	const uint8_t *streams[3] = { a, b, c };
	uint32_t lens[3] = { sizeof(a), sizeof(b), sizeof(c) };
	struct fx_bitmap bm;
	CHECK(fx_image_fixture_bitmap(32, 16, &bm, err, sizeof(err)) == 0,
		"fixture failed");

	uint8_t *img = NULL;
	size_t n = 0;
	CHECK(fx_image_compose_multi(streams, lens, 3, &bm, &img, &n,
		err, sizeof(err)) == 0, "compose failed: %s", err);

	struct fx_multi_layout M;
	CHECK(fx_image_layout_multi(lens, 3, 1, (uint32_t)bm.data_len,
		FX_IMAGE_CHIP_BYTES_DEFAULT, FX_IMAGE_PAGE_BYTES_DEFAULT,
		&M, err, sizeof(err)) == 0, "layout failed");
	CHECK((size_t)M.image_len == n, "image_len %u != %zu", M.image_len, n);

	/* Every stream payload appears at its declared offset. */
	CHECK(memcmp(img + M.stream_offset[0], a, sizeof(a)) == 0, "parity s0");
	CHECK(memcmp(img + M.stream_offset[1], b, sizeof(b)) == 0, "parity s1");
	CHECK(memcmp(img + M.stream_offset[2], c, sizeof(c)) == 0, "parity s2");
	/* Bitmap header then data at the declared offset. */
	CHECK(img[M.bitmap_offset] == 0x00 && img[M.bitmap_offset + 1] == 32,
		"bm header width");
	CHECK(memcmp(img + M.bitmap_offset + 4, bm.data, bm.data_len) == 0,
		"bm parity");

	/* Determinism: a second compose is byte-identical. */
	uint8_t *img2 = NULL;
	size_t n2 = 0;
	CHECK(fx_image_compose_multi(streams, lens, 3, &bm, &img2, &n2,
		err, sizeof(err)) == 0, "compose2 failed");
	CHECK(n == n2 && memcmp(img, img2, n) == 0, "not deterministic");
	free(img);
	free(img2);
	fx_bitmap_free(&bm);
}

static void test_multi_no_bitmap(void)
{
	char err[256];
	struct fx_multi_layout M;
	uint32_t lens[2] = { 10, 20 };
	CHECK(fx_image_layout_multi(lens, 2, 0, 0, 16u * 1024u * 1024u, 256,
		&M, err, sizeof(err)) == 0, "layout failed: %s", err);
	CHECK(M.has_bitmap == 0, "has_bitmap %u", M.has_bitmap);
	CHECK(M.bitmap_len == 0, "bitmap_len %u", M.bitmap_len);
	CHECK(M.bitmap_offset == 0, "bitmap_offset %u", M.bitmap_offset);
	CHECK(M.image_len == 30, "image_len %u", M.image_len);
	CHECK(M.data_bytes == 256, "data_bytes %u", M.data_bytes);
	CHECK(M.abs_bitmap_end == M.data_offset + 30, "abs end");

	uint8_t a[10], b[20];
	memset(a, 0x11, sizeof(a));
	memset(b, 0x22, sizeof(b));
	const uint8_t *streams[2] = { a, b };
	uint8_t *img = NULL;
	size_t n = 0;
	CHECK(fx_image_compose_multi(streams, lens, 2, NULL, &img, &n,
		err, sizeof(err)) == 0, "compose failed: %s", err);
	CHECK(n == 30, "compose len %zu", n);
	CHECK(memcmp(img, a, 10) == 0 && memcmp(img + 10, b, 20) == 0,
		"streams-only parity");
	free(img);
}

static void test_multi_page_math(void)
{
	char err[256];
	struct fx_multi_layout M;
	/* sum streams + header + bitmap == 1024 exactly. */
	uint32_t lens[1] = { 900 };
	CHECK(fx_image_layout_multi(lens, 1, 1, 120, 16u * 1024u * 1024u, 256,
		&M, err, sizeof(err)) == 0, "layout failed: %s", err);
	CHECK(M.image_len == 1024, "image_len %u", M.image_len);
	CHECK(M.data_bytes == 1024, "data_bytes %u", M.data_bytes);
	/* One byte over -> next page. */
	CHECK(fx_image_layout_multi(lens, 1, 1, 121, 16u * 1024u * 1024u, 256,
		&M, err, sizeof(err)) == 0, "layout failed");
	CHECK(M.image_len == 1025, "image_len %u", M.image_len);
	CHECK(M.data_bytes == 1280, "data_bytes %u", M.data_bytes);
	CHECK(M.data_page == M.data_offset / 256, "page math");
}

static void test_multi_layout_rejections(void)
{
	char err[256];
	struct fx_multi_layout M;
	uint32_t lens[3] = { 5, 7, 3 };
	uint32_t one_empty[1] = { 0 };
	uint32_t big[1] = { 0x1000000u };

	CHECK(fx_image_layout_multi(NULL, 0, 0, 0, 16u * 1024u * 1024u, 256,
		&M, err, sizeof(err)) != 0, "empty stream list accepted");
	CHECK(fx_image_layout_multi(lens, FX_IMAGE_MAX_STREAMS + 1, 0, 0,
		16u * 1024u * 1024u, 256, &M, err, sizeof(err)) != 0,
		"too many streams accepted");
	CHECK(fx_image_layout_multi(one_empty, 1, 0, 0, 16u * 1024u * 1024u,
		256, &M, err, sizeof(err)) != 0, "empty stream accepted");
	CHECK(fx_image_layout_multi(big, 1, 0, 0, 16u * 1024u * 1024u, 256,
		&M, err, sizeof(err)) != 0, "24-bit overflow accepted");
	CHECK(fx_image_layout_multi(lens, 3, 1, 0, 16u * 1024u * 1024u, 256,
		&M, err, sizeof(err)) != 0, "empty bitmap accepted");
	CHECK(fx_image_layout_multi(lens, 3, 0, 0, 16u * 1024u * 1024u, 200,
		&M, err, sizeof(err)) != 0, "non-pow2 page accepted");
	CHECK(fx_image_layout_multi(lens, 3, 1, 0xFFFFFFu, 16u * 1024u * 1024u,
		256, &M, err, sizeof(err)) != 0, "oversize image accepted");
}

static void test_multi_compose_rejections(void)
{
	char err[256];
	uint8_t a[4] = { 1, 2, 3, 4 };
	const uint8_t *streams[1] = { a };
	uint32_t lens[1] = { sizeof(a) };
	uint8_t *img = NULL;
	size_t n = 0;
	CHECK(fx_image_compose_multi(NULL, lens, 1, NULL, &img, &n,
		err, sizeof(err)) != 0, "null streams accepted");
	uint32_t empty[1] = { 0 };
	CHECK(fx_image_compose_multi(streams, empty, 1, NULL, &img, &n,
		err, sizeof(err)) != 0, "empty stream accepted");
	/* A bitmap with no data must be rejected when supplied. */
	struct fx_bitmap zero;
	memset(&zero, 0, sizeof(zero));
	CHECK(fx_image_compose_multi(streams, lens, 1, &zero, &img, &n,
		err, sizeof(err)) != 0, "empty bitmap accepted");
}

int main(void)
{
	test_layout_reference();
	test_single_page_add();
	test_page_boundary_exact();
	test_layout_rejections();
	test_fixture_bitmap();
	test_raw_bitmap();
	test_pbm_p1();
	test_pbm_p4_matches_p1();
	test_pbm_rejections();
	test_compose();
	test_multi_layout_offsets();
	test_multi_equals_single();
	test_multi_parity_and_determinism();
	test_multi_no_bitmap();
	test_multi_page_math();
	test_multi_layout_rejections();
	test_multi_compose_rejections();

	printf("fx_image_test: %d checks, %d failures\n", checks, failures);
	return failures == 0 ? 0 : 1;
}
