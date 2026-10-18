/*
 * score_dump.c - dump the packed PROGMEM score (and optional SFX) of a
 * generated ATMlib2 song header to stdout, for tools/atm-shrink/atm_shrink.c.
 *
 * Compile-time selected header so the same tool serves both layouts:
 *   cc -Isrc -I<dir> [-DHAVE_SFX1=1] \
 *      -DATM_SHRINK_SCORE_HEADER='"song.h"' score_dump.c -o score_dump
 *   cc -Isrc -I<dir> -Iresearch/fx/footprint_baseline/trace/avr_shim \
 *      -DATM_SHRINK_SCORE_HEADER='"score.h"' score_dump.c -o score_dump
 *
 * argv[1] chooses "score" (default) or "sfx" (requires HAVE_SFX1).
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stddef.h>

#ifndef PROGMEM
#define PROGMEM
#endif
#ifndef ATM_SCORE_FMT_FULL
#define ATM_SCORE_FMT_FULL (0x3)
#endif
#ifndef ATM_SCORE_FMT_MINIMAL_MONO
#define ATM_SCORE_FMT_MINIMAL_MONO (0x0)
#endif
#ifndef ATM_SHRINK_SCORE_HEADER
#define ATM_SHRINK_SCORE_HEADER "song.h"
#endif
#ifndef ATM_SHRINK_SCORE_SYMBOL
#define ATM_SHRINK_SCORE_SYMBOL score
#endif

#include ATM_SHRINK_SCORE_HEADER

int main(int argc, char **argv)
{
	const char *which = (argc > 1) ? argv[1] : "score";

	if (!strcmp(which, "sfx")) {
#ifdef HAVE_SFX1
		const uint8_t *p = (const uint8_t *)&sfx1;
		size_t n = sizeof(sfx1);
		fwrite(p, 1, n, stdout);
		return 0;
#else
		fprintf(stderr, "score_dump: header has no sfx1 symbol\n");
		return 2;
#endif
	}

	const uint8_t *p = (const uint8_t *)&ATM_SHRINK_SCORE_SYMBOL;
	size_t n = sizeof(ATM_SHRINK_SCORE_SYMBOL);
	fwrite(p, 1, n, stdout);
	return 0;
}
