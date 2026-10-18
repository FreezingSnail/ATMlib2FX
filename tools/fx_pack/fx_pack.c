/*
 * fx_pack.c - supported host converter for finite-v1 compact FX music streams
 * (ATMlib2FX-hlh.7).
 *
 * Usage:
 *   fx_pack --song <score.h> [--symbol NAME] --out <stream.bin> [--meta M.json]
 *           [--tempo N] [--ticks N] [--ring N] [--format auto|modern|legacy]
 *           [--input-bin PATH] [--workdir DIR] [--cc PATH]
 *
 *   fx_pack --score-bin <flat_score.bin> --out <stream.bin> [...]
 *
 * A song header is extracted at runtime by compiling a tiny probe translation
 * unit that #includes the header and writes the named object's bytes; this is
 * how the CLI takes an arbitrary score instead of a compiled-in fixture. The
 * probe is generated under --workdir (default build/fx-port/pack/work) and is
 * never part of the converter binary. --score-bin bypasses extraction and reads
 * an already-flat score (used by tests and by the future JSON adapter, which
 * links the encoder directly).
 *
 * No network, no installs, no git. Output is deterministic for a given input
 * and option set.
 */
#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>

#include "fx_encode.h"
#include "fx_score.h"

#define DEFAULT_WORKDIR "build/fx-port/pack/work"

static void usage(FILE *f)
{
	fprintf(f,
		"usage: fx_pack --song <score.h> [--symbol NAME] --out <stream.bin>\n"
		"               [--meta <meta.json>] [--input-bin <flat.bin>]\n"
		"               [--tempo N] [--ticks N] [--ring N] [--loops]\n"
		"               [--format auto|modern|legacy]\n"
		"               [--workdir DIR] [--cc PATH]\n"
		"       fx_pack --score-bin <flat_score.bin> --out <stream.bin> [...]\n"
		"\n"
		"  --tempo N     override SET_TEMPO operand (0 = authored, default)\n"
		"  --loops       allow SET_LOOP_PATTERN and emit a loop-capable stream\n"
		"                (default: finite v1, SET_LOOP_PATTERN rejected)\n"
		"  --ticks N     conversion tick cap (default %d)\n"
		"  --ring N      admission ring size in bytes (default %d)\n"
		"  --symbol NAME top-level score object in the header (default: score,\n"
		"                then music)\n",
		FX_ENC_DEFAULT_TICKS, FX_ENC_DEFAULT_RING);
}

static int mkdir_p(const char *path)
{
	char *tmp;
	size_t n;
	int rc = 0;

	if (!path || !*path) return 0;
	tmp = strdup(path);
	if (!tmp) return -1;
	n = strlen(tmp);
	while (n > 1 && tmp[n - 1] == '/') tmp[--n] = '\0';
	for (char *p = tmp + 1; *p; p++) {
		if (*p != '/') continue;
		*p = '\0';
		if (mkdir(tmp, 0777) != 0 && errno != EEXIST) { rc = -1; break; }
		*p = '/';
	}
	if (rc == 0 && mkdir(tmp, 0777) != 0 && errno != EEXIST) rc = -1;
	free(tmp);
	return rc;
}

static char *path_dirname(const char *path)
{
	const char *slash = strrchr(path, '/');
	size_t n;
	char *d;

	if (!slash) return strdup(".");
	n = (size_t)(slash - path);
	if (n == 0) n = 1; /* root */
	d = malloc(n + 1);
	if (!d) return NULL;
	memcpy(d, path, n);
	d[n] = '\0';
	return d;
}

static char *path_join(const char *a, const char *b)
{
	size_t na = strlen(a);
	int need = !(na > 0 && a[na - 1] == '/');
	size_t nb = strlen(b);
	char *r = malloc(na + (size_t)need + nb + 1);
	if (!r) return NULL;
	memcpy(r, a, na);
	if (need) r[na++] = '/';
	memcpy(r + na, b, nb + 1);
	return r;
}

static int file_exists(const char *path)
{
	struct stat st;
	return stat(path, &st) == 0 && S_ISREG(st.st_mode);
}

