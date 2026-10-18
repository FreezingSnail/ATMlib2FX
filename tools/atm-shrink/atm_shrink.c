/*
 * atm_shrink.c - CLI for the offline ATMlib2 song-shrink pass (ATMlib2FX-hlh.3).
 *
 * Reads a packed ATMlib2 score (ATM_SCORE_FMT_FULL / FULL_MONO) as a binary
 * blob, applies the shrink transforms in shrink_core.c and writes:
 *   --out-blob    the shrunk packed score (binary)
 *   --out-header  a drop-in song.h defining `score` (and `sfx1` if given)
 *   --report      a text report (bytes before/after, patterns added/removed,
 *                 call depth used, per-transform savings)
 *
 * The packed blob is the exact PROGMEM layout; extract one from a song .h with
 * tools/atm-shrink/score_dump.c.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "shrink_core.h"

static uint8_t *read_file(const char *path, size_t *out_len)
{
	FILE *f = fopen(path, "rb");
	if (!f) { perror(path); return NULL; }
	if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return NULL; }
	long n = ftell(f);
	if (n < 0) { fclose(f); return NULL; }
	rewind(f);
	uint8_t *buf = malloc((size_t)n ? (size_t)n : 1);
	if (!buf) { fclose(f); return NULL; }
	if (n > 0 && fread(buf, 1, (size_t)n, f) != (size_t)n) {
		free(buf); fclose(f); return NULL;
	}
	fclose(f);
	*out_len = (size_t)n;
	return buf;
}

int main(int argc, char **argv)
{
	const char *in_path = NULL, *sfx_path = NULL;
	const char *out_blob = NULL, *out_header = NULL, *report_path = NULL;
	const char *label = "score";
	int do_loop = 1, do_inline = 1, do_share = 1, flat = 0;

	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "--in") && i + 1 < argc) in_path = argv[++i];
		else if (!strcmp(argv[i], "--sfx") && i + 1 < argc) sfx_path = argv[++i];
		else if (!strcmp(argv[i], "--out-blob") && i + 1 < argc) out_blob = argv[++i];
		else if (!strcmp(argv[i], "--out-header") && i + 1 < argc) out_header = argv[++i];
		else if (!strcmp(argv[i], "--report") && i + 1 < argc) report_path = argv[++i];
		else if (!strcmp(argv[i], "--label") && i + 1 < argc) label = argv[++i];
		else if (!strcmp(argv[i], "--no-loop")) do_loop = 0;
		else if (!strcmp(argv[i], "--no-inline")) do_inline = 0;
		else if (!strcmp(argv[i], "--no-share")) do_share = 0;
		else if (!strcmp(argv[i], "--flat")) flat = 1;
		else {
			fprintf(stderr, "atm_shrink: unknown arg %s\n", argv[i]);
			fprintf(stderr, "usage: atm_shrink --in <blob> [--sfx <blob>] "
				"[--out-blob f] [--out-header f] [--report f] "
				"[--label s] [--no-loop] [--no-inline] [--no-share]\n");
			return 2;
		}
	}

	if (!in_path) { fprintf(stderr, "atm_shrink: --in is required\n"); return 2; }

	size_t in_len = 0;
	uint8_t *in = read_file(in_path, &in_len);
	if (!in) return 1;

	struct shrink_score s;
	int rc = shrink_parse(&s, in, in_len);
	if (rc != SHRINK_OK) {
		fprintf(stderr, "atm_shrink: %s: unsupported score format "
			"(fmt=0x%02x); the engine handles ATM_SCORE_FMT_FULL/FULL_MONO "
			"pattern scores only (legacy raw byte arrays are not supported)\n",
			in_path, in_len ? in[0] : 0);
		free(in);
		return 3;
	}
	s.loop_present = 0;

	if (sfx_path) {
		size_t sl = 0;
		uint8_t *sb = read_file(sfx_path, &sl);
		if (sb) { shrink_parse_sfx(&s, sb, sl); free(sb); }
	}

	int before = shrink_score_bytes(&s);
	int pat_before = shrink_pattern_count(&s);
	int depth_before = shrink_max_depth(&s);

	/* The library skips CALL at pstack_index >= ATM_PATTERN_STACK_DEPTH-1
	 * (src/cmd_parse.c), so an input that already reaches the depth limit
	 * plays differently from any statically flattened rewrite. Gate on the
	 * input semantics, independent of the transforms. */
	if (depth_before >= SHRINK_STACK_DEPTH) {
		fprintf(stderr, "atm_shrink: rejecting input: call depth %d reaches "
			"limit %d (the library skips calls at pstack_index %d); "
			"rewriting could change playback\n",
			depth_before + 1, SHRINK_STACK_DEPTH, SHRINK_STACK_DEPTH - 1);
		free(in);
		return 4;
	}

	int loop_saved = do_loop ? shrink_loop_normalize(&s) : 0;
	int inline_saved = do_inline ? shrink_inline_single_use(&s) : 0;
	int share_saved = do_share ? shrink_share_runs(&s) : 0;

	if (shrink_finalize(&s) != SHRINK_OK) {
		fprintf(stderr, "atm_shrink: internal remap failure\n");
		free(in);
		return 1;
	}

	int after = shrink_score_bytes(&s);
	int pat_after = shrink_pattern_count(&s);
	int depth_after = shrink_max_depth(&s);

	if (depth_after >= SHRINK_STACK_DEPTH) {
		fprintf(stderr, "atm_shrink: rejecting result: call depth %d "
			"reaches limit %d\n", depth_after + 1, SHRINK_STACK_DEPTH);
		free(in);
		return 4;
	}

	if (out_blob) {
		uint8_t buf[1 << 16];
		size_t n = shrink_emit_blob(&s, buf, sizeof(buf));
		if (!n) { fprintf(stderr, "atm_shrink: blob too large\n"); free(in); return 1; }
		FILE *f = fopen(out_blob, "wb");
		if (!f) { perror(out_blob); free(in); return 1; }
		fwrite(buf, 1, n, f);
		fclose(f);
	}
	if (out_header) {
		FILE *f = fopen(out_header, "w");
		if (!f) { perror(out_header); free(in); return 1; }
		if (flat) shrink_emit_flat_header(&s, f, label);
		else shrink_emit_header(&s, f, label);
		fclose(f);
	}

	FILE *r = report_path ? fopen(report_path, "w") : stdout;
	if (!r) { perror(report_path); free(in); return 1; }
	int pat_added = 0;
	for (int i = 0; i < s.npat; i++)
		if (s.pat[i].shared) pat_added++;
	fprintf(r, "atm-shrink report\n");
	fprintf(r, "label: %s\n", label);
	fprintf(r, "input_blob_bytes: %zu\n", in_len);
	fprintf(r, "score_bytes_before: %d\n", before);
	fprintf(r, "score_bytes_after: %d\n", after);
	fprintf(r, "score_bytes_saved: %d\n", before - after);
	fprintf(r, "patterns_before: %d\n", pat_before);
	fprintf(r, "patterns_after: %d\n", pat_after);
	fprintf(r, "patterns_added: %d\n", pat_added);
	fprintf(r, "patterns_removed: %d\n", pat_before + pat_added - pat_after);
	fprintf(r, "depth_before: %d\n", depth_before);
	fprintf(r, "depth_after: %d\n", depth_after);
	fprintf(r, "loop_present: %d\n", s.loop_present);
	fprintf(r, "transform_loop_saved_bytes: %d\n", loop_saved);
	fprintf(r, "transform_inline_saved_bytes: %d\n", inline_saved);
	fprintf(r, "transform_share_saved_bytes: %d\n", share_saved);
	if (r != stdout) fclose(r);

	free(in);
	return 0;
}
