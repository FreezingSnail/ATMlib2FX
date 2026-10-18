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

	printf("fx_image_test: %d checks, %d failures\n", checks, failures);
	return failures == 0 ? 0 : 1;
}