/* Quote a string for /bin/sh (single quotes, embedded quotes escaped). */
static char *shquote(const char *s)
{
	size_t n = strlen(s);
	char *out = malloc(n * 4 + 3);
	char *w;
	if (!out) return NULL;
	w = out;
	*w++ = '\'';
	for (const char *p = s; *p; p++) {
		if (*p == '\'') {
			memcpy(w, "'\\''", 4);
			w += 4;
		} else {
			*w++ = *p;
		}
	}
	*w++ = '\'';
	*w = '\0';
	return out;
}

static int read_file(const char *path, uint8_t **out, size_t *outlen,
		     char *err, size_t errlen)
{
	FILE *f = fopen(path, "rb");
	long sz;
	uint8_t *buf;

	if (!f) {
		snprintf(err, errlen, "cannot open %s: %s", path, strerror(errno));
		return -1;
	}
	if (fseek(f, 0, SEEK_END) != 0) {
		snprintf(err, errlen, "cannot seek %s", path);
		fclose(f);
		return -1;
	}
	sz = ftell(f);
	if (sz < 0) sz = 0;
	rewind(f);
	buf = malloc((size_t)sz ? (size_t)sz : 1);
	if (!buf) {
		snprintf(err, errlen, "out of memory");
		fclose(f);
		return -1;
	}
	if (fread(buf, 1, (size_t)sz, f) != (size_t)sz) {
		snprintf(err, errlen, "cannot read %s", path);
		free(buf);
		fclose(f);
		return -1;
	}
	fclose(f);
	*out = buf;
	*outlen = (size_t)sz;
	return 0;
}

static int write_file(const char *path, const uint8_t *data, size_t len,
		      char *err, size_t errlen)
{
	FILE *f;
	char *dir = path_dirname(path);
	int rc = 0;

	if (dir) { mkdir_p(dir); free(dir); }
	f = fopen(path, "wb");
	if (!f) {
		snprintf(err, errlen, "cannot open %s for writing: %s", path,
			 strerror(errno));
		return -1;
	}
	if (len && fwrite(data, 1, len, f) != len) {
		snprintf(err, errlen, "cannot write %s", path);
		rc = -1;
	}
	fclose(f);
	return rc;
}

static char *find_repo_src(const char *song)
{
	const char *env = getenv("FX_PACK_SRC");
	char *dir;

	if (env && *env) {
		char *cand = path_join(env, "atm_cmd_constants.h");
		if (cand && file_exists(cand)) {
			free(cand);
			return strdup(env);
		}
		free(cand);
	}

	dir = path_dirname(song);
	while (dir) {
		char *cand = path_join(dir, "src");
		char *hdr = cand ? path_join(cand, "atm_cmd_constants.h") : NULL;
		char *parent;

		if (hdr && file_exists(hdr)) {
			free(hdr);
			free(dir);
			return cand;
		}
		free(hdr);
		free(cand);

		parent = path_dirname(dir);
		if (!parent || !strcmp(parent, dir)) {
			free(parent);
			free(dir);
			break;
		}
		free(dir);
		dir = parent;
	}
	return NULL;
}

static int write_probe(const char *path, char *err, size_t errlen)
{
	static const char body[] =
		"#include <stdio.h>\n"
		"#include <stdint.h>\n"
		"#include <stddef.h>\n"
		"#ifndef PROGMEM\n"
		"#define PROGMEM\n"
		"#endif\n"
		"#define ATM_SCORE_FMT_MINIMAL_MONO 0x0\n"
		"#define ATM_SCORE_FMT_FULL_MONO 0x2\n"
		"#define ATM_SCORE_FMT_FULL 0x3\n"
		"#include \"song.h\"\n"
		"#ifndef FX_SCORE_SYMBOL\n"
		"#define FX_SCORE_SYMBOL score\n"
		"#endif\n"
		"int main(void)\n"
		"{\n"
		"    const unsigned char *p = (const unsigned char *)&FX_SCORE_SYMBOL;\n"
		"    size_t n = sizeof(FX_SCORE_SYMBOL);\n"
		"    return fwrite(p, 1, n, stdout) == n ? 0 : 1;\n"
		"}\n";
	FILE *f = fopen(path, "wb");
	if (!f) {
		snprintf(err, errlen, "cannot write probe %s: %s", path,
			 strerror(errno));
		return -1;
	}
	if (fwrite(body, 1, sizeof(body) - 1, f) != sizeof(body) - 1) {
		snprintf(err, errlen, "cannot write probe %s", path);
		fclose(f);
		return -1;
	}
	fclose(f);
	return 0;
}

