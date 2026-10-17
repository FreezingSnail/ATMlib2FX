/*
 * compact_format_test.c - host tests for the compact FX stream decoder
 * (ATMlib2FX-hlh.5): gap boundaries, malformed/nonprogressing/oversize
 * rejection, and underflow freeze. Permanent host test, co-located with the
 * trace harness; contributes no AVR bytes.
 *
 * It compiles the device decoder (src/atm_synth.c with ATM_HAS_FX_COMPACT=1)
 * and drives the registered tick callback directly, so tick advance is
 * deterministic and independent of the base-timer shim.
 *
 * Usage: compact_format_test
 * Exit 0 = all assertions pass.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#define ATM_HAS_FX_COMPACT (1)
#define ATM_FX_COMPACT_DIAG (1)
#include "atm_synth.c"

/* ---------------- osc.c timer-layer substitution ---------------- */
struct host_cb {
	uint8_t preset;
	uint8_t counter;
	osc_tick_callback cb;
	void *priv;
};
struct osc_params osc_params_array[OSC_CH_COUNT];
static struct host_cb host_cb[OSC_TICK_CALLBACK_COUNT];

void osc_setup(void)
{
	uint8_t i;
	memset(osc_params_array, 0, sizeof(osc_params_array));
	memset(host_cb, 0, sizeof(host_cb));
	for (i = 0; i < OSC_CH_COUNT; i++) osc_params_array[i].mod = 0x7F;
	osc_params_array[OSC_CH_THREE].phase_increment = 0x0001;
}
void osc_set_tick_rate(const uint8_t i, const uint16_t r)
{
	host_cb[i].preset = (uint8_t)((OSC_SAMPLERATE / OSC_ISR_PRESCALER_DIV) / r - 1);
}
void osc_set_tick_callback(const uint8_t i, const osc_tick_callback cb, const void *priv)
{
	host_cb[i].cb = cb;
	host_cb[i].priv = (void *)priv;
	if (cb) host_cb[i].counter = 0;
}
void osc_get_tick_callback(const uint8_t i, osc_tick_callback *cb, void **priv)
{
	if (cb) *cb = host_cb[i].cb;
	if (priv) *priv = host_cb[i].priv;
}

/* ---------------- FX byte source ---------------- */
static uint8_t g_buf[512];
static size_t g_buflen;

void atm_fx_compact_fetch(uint32_t offset, uint8_t *dst, uint8_t n)
{
	for (uint8_t i = 0; i < n; i++) {
		uint32_t o = offset + i;
		dst[i] = o < g_buflen ? g_buf[o] : 0;
	}
}

/* ---------------- stream builder (mirrors the converter) ---------------- */
static void putb(uint8_t b) { g_buf[g_buflen++] = b; }
static uint8_t gap_nbytes(uint16_t g)
{
	if (g <= 0x7F) return 1;
	if (g <= 0x7EFF) return 2;
	return 3;
}
static void put_gap(uint16_t g)
{
	if (g <= 0x7F) {
		putb((uint8_t)g);
	} else if (g <= 0x7EFF) {
		putb((uint8_t)(0x80 | (g >> 8)));
		putb((uint8_t)(g & 0xFF));
	} else {
		putb(0xFF);
		putb((uint8_t)((g >> 8) & 0xFF));
		putb((uint8_t)(g & 0xFF));
	}
}
/* one well-formed pass record for channel 0 with `n` command bytes */
static void emit_pass_ch0(uint16_t gap, const uint8_t *cmds, uint8_t n)
{
	putb((uint8_t)(1 + gap_nbytes(gap) + 1 + 1 + n)); /* len */
	put_gap(gap);
	putb(0x01);                                        /* bitmap */
	putb(n);                                           /* group len */
	for (uint8_t i = 0; i < n; i++) putb(cmds[i]);
}

/* ---------------- harness ---------------- */
static int g_fail;

static void begin_test(void)
{
	g_buflen = 0;
	putb(0xC0); /* magic */
	memset(&atm_fx_compact_state, 0, sizeof(atm_fx_compact_state));
	osc_setup();
	atm_synth_setup();
}

/* Drive the registered handler; return the 1-based call index at which
 * channels[0].note first equals `target`, or -1. Services each tick. */
static int drive_until_note(uint8_t target, int max_calls)
{
	for (int i = 1; i <= max_calls; i++) {
		atm_fx_compact_service();
		if (host_cb[0].cb == NULL) return -1;
		host_cb[0].cb(0, host_cb[0].priv);
		if (channels[0].note == target) return i;
	}
	return -1;
}

static void check(const char *what, int cond)
{
	if (!cond) { fprintf(stderr, "FAIL: %s\n", what); g_fail = 1; }
	else { printf("ok: %s\n", what); }
}

