/*
 * control_test.c - host tests for compact-backend control semantics
 * (ATMlib2FX-hlh.9): prefill-before-arm, pause/resume position and live-state
 * preservation with defined mute/restore, atomic replacement (no mixed track
 * state), stop-mute, and the independent-tempo SFX borrow/restore.
 *
 * It compiles the device decoder (src/atm_synth.c with ATM_HAS_FX_COMPACT=1,
 * ATM_FX_COMPACT_DIAG=1, ATM_FX_COMPACT_SFX=1) and drives the registered tick
 * callbacks through the same base-timer down-counter model the other trace
 * harnesses use, so timing is deterministic. Permanent host test, co-located
 * with the control harnesses; contributes no AVR bytes.
 *
 * Usage: control_test
 * Exit 0 = all assertions pass.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#define ATM_HAS_FX_COMPACT (1)
#define ATM_FX_COMPACT_DIAG (1)
#define ATM_FX_COMPACT_SFX (1)
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
static uint8_t g_buf[1024];
static size_t g_buflen;

void atm_fx_compact_fetch(uint32_t offset, uint8_t *dst, uint8_t n)
{
	for (uint8_t i = 0; i < n; i++) {
		uint32_t o = offset + i;
		dst[i] = o < g_buflen ? g_buf[o] : 0;
	}
}

/* ---------------- stream builder ---------------- */
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
/* one well-formed pass record for `ch` with `n` command bytes */
static void emit_pass(uint8_t ch, uint16_t gap, const uint8_t *cmds, uint8_t n)
{
	putb((uint8_t)(1 + gap_nbytes(gap) + 1 + 1 + n)); /* len */
	put_gap(gap);
	putb((uint8_t)(1u << ch));                         /* bitmap */
	putb(n);                                           /* group len */
	for (uint8_t i = 0; i < n; i++) putb(cmds[i]);
}

/* ---------------- base-timer driver ---------------- */
static uint64_t g_base;
static uint32_t g_music_calls;

static void host_tick_handler(void)
{
	for (uint8_t n = 0; n < OSC_TICK_CALLBACK_COUNT; n++) {
		if (host_cb[n].counter != 255) {
			if (!host_cb[n].cb) host_cb[n].counter = 255;
			continue;
		}
		if (host_cb[n].cb) {
			host_cb[n].cb(n, host_cb[n].priv);
			if (n == 0) g_music_calls++;
		}
		host_cb[n].counter = host_cb[n].preset;
	}
}

/* One base event; optionally service the foreground refill first. */
static void base_event(int service)
{
	int due = 0;
	if (service) atm_fx_compact_service();
	for (uint8_t n = 0; n < OSC_TICK_CALLBACK_COUNT; n++) {
		host_cb[n].counter--;
		if (host_cb[n].counter == 0xFF) due = 1;
	}
	if (due) host_tick_handler();
	g_base++;
}

static void run_base(int n, int service)
{
	for (int i = 0; i < n; i++) base_event(service);
}

/* ---------------- harness ---------------- */
static int g_fail;

static void check(const char *what, int cond)
{
	if (!cond) { fprintf(stderr, "FAIL: %s\n", what); g_fail = 1; }
	else { printf("ok: %s\n", what); }
}

static void begin_test(void)
{
	g_buflen = 0;
	putb(0xC0); /* magic */
	g_base = 0;
	g_music_calls = 0;
	memset(&atm_fx_compact_state, 0, sizeof(atm_fx_compact_state));
	osc_setup();
	atm_synth_setup();
}

/* ---------------- tests ---------------- */

/* Prefill: play() must leave at least one complete record resident before the
 * first due tick, so the first tick cannot underrun. */
static void test_prefill_before_arm(void)
{
	static const uint8_t c12[1] = { 12 };
	begin_test();
	emit_pass(0, 0, c12, 1);
	putb(0x00); /* END */
	atm_fx_compact_play(0, (uint32_t)g_buflen);

	check("play prefills the ring before arming",
		(uint8_t)(atm_fx_compact_state.tail - atm_fx_compact_state.head) > 0 &&
		atm_fx_compact_state.head == 0);
	check("play armed the music callback", host_cb[0].cb != NULL);

	run_base(1, 1);
	check("first due tick applied the first record (no underrun)",
		channels[0].note == 12 && atm_fx_compact_state.underruns == 0);
}

/* Pause preserves ring position and live state, mutes, and resume restores the
 * saved voice and continues from the same position with no drift. */
