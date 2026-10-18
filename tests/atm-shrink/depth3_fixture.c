/*
 * depth3_fixture.c - ATMlib2FX-hlh.3 CLI depth-gate fixtures.
 *
 * Emits one packed score blob to stdout whose input semantics reach the
 * library's CALL-skip boundary (ATM_PATTERN_STACK_DEPTH = 3; src/cmd_parse.c
 * skips CALL at pstack_index >= ATM_PATTERN_STACK_DEPTH-1):
 *
 *   (default) channel: depth-3 single-use CALL chain rooted at the channel
 *     entry pattern.
 *       fmt 0x03, 4 patterns, 1 channel starting at pattern 0
 *       p0: CALL 1; END      p1: CALL 2; END
 *       p2: CALL 3; END      p3: 0x74 0x10; END   (leaf, L=3)
 *
 *   looproot: depth-3 CALL chain rooted only at a SET_LOOP_PATTERN target
 *     (the second-round review repro). The library restarts a loop target at
 *     pstack_index 0 (src/atm_synth.c start_loop), so the chain is at the
 *     limit exactly like the channel-entry case.
 *       fmt 0x03, 5 patterns, 4 channels starting at pattern 0
 *       p0: LOOP 1; 0x74 0x10; END
 *       p1: CALL 2; 0x40; END   p2: CALL 3; 0x40; END
 *       p3: CALL 4; 0x40; END   p4: 0x74 0x20; END
 *
 *   looproot2: one-hop-shorter control (depth 2, must stay accepted):
 *       fmt 0x03, 4 patterns, 4 channels starting at pattern 0
 *       p0: LOOP 1; 0x74 0x10; END
 *       p1: CALL 2; 0x40; END   p2: CALL 3; 0x40; END
 *       p3: 0x74 0x20; END
 *
 * The inline pass could flatten either depth-3 input to depth 0, but the
 * library skips the deepest CALL, so the input already plays differently from
 * any flattened rewrite. atm_shrink must reject both depth-3 fixtures with
 * exit 4 under default flags *and* --no-inline --no-share;
 * tests/atm-shrink/run-tests.sh asserts that and byte-checks the looproot2
 * control output.
 */
#include <stdio.h>
#include <stdint.h>
#include <string.h>

static const uint8_t blob_channel[] = {
	0x03, 0x04,          /* fmt, num_patterns        */
	0x0c, 0x00,          /* patterns_offset[0] = 12  */
	0x0f, 0x00,          /* patterns_offset[1] = 15  */
	0x12, 0x00,          /* patterns_offset[2] = 18  */
	0x15, 0x00,          /* patterns_offset[3] = 21  */
	0x01,                /* num_channels             */
	0x00,                /* start_patterns[0] = 0    */
	0x82, 0x01, 0x61,    /* p0: CALL 1; END          */
	0x82, 0x02, 0x61,    /* p1: CALL 2; END          */
	0x82, 0x03, 0x61,    /* p2: CALL 3; END          */
	0x74, 0x10, 0x61     /* p3: 1P command; END      */
};

static const uint8_t blob_looproot[] = {
	0x03, 0x05,          /* fmt, num_patterns        */
	0x11, 0x00,          /* patterns_offset[0] = 17  */
	0x16, 0x00,          /* patterns_offset[1] = 22  */
	0x1a, 0x00,          /* patterns_offset[2] = 26  */
	0x1e, 0x00,          /* patterns_offset[3] = 30  */
	0x22, 0x00,          /* patterns_offset[4] = 34  */
	0x04,                /* num_channels             */
	0x00, 0x00, 0x00, 0x00, /* start_patterns[0..3]   */
	0x80, 0x01, 0x74, 0x10, 0x61, /* p0: LOOP 1; 74 10; END */
	0x82, 0x02, 0x40, 0x61, /* p1: CALL 2; 0x40; END  */
	0x82, 0x03, 0x40, 0x61, /* p2: CALL 3; 0x40; END  */
	0x82, 0x04, 0x40, 0x61, /* p3: CALL 4; 0x40; END  */
	0x74, 0x20, 0x61     /* p4: 74 20; END           */
};

static const uint8_t blob_looproot2[] = {
	0x03, 0x04,          /* fmt, num_patterns        */
	0x0f, 0x00,          /* patterns_offset[0] = 15  */
	0x14, 0x00,          /* patterns_offset[1] = 20  */
	0x18, 0x00,          /* patterns_offset[2] = 24  */
	0x1c, 0x00,          /* patterns_offset[3] = 28  */
	0x04,                /* num_channels             */
	0x00, 0x00, 0x00, 0x00, /* start_patterns[0..3]   */
	0x80, 0x01, 0x74, 0x10, 0x61, /* p0: LOOP 1; 74 10; END */
	0x82, 0x02, 0x40, 0x61, /* p1: CALL 2; 0x40; END  */
	0x82, 0x03, 0x40, 0x61, /* p2: CALL 3; 0x40; END  */
	0x74, 0x20, 0x61     /* p3: 74 20; END           */
};

int main(int argc, char **argv)
{
	const uint8_t *blob = blob_channel;
	size_t len = sizeof(blob_channel);

	if (argc > 1 && !strcmp(argv[1], "looproot")) {
		blob = blob_looproot;
		len = sizeof(blob_looproot);
	} else if (argc > 1 && !strcmp(argv[1], "looproot2")) {
		blob = blob_looproot2;
		len = sizeof(blob_looproot2);
	} else if (argc > 1 && strcmp(argv[1], "channel")) {
		fprintf(stderr, "usage: depth3_fixture [channel|looproot|looproot2]\n");
		return 2;
	}

	if (fwrite(blob, 1, len, stdout) != len)
		return 1;
	return 0;
}