/* Compile the header probe and run it; returns the flat score bytes. */
static int extract_song(const char *song, const char *symbol,
			const char *cc, const char *workdir,
			uint8_t **out, size_t *outlen,
			char *used_symbol, size_t used_symbol_len,
			char *err, size_t errlen)
{
	static const char *default_symbols[] = { "score", "music" };
	char *songdir = NULL;
	char *src = NULL;
	char *probe = NULL;
	char *probe_bin = NULL;
	char *out_bin = NULL;
	char *log = NULL;
	char *qcc = NULL, *qsrc = NULL, *qsongdir = NULL, *qprobe = NULL;
	char *qbin = NULL, *qlog = NULL, *qout = NULL;
	int rc = -1;

	if (mkdir_p(workdir) != 0) {
		snprintf(err, errlen, "cannot create workdir %s: %s", workdir,
			 strerror(errno));
		return -1;
	}
	songdir = path_dirname(song);
	src = find_repo_src(song);
	if (!songdir || !src) {
		snprintf(err, errlen,
			 "cannot locate the repository src/ directory "
			 "(atm_cmd_constants.h) above %s", song);
		goto done;
	}
	probe = path_join(workdir, "fx_score_probe.c");
	probe_bin = path_join(workdir, "fx_score_probe");
	out_bin = path_join(workdir, "fx_score_input.bin");
	log = path_join(workdir, "fx_score_probe.log");
	if (!probe || !probe_bin || !out_bin || !log) {
		snprintf(err, errlen, "out of memory");
		goto done;
	}
	if (write_probe(probe, err, errlen) != 0) goto done;

	qcc = shquote(cc);
	qsrc = shquote(src);
	qsongdir = shquote(songdir);
	qprobe = shquote(probe);
	qbin = shquote(probe_bin);
	qlog = shquote(log);
	qout = shquote(out_bin);
	if (!qcc || !qsrc || !qsongdir || !qprobe || !qbin || !qlog || !qout) {
		snprintf(err, errlen, "out of memory");
		goto done;
	}

	for (int attempt = 0; attempt < 2; attempt++) {
		const char *sym;
		char *qsym;
		char *cmd;
		int status;

		if (symbol) {
			if (attempt > 0) break;
			sym = symbol;
		} else {
			sym = default_symbols[attempt];
		}
		qsym = shquote(sym);

		/* compile */
		{
			size_t need = strlen(qcc) + strlen(qsrc) +
				strlen(qsongdir) + strlen(qprobe) + strlen(qbin) +
				strlen(qlog) + strlen(qsym) + 128;
			cmd = malloc(need);
			if (!cmd) { free(qsym); snprintf(err, errlen, "out of memory"); goto done; }
			snprintf(cmd, need,
				 "%s -std=c11 -O0 -w -I%s -I%s "
				 "-DFX_SCORE_SYMBOL=%s %s -o %s > %s 2>&1",
				 qcc, qsrc, qsongdir, qsym, qprobe, qbin, qlog);
		}
		status = system(cmd);
		free(cmd);
		free(qsym);
		if (status == -1 || !WIFEXITED(status) ||
		    WEXITSTATUS(status) != 0)
			continue;

		/* run */
		{
			size_t need = strlen(qbin) + strlen(qout) + 8;
			cmd = malloc(need);
			if (!cmd) { snprintf(err, errlen, "out of memory"); goto done; }
			snprintf(cmd, need, "%s > %s", qbin, qout);
		}
		status = system(cmd);
		free(cmd);
		if (status == -1 || !WIFEXITED(status) ||
		    WEXITSTATUS(status) != 0) {
			snprintf(err, errlen,
				 "score probe compiled but failed to run for symbol %s",
				 sym);
			goto done;
		}
		if (read_file(out_bin, out, outlen, err, errlen) != 0) goto done;
		if (used_symbol && used_symbol_len)
			snprintf(used_symbol, used_symbol_len, "%s", sym);
		rc = 0;
		goto done;
	}

	{
		char logtail[256] = "";
		FILE *lf = fopen(log, "rb");
		if (lf) {
			char line[256];
			while (fgets(line, sizeof(line), lf))
				snprintf(logtail, sizeof(logtail), "%s", line);
			fclose(lf);
		}
		snprintf(err, errlen,
			 "cannot extract a score from %s (tried symbol%s: %s%s); "
			 "probe log tail: %s",
			 song, symbol ? "" : "s",
			 symbol ? symbol : "score, music", symbol ? "" : "",
			 logtail);
	}

done:
	free(songdir);
	free(src);
	free(probe);
	free(probe_bin);
	free(out_bin);
	free(log);
	free(qcc);
	free(qsrc);
	free(qsongdir);
	free(qprobe);
	free(qbin);
	free(qlog);
	free(qout);
	return rc;
}