static void test_pause_resume(void)
{
	static const uint8_t c1[3] = { ATM_CMD_1P_SET_VOLUME, 100, 12 }; /* vol=100, note 12 */
	static const uint8_t c2[1] = { 13 };
	uint16_t head0, tail0, gap0;
	struct atm_channel_state ch0;
	uint16_t inc0;
	uint32_t control_calls;

	/* Control run: no pause. Calls until note 13. */
	begin_test();
	emit_pass(0, 5, c1, 3);
	emit_pass(0, 0, c2, 1);
	putb(0x00);
	atm_fx_compact_play(0, (uint32_t)g_buflen);
	for (int i = 0; i < 200000 && channels[0].note != 13; i++) base_event(1);
	control_calls = g_music_calls;

	/* Paused run. */
	begin_test();
	emit_pass(0, 5, c1, 3);
	emit_pass(0, 0, c2, 1);
	putb(0x00);
	atm_fx_compact_play(0, (uint32_t)g_buflen);

	while (g_music_calls < 3) base_event(1);
	head0 = atm_fx_compact_state.head;
	tail0 = atm_fx_compact_state.tail;
	gap0 = atm_fx_compact_state.gap;
	inc0 = osc_params_array[0].phase_increment;
	ch0 = channels[0];

	atm_fx_compact_pause();
	check("pause reported", atm_fx_compact_is_paused() == 1);
	check("pause unregistered the callback", host_cb[0].cb == NULL);
	check("pause muted the owned voice", osc_params_array[0].vol == 0);

	{
		uint32_t calls_at_pause = g_music_calls;
		run_base(4000, 1); /* ~50 music ticks worth of base events */
		check("paused: no tick advanced", g_music_calls == calls_at_pause);
		check("paused: position preserved",
			atm_fx_compact_state.head == head0 &&
			atm_fx_compact_state.tail == tail0 &&
			atm_fx_compact_state.gap == gap0);
		check("paused: live channel state preserved",
			memcmp(&channels[0], &ch0, sizeof(ch0)) == 0);
		check("paused: oscillator pitch preserved (only vol muted)",
			osc_params_array[0].phase_increment == inc0);
	}

	atm_fx_compact_resume();
	check("resume reported", atm_fx_compact_is_paused() == 0);
	check("resume re-armed the callback", host_cb[0].cb != NULL);
	check("resume restored the saved volume", osc_params_array[0].vol == 100);
	check("resume kept the position",
		atm_fx_compact_state.head == head0 &&
		atm_fx_compact_state.tail == tail0 &&
		atm_fx_compact_state.gap == gap0);

	for (int i = 0; i < 200000 && channels[0].note != 13; i++) base_event(1);
	check("resume continued to the next note", channels[0].note == 13);
	check("pause/resume caused no tick drift", g_music_calls == control_calls);
}

/* Replacement is atomic: the new track's state is fully in place when play()
 * returns and no unread/partial data of the previous track survives. */
static void test_replacement_atomic(void)
{
	static const uint8_t a12[1] = { 12 };
	static const uint8_t a13[1] = { 13 };
	static const uint8_t b55[1] = { 55 };

	begin_test();
	emit_pass(0, 10, a12, 1);
	emit_pass(0, 0, a13, 1);
	putb(0x00);
	atm_fx_compact_play(0, (uint32_t)g_buflen);
	run_base(3, 1);
	check("track A sounding before replacement", channels[0].note == 12);

	/* Build B as a full stream (magic + record + END) in a separate region. */
	putb(0xC0);
	uint8_t bstart = (uint8_t)(g_buflen - 1);
	emit_pass(0, 0, b55, 1);
	putb(0x00);
	uint8_t blen = (uint8_t)(g_buflen - bstart);

	atm_fx_compact_play(bstart, blen);

	check("replacement re-initialized the channel",
		channels[0].note == 0 && channels[0].vol == 0 &&
		channels[0].dst_osc_params == &osc_params_array[0]);
	check("replacement reset the ring indices",
		atm_fx_compact_state.head == 0);
	check("replacement invalidated unread data (ring holds only B)",
		(uint8_t)(atm_fx_compact_state.tail - atm_fx_compact_state.head) ==
			(uint8_t)(blen - 1));
	check("replacement cleared the active mask",
		atmlib_state.channel_active_mute == 0b11110000 &&
		atm_fx_compact_state.active == 1);

	run_base(1, 1);
	check("replacement applied only the new track's first record",
		channels[0].note == 55);
	check("replacement left no mixed-track residue (no A note 12/13)",
		channels[0].note == 55);
}

/* Replacement while paused must clear pause and start cleanly. */
static void test_replacement_while_paused(void)
{
	static const uint8_t a12[1] = { 12 };
	static const uint8_t b55[1] = { 55 };
	begin_test();
	emit_pass(0, 10, a12, 1);
	putb(0x00);
	atm_fx_compact_play(0, (uint32_t)g_buflen);
	run_base(2, 1);
	atm_fx_compact_pause();
	check("paused before replacement", atm_fx_compact_is_paused() == 1);

	uint8_t bstart;
	putb(0xC0);
	bstart = (uint8_t)(g_buflen - 1);
	emit_pass(0, 0, b55, 1);
	putb(0x00);
	atm_fx_compact_play(bstart, (uint8_t)(g_buflen - bstart));
	check("replacement cleared the pause", atm_fx_compact_is_paused() == 0);

	run_base(1, 1);
	check("replacement-while-paused played the new track", channels[0].note == 55);
}