static void test_gap_advance(uint16_t g)
{
	static const uint8_t n12[1] = { 12 };
	static const uint8_t n13[1] = { 13 };
	begin_test();
	emit_pass_ch0(g, n12, 1);   /* rec1: gap g -> next pass g+1 calls later */
	emit_pass_ch0(0, n13, 1);   /* rec2: note 13                            */
	putb(0x00);                 /* END */

	atm_fx_compact_play(0, (uint32_t)g_buflen);
	int a = -1, b = -1;
	for (int i = 1; i <= (int)g + 4; i++) {
		atm_fx_compact_service();
		if (host_cb[0].cb == NULL) break;
		host_cb[0].cb(0, host_cb[0].priv);
		if (a < 0 && channels[0].note == 12) {
			a = i;
		} else if (a >= 0 && channels[0].note == 13) {
			b = i;
			break;
		}
	}
	char msg[72];
	snprintf(msg, sizeof(msg),
		"gap %u: note12 at call %d, note13 at call %d, delta %d == %u",
		(unsigned)g, a, b, b - a, (unsigned)g + 1);
	check(msg, a == 1 && b > 0 && (b - a) == (int)g + 1);
}

static void test_reject_oversize(void)
{
	begin_test();
	putb((uint8_t)(ATM_FX_COMPACT_RING + 1)); /* declared len > ring */
	for (int i = 0; i < ATM_FX_COMPACT_RING + 1; i++) putb(0x00);
	putb(0x00);
	atm_fx_compact_play(0, (uint32_t)g_buflen);
	drive_until_note(0xFF, 1);
	check("oversize record rejected (error=2, stopped)",
		atm_fx_compact_state.error == 2 && atm_fx_compact_state.active == 0);
}

static void test_reject_nonprogress(void)
{
	begin_test();
	putb(5);      /* len */
	put_gap(0);   /* gap */
	putb(0x00);   /* bitmap = 0 -> nonprogressing */
	putb(0x00);   /* pad to declared len (5): len,gap,bitmap + 2 pad */
	putb(0x00);
	putb(0x00);
	atm_fx_compact_play(0, (uint32_t)g_buflen);
	drive_until_note(0xFF, 1);
	check("zero-channel pass rejected (error=1, stopped)",
		atm_fx_compact_state.error == 1 && atm_fx_compact_state.active == 0);
}

static void test_reject_malformed(void)
{
	begin_test();
	/* len=6: gap=0, bitmap=0x01, glen=3, but only two trailing bytes fit */
	putb(6);
	put_gap(0);
	putb(0x01);
	putb(3);
	putb(12);
	putb(12);
	putb(0x00);
	atm_fx_compact_play(0, (uint32_t)g_buflen);
	channels[0].note = 0x2A; /* sentinel: must not change */
	drive_until_note(0xFF, 1);
	check("malformed group length rejected (error=1, stopped)",
		atm_fx_compact_state.error == 1 && atm_fx_compact_state.active == 0);
	check("malformed record did not mutate channel state",
		channels[0].note == 0x2A);
}

static void test_underflow_freeze(void)
{
	begin_test();
	/* Declared len 24; only 10 bytes exist in the byte source, so the record
	 * can never be fully resident. The tick must freeze without mutation. */
	putb(24);
	put_gap(0);
	putb(0x01);
	putb(20);
	for (int i = 0; i < 6; i++) putb(12);
	/* g_buflen is 11 now: the decoder reads from offset 1, so 10 bytes */
	atm_fx_compact_play(0, (uint32_t)g_buflen);
	channels[0].note = 0x2A; /* sentinel: must not change on a frozen tick */
	for (int i = 1; i <= 3; i++) {
		atm_fx_compact_service();
		host_cb[0].cb(0, host_cb[0].priv);
	}
	check("underflow counted (underruns>=1)",
		atm_fx_compact_state.underruns >= 1);
	check("underflow froze the tick without mutation",
		channels[0].note == 0x2A);
}

int main(void)
{
	/* Delay/gap boundaries from the bead: source delay 1/32/33/255/256/257/
	 * 65535 map to gap = delay-1. Cover the gap-codec boundaries too. */
	static const uint16_t gaps[] = { 0, 1, 31, 32, 33, 127, 128, 254, 255,
		256, 257, 0x7EFE, 0x7EFF, 0x7F00, 65534, 65535 };
	for (size_t i = 0; i < sizeof(gaps) / sizeof(gaps[0]); i++)
		test_gap_advance(gaps[i]);

	test_reject_oversize();
	test_reject_nonprogress();
	test_reject_malformed();
	test_underflow_freeze();

	if (g_fail) {
		fprintf(stderr, "compact_format_test: FAILED\n");
		return 1;
	}
	printf("compact_format_test: all checks passed\n");
	return 0;
}