static void json_escape(FILE *f, const char *s)
{
	for (const char *p = s; *p; p++) {
		if (*p == '"' || *p == '\\') fputc('\\', f);
		if ((unsigned char)*p < 0x20) {
			fprintf(f, "\\u%04x", (unsigned)(unsigned char)*p);
		} else {
			fputc(*p, f);
		}
	}
}

static int write_meta(const char *path, const char *input_path,
		      const char *symbol, const struct fx_score *score,
		      const struct fx_encode_options *opt,
		      const struct fx_encode_result *res,
		      char *err, size_t errlen)
{
	FILE *f;
	char *dir = path_dirname(path);

	if (dir) { mkdir_p(dir); free(dir); }
	f = fopen(path, "wb");
	if (!f) {
		snprintf(err, errlen, "cannot open %s for writing: %s", path,
			 strerror(errno));
		return -1;
	}

	fprintf(f, "{\n");
	fprintf(f, "  \"tool\": \"fx_pack\",\n");
	fprintf(f, "  \"contract\": \"%s\",\n",
		res->meta.has_loop
			? "loop-capable compact directly-consumed stream"
			: "finite-v1 compact directly-consumed stream");
	fprintf(f, "  \"input\": {\n");
	fprintf(f, "    \"path\": \"");
	json_escape(f, input_path ? input_path : "");
	fprintf(f, "\",\n");
	fprintf(f, "    \"symbol\": \"");
	json_escape(f, symbol && *symbol ? symbol : "-");
	fprintf(f, "\",\n");
	fprintf(f, "    \"format\": \"");
	json_escape(f, score->format_name);
	fprintf(f, "\",\n");
	fprintf(f, "    \"bytes\": %zu\n", score->source_len);
	fprintf(f, "  },\n");
	fprintf(f, "  \"options\": {\n");
	if (opt->tempo_override)
		fprintf(f, "    \"tempo\": %d,\n", opt->tempo_override);
	else
		fprintf(f, "    \"tempo\": \"authored\",\n");
	fprintf(f, "    \"tick_cap\": %u,\n", (unsigned)opt->tick_cap);
	fprintf(f, "    \"ring\": %u\n", (unsigned)opt->ring);
	fprintf(f, "  },\n");
	fprintf(f, "  \"result\": {\n");
	fprintf(f, "    \"stream_bytes\": %zu,\n", res->stream_len);
	fprintf(f, "    \"ticks\": %u,\n", (unsigned)res->meta.ticks_span);
	fprintf(f, "    \"stopped_at\": %d,\n", (int)res->meta.stopped_at);
	fprintf(f, "    \"passes\": %u,\n", (unsigned)res->meta.passes);
	fprintf(f, "    \"payload_bytes\": %u,\n",
		(unsigned)res->meta.payload_bytes);
	fprintf(f, "    \"max_group\": %u,\n", (unsigned)res->meta.max_group);
	fprintf(f, "    \"max_record\": %u,\n", (unsigned)res->meta.max_record);
	fprintf(f, "    \"framing_bytes\": %u,\n",
		(unsigned)res->meta.framing_bytes);
	fprintf(f, "    \"has_loop\": %d,\n", res->meta.has_loop);
	fprintf(f, "    \"loop_start_offset\": %d,\n",
		(int)res->meta.loop_start_offset);
	fprintf(f, "    \"intro_ticks\": %u,\n",
		(unsigned)res->meta.intro_ticks);
	fprintf(f, "    \"cycle_ticks\": %u,\n",
		(unsigned)res->meta.cycle_ticks);
	fprintf(f, "    \"intro_passes\": %u,\n",
		(unsigned)res->meta.intro_passes);
	fprintf(f, "    \"loop_passes\": %u,\n",
		(unsigned)res->meta.loop_passes);
	fprintf(f, "    \"window_bytes\": {");
	for (int k = 1; k <= FX_ENC_MAX_WINDOW; k++)
		fprintf(f, "%s\"%d\": %u", k == 1 ? "" : ", ", k,
			(unsigned)res->meta.max_window[k]);
	fprintf(f, "},\n");
	fprintf(f, "    \"window_at\": {");
	for (int k = 1; k <= FX_ENC_MAX_WINDOW; k++)
		fprintf(f, "%s\"%d\": %lld", k == 1 ? "" : ", ", k,
			(long long)res->meta.max_window_at[k]);
	fprintf(f, "}\n");
	fprintf(f, "  }\n");
	fprintf(f, "}\n");

	if (ferror(f)) {
		snprintf(err, errlen, "cannot write %s", path);
		fclose(f);
		return -1;
	}
	fclose(f);
	return 0;
}