/* Stop mutes the owned voices and unregisters. */
static void test_stop_mutes(void)
{
	static const uint8_t c1[3] = { ATM_CMD_1P_SET_VOLUME, 120, 12 };
	begin_test();
	emit_pass(0, 50, c1, 3);
	putb(0x00);
	atm_fx_compact_play(0, (uint32_t)g_buflen);
	run_base(2, 1);
	check("voice audible before stop", osc_params_array[0].vol == 120);
	atm_fx_compact_stop();
	check("stop unregistered the callback", host_cb[0].cb == NULL);
	check("stop cleared active", atm_fx_compact_is_active() == 0);
	check("stop muted the owned voices", osc_params_array[0].vol == 0);
}

/* SFX overlay: borrow channel 2 at independent tempo, music advances behind it,
 * stop restores the borrowed voice. */
static const uint8_t kSfx[21] = {
	0xc0, 0x09, 0x0a, 0x04, 0x05, 0x72, 0x16, 0x74, 0x7f, 0x2a,
	0x05, 0x0a, 0x04, 0x01, 0x00, 0x05, 0x00, 0x04, 0x01, 0x61, 0x00
};

static void test_sfx_borrow_restore(void)
{
	static const uint8_t m40[1] = { 40 };
	struct osc_params before;
	uint32_t music_at_start;
	uint16_t inc_expected = note_index_2_phase_inc(40);

	begin_test();
	emit_pass(2, 40, m40, 1);
	putb(0x00);
	atm_fx_compact_play(0, (uint32_t)g_buflen);
	while (g_music_calls < 1) base_event(1);
	check("music channel 2 sounding", osc_params_array[2].phase_increment == inc_expected);
	before = osc_params_array[2];

	atm_fx_compact_play_sfx(2, kSfx, sizeof(kSfx));
	check("sfx active", atm_fx_compact_is_sfx_active() == 1);
	check("sfx borrowed the channel (rerouted music effects)",
		channels[2].dst_osc_params == &atm_fx_compact_state.sfx_save);
	check("sfx silenced the borrowed voice", osc_params_array[2].vol == 0 &&
		osc_params_array[2].phase_increment == 0);
	check("sfx started on the borrowed channel",
		atm_fx_compact_state.sfx_borrow == 2);

	music_at_start = g_music_calls;

	/* Run the SFX to completion; music must keep advancing behind it. */
	for (int i = 0; i < 200000 && atm_fx_compact_is_sfx_active(); i++) {
		base_event(1);
	}

	check("sfx ran to its natural stop", atm_fx_compact_is_sfx_active() == 0);
	check("sfx tick count matches the reference (23)", atm_fx_compact_state.sfx_ticks == 23);
	check("music advanced behind the borrowed channel", g_music_calls > music_at_start);
	check("sfx stop restored the borrowed voice",
		osc_params_array[2].phase_increment == before.phase_increment &&
		osc_params_array[2].mod == before.mod);
	check("sfx restore released the channel reroute",
		channels[2].dst_osc_params == &osc_params_array[2] &&
		atm_fx_compact_state.sfx_restore_ok == 1);
}

/* Replacing an active SFX restores its borrow before installing the new one. */
static void test_sfx_replacement(void)
{
	static const uint8_t m40[1] = { 40 };
	begin_test();
	emit_pass(2, 60, m40, 1);
	putb(0x00);
	atm_fx_compact_play(0, (uint32_t)g_buflen);
	while (g_music_calls < 1) base_event(1);

	atm_fx_compact_play_sfx(2, kSfx, sizeof(kSfx));
	run_base(300, 1);
	check("sfx active before replacement", atm_fx_compact_is_sfx_active() == 1);

	atm_fx_compact_play_sfx(2, kSfx, sizeof(kSfx));
	check("sfx replacement leaves exactly one active overlay",
		atm_fx_compact_is_sfx_active() == 1 &&
		channels[2].dst_osc_params == &atm_fx_compact_state.sfx_save &&
		atm_fx_compact_state.sfx_ticks == 0);
}

int main(void)
{
	test_prefill_before_arm();
	test_pause_resume();
	test_replacement_atomic();
	test_replacement_while_paused();
	test_stop_mutes();
	test_sfx_borrow_restore();
	test_sfx_replacement();

	if (g_fail) {
		fprintf(stderr, "control_test: FAILED\n");
		return 1;
	}
	printf("control_test: all checks passed\n");
	return 0;
}
