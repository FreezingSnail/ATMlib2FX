/*
 * fx_make_fxdata.c - assemble the FX data image for the stream spike test.
 *
 * Layout: [ stream bytes ][ generated 32x16 1bpp bitmap ]
 *
 * The image is what absim loads into the emulated W25Q128. In absim's non-cart
 * layout the image is placed at the top of the 16 MB chip, so its absolute
 * flash address (and therefore every stream address) is above 0x010000. The
 * tool computes and prints the FX data page for FX::begin(page) and the asset
 * offsets. The bitmap is a deterministic checker so the foreground read cost is
 * stable; it is not a game asset.
 *
 * Not a test harness. Build/run via research/fx/tools/build-fx-stream.sh.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHIP_BYTES (16u * 1024u * 1024u) /* W25Q128 */
#define PAGE_BYTES (256u)

#define BITMAP_W (32)
#define BITMAP_H (16)

static uint8_t *read_file(const char *path, size_t *len)
{
	FILE *f = fopen(path, "rb");
	if (!f) { perror(path); exit(1); }
	fseek(f, 0, SEEK_END);
	long sz = ftell(f);
	fseek(f, 0, SEEK_SET);
	uint8_t *buf = malloc((size_t)sz ? (size_t)sz : 1);
	if (!buf) { perror("malloc"); exit(1); }
	if (fread(buf, 1, (size_t)sz, f) != (size_t)sz) { perror("fread"); exit(1); }
	fclose(f);
	*len = (size_t)sz;
	return buf;
}

int main(int argc, char **argv)
{
	const char *stream_path = NULL;
	const char *out_path = NULL;
	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "--stream") && i + 1 < argc) stream_path = argv[++i];
		else if (!strcmp(argv[i], "--out") && i + 1 < argc) out_path = argv[++i];
		else { fprintf(stderr, "fx_make_fxdata: unknown arg %s\n", argv[i]); return 2; }
	}
	if (!stream_path || !out_path) {
		fprintf(stderr, "usage: fx_make_fxdata --stream <bin> --out <bin>\n");
		return 2;
	}

	size_t slen = 0;
	uint8_t *stream = read_file(stream_path, &slen);

	const size_t bitmap_hdr = 4;
	const size_t bitmap_data = (size_t)((BITMAP_H + 7) / 8) * BITMAP_W;
	const size_t image_len = slen + bitmap_hdr + bitmap_data;

	uint8_t *image = calloc(1, image_len);
	if (!image) { perror("calloc"); return 1; }
	memcpy(image, stream, slen);

	/* [width_hi width_lo height_hi height_lo] then page-major 1bpp pixels */
	uint8_t *bm = image + slen;
	bm[0] = (uint8_t)(BITMAP_W >> 8);
	bm[1] = (uint8_t)(BITMAP_W & 0xFF);
	bm[2] = (uint8_t)(BITMAP_H >> 8);
	bm[3] = (uint8_t)(BITMAP_H & 0xFF);
	for (size_t i = 0; i < bitmap_data; i++) {
		bm[bitmap_hdr + i] = (uint8_t)(((i * 7u + 3u) & 0xFF) ^ (uint8_t)i);
	}

	FILE *f = fopen(out_path, "wb");
	if (!f) { perror(out_path); return 1; }
	if (fwrite(image, 1, image_len, f) != image_len) { perror("fwrite"); return 1; }
	fclose(f);

	/* absim non-cart layout: round image up to a page and place it at the top */
	size_t data_bytes = (image_len + PAGE_BYTES - 1) & ~(size_t)(PAGE_BYTES - 1);
	size_t data_offset = CHIP_BYTES - data_bytes;
	unsigned page = (unsigned)(data_offset / PAGE_BYTES);

	printf("stream_offset=0\n");
	printf("stream_len=%zu\n", slen);
	printf("bitmap_offset=%zu\n", slen);
	printf("image_len=%zu\n", image_len);
	printf("data_page=%u\n", page);
	printf("abs_stream_addr=%u\n", (unsigned)(data_offset + 0));

	free(stream);
	free(image);
	return 0;
}