int main(int argc, char **argv)
{
	const char *song = NULL;
	const char *symbol = NULL;
	const char *score_bin = NULL;
	const char *out_path = NULL;
	const char *meta_path = NULL;
	const char *input_bin = NULL;
	const char *workdir = DEFAULT_WORKDIR;
	const char *cc = getenv("CC");
	int format = FX_SCORE_AUTO;
	int tempo = 0;
	int loops = 0;
	long ticks = FX_ENC_DEFAULT_TICKS;
	long ring = FX_ENC_DEFAULT_RING;
	uint8_t *input = NULL;
	size_t input_len = 0;
	char used_symbol[64] = "";
	struct fx_score score;
	struct fx_encode_options opt;
	struct fx_encode_result res;
	char err[512] = "";

	if (!cc || !*cc) cc = "cc";

	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "--help") || !strcmp(argv[i], "-h")) {
			usage(stdout);
			return 0;
		} else if (!strcmp(argv[i], "--song") && i + 1 < argc) {
			song = argv[++i];
		} else if (!strcmp(argv[i], "--symbol") && i + 1 < argc) {
			symbol = argv[++i];
		} else if (!strcmp(argv[i], "--score-bin") && i + 1 < argc) {
			score_bin = argv[++i];
		} else if (!strcmp(argv[i], "--out") && i + 1 < argc) {
			out_path = argv[++i];
		} else if (!strcmp(argv[i], "--meta") && i + 1 < argc) {
			meta_path = argv[++i];
		} else if (!strcmp(argv[i], "--input-bin") && i + 1 < argc) {
			input_bin = argv[++i];
		} else if (!strcmp(argv[i], "--tempo") && i + 1 < argc) {
			tempo = atoi(argv[++i]);
		} else if (!strcmp(argv[i], "--loops")) {
			loops = 1;
		} else if (!strcmp(argv[i], "--ticks") && i + 1 < argc) {
			ticks = atol(argv[++i]);
		} else if (!strcmp(argv[i], "--ring") && i + 1 < argc) {
			ring = atol(argv[++i]);
		} else if (!strcmp(argv[i], "--format") && i + 1 < argc) {
			format = fx_score_format_from_name(argv[++i]);
			if (format < 0) {
				fprintf(stderr, "fx_pack: unknown --format %s\n",
					argv[i]);
				return 2;
			}
		} else if (!strcmp(argv[i], "--workdir") && i + 1 < argc) {
			workdir = argv[++i];
		} else if (!strcmp(argv[i], "--cc") && i + 1 < argc) {
			cc = argv[++i];
		} else {
			fprintf(stderr, "fx_pack: unknown argument %s\n", argv[i]);
			return 2;
		}
	}

	if (!out_path) { usage(stderr); return 2; }
	if (song && score_bin) {
		fprintf(stderr, "fx_pack: --song and --score-bin are exclusive\n");
		return 2;
	}
	if (!song && !score_bin) { usage(stderr); return 2; }
	if (tempo < 0 || tempo > 255) {
		fprintf(stderr, "fx_pack: --tempo must be in [0, 255]\n");
		return 2;
	}
	if (ticks <= 0 || ticks > 16777215) {
		fprintf(stderr, "fx_pack: --ticks must be in [1, 16777215]\n");
		return 2;
	}	if (ring < 5 || ring > 256) {
		fprintf(stderr, "fx_pack: --ring must be in [5, 256]\n");
		return 2;
	}

	memset(&score, 0, sizeof(score));
	memset(&res, 0, sizeof(res));
	opt.ring = (uint16_t)ring;
	opt.tick_cap = (uint32_t)ticks;
	opt.tempo_override = tempo;
	opt.allow_loops = loops;

	if (song) {
		if (extract_song(song, symbol, cc, workdir, &input, &input_len,
				 used_symbol, sizeof(used_symbol),
				 err, sizeof(err)) != 0) {
			fprintf(stderr, "fx_pack: %s\n", err);
			return 2;
		}
		if (!symbol) symbol = used_symbol;
	} else {
		if (read_file(score_bin, &input, &input_len, err, sizeof(err)) != 0) {
			fprintf(stderr, "fx_pack: %s\n", err);
			return 2;
		}
	}

	if (input_bin && write_file(input_bin, input, input_len,
				    err, sizeof(err)) != 0) {
		fprintf(stderr, "fx_pack: %s\n", err);
		free(input);
		return 2;
	}

	if (fx_score_parse(input, input_len, (enum fx_score_format)format,
			   &score, err, sizeof(err)) != 0) {
		fprintf(stderr, "fx_pack: admission: %s\n", err);
		free(input);
		fx_score_free(&score);
		return 2;
	}

	{
		struct fx_score_patterns view = fx_score_view(&score);
		if (fx_encode(&view, &opt, &res) != 0) {
			fprintf(stderr, "fx_pack: admission: %s\n", res.error);
			free(input);
			fx_score_free(&score);
			fx_encode_result_free(&res);
			return 2;
		}
	}

	if (write_file(out_path, res.stream, res.stream_len,
		       err, sizeof(err)) != 0) {
		fprintf(stderr, "fx_pack: %s\n", err);
		free(input);
		fx_score_free(&score);
		fx_encode_result_free(&res);
		return 2;
	}
	if (meta_path && write_meta(meta_path, song ? song : score_bin,
				    symbol, &score, &opt, &res,
				    err, sizeof(err)) != 0) {
		fprintf(stderr, "fx_pack: %s\n", err);
		free(input);
		fx_score_free(&score);
		fx_encode_result_free(&res);
		return 2;
	}

	fprintf(stderr,
		"fx_pack: input=%s format=%s ticks=%u stopped_at=%d "
		"stream_bytes=%zu passes=%u payload_bytes=%u max_group=%u "
		"max_record=%u framing_bytes=%u tempo=%s rings=%u loop=%s "
		"-> %s\n",
		song ? song : score_bin, score.format_name,
		(unsigned)res.meta.ticks_span, (int)res.meta.stopped_at,
		res.stream_len, (unsigned)res.meta.passes,
		(unsigned)res.meta.payload_bytes,
		(unsigned)res.meta.max_group, (unsigned)res.meta.max_record,
		(unsigned)res.meta.framing_bytes,
		tempo ? "override" : "authored", (unsigned)opt.ring,
		res.meta.has_loop ? "yes" : "no", out_path);

	printf("window_bytes");
	for (int k = 1; k <= FX_ENC_MAX_WINDOW; k++)
		printf(",%d:%u@%lld", k, (unsigned)res.meta.max_window[k],
		       (long long)res.meta.max_window_at[k]);
	printf("\n");

	free(input);
	fx_score_free(&score);
	fx_encode_result_free(&res);
	return 0;
}
