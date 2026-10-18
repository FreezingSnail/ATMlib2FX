/*
 * atm_fx_compact.c - compact directly-consumed FX music stream
 * (ATMlib2FX-hlh.5) with pause/replacement semantics and an independent-tempo
 * SFX overlay (ATMlib2FX-hlh.9).
 *
 * This file is #included by src/atm_synth.c (after the static effect/command
 * helpers and after src/cmd_parse.c) when ATM_HAS_FX_COMPACT == 1, so it can
 * reuse process_fx(), apply_cmd() and the shared channel/oscillator arrays.
 * The whole body is guarded so a standalone compile (arduino-cli compiles every
 * .c in src/) produces nothing, exactly like src/cmd_parse.c.
 *
 * Record framing (provisional; research/fx/fx_compact_spike/):
 *   0xC0 magic, then  <len> <gap> <bitmap> <per-channel len+cmds>  ... 0x00 END
 * See src/atm_fx_compact.h and research/fx/fx_compact_spike/README.md.
 */
#ifdef ATM_FX_COMPACT_IMPL

#define ATM_FX_COMPACT_MASK (ATM_FX_COMPACT_RING - 1)

/* Replacement/pause critical sections. The timer consumer and the foreground
 * control API share the ring descriptor; the control API runs its mutation
 * between complete ticks. On AVR use an interrupt-restoring atomic block; on a
 * host build (the trace harnesses) the single-threaded shim needs nothing. */
#if defined(__AVR__)
#include <util/atomic.h>
#define ATM_FX_COMPACT_ATOMIC ATOMIC_BLOCK(ATOMIC_RESTORESTATE)
#else
#define ATM_FX_COMPACT_ATOMIC if (1)
#endif

struct atm_fx_compact_state atm_fx_compact_state;

/* Byte length of one command, matching the original encoding. */
static uint8_t atm_fx_compact_cmd_bytes(const uint8_t id)
{
	if (id < ATM_CMD_BLK_DELAY)       return 1;
	if (id < ATM_CMD_BLK_IMMEDIATE)   return 1;
	if (id < ATM_CMD_BLK_1_PARAMETER) return 1;
	if (id < ATM_CMD_BLK_N_PARAMETER) return 2;
	return (uint8_t)(1 + (((id >> 4) & 0x07) + 1));
}

static void atm_fx_compact_channels_init(void)
{
	for (uint8_t n = 0; n < OSC_CH_COUNT; n++) {
		struct atm_channel_state *ch = &channels[n];
		memset(ch, 0, sizeof(*ch));
#if ATM_HAS_FX_NOTE_RETRIG
		ch->arpCount = 0x80;
#endif
		ch->mod = 0x7F;
		ch->dst_osc_params = &osc_params_array[n];
	}
}

/* Read one byte from the pinned record, offset from the consumer head. */
static inline __attribute__((always_inline)) uint8_t
atm_fx_compact_read(const uint8_t off)
{
	return atm_fx_compact_state.buf[
		(uint8_t)(atm_fx_compact_state.head + off) & ATM_FX_COMPACT_MASK];
}

/* One tick with no commands: effects advance, no delays to count down. */
static void atm_fx_compact_run_effects(void)
{
	for (uint8_t ch_index = 0; ch_index < OSC_CH_COUNT; ch_index++) {
		process_fx(ch_index, &atmlib_state, &channels[ch_index]);
	}
	osc_set_tick_rate(0, atmlib_state.tick_rate);
}

/* Walk the pinned record from the current head. When apply == 0 this only
 * preflights structure (no effect/command/oscillator mutation); when apply != 0
 * it runs effects and commands in the original channel order. Returns the
 * record length, or a negative error code. */
static int16_t atm_fx_compact_walk(const uint8_t apply, uint16_t *gap_out)
{
	const uint8_t len = atm_fx_compact_read(0);
	uint8_t pos = 1;
	uint16_t gap;

	const uint8_t b0 = atm_fx_compact_read(pos++);
	if (b0 < 0x80) {
		gap = b0;
	} else if (b0 != 0xFF) {
		gap = (uint16_t)(((uint16_t)(b0 & 0x7F) << 8) |
			atm_fx_compact_read(pos++));
	} else {
		gap = (uint16_t)(((uint16_t)atm_fx_compact_read(pos) << 8) |
			atm_fx_compact_read((uint8_t)(pos + 1)));
		pos = (uint8_t)(pos + 2);
	}
	if (pos >= len) return -1;

	const uint8_t bitmap = atm_fx_compact_read(pos++);
	if (bitmap == 0 || (bitmap & 0xF0)) return -1;

	for (uint8_t ch_index = 0; ch_index < OSC_CH_COUNT; ch_index++) {
		struct atm_channel_state *ch = &channels[ch_index];

		if (apply) {
			process_fx(ch_index, &atmlib_state, ch);
		}

		if (bitmap & (1u << ch_index)) {
			if (pos >= len) return -1;
			const uint8_t glen = atm_fx_compact_read(pos++);
			if (glen == 0) return -1;
			const uint8_t end = (uint8_t)(pos + glen);
			if (end > len || end < pos) return -1;
			while (pos < end) {
				const uint8_t id = atm_fx_compact_read(pos);
				const uint8_t sz = atm_fx_compact_cmd_bytes(id);
				if ((uint8_t)(pos + sz) > end ||
				    (uint8_t)(pos + sz) < pos) {
					return -1;
				}
				if (apply) {
					struct atm_cmd_data cmd;
					cmd.id = id;
					cmd.params[0] = sz > 1 ? atm_fx_compact_read((uint8_t)(pos + 1)) : 0;
					cmd.params[1] = sz > 2 ? atm_fx_compact_read((uint8_t)(pos + 2)) : 0;
					cmd.params[2] = sz > 3 ? atm_fx_compact_read((uint8_t)(pos + 3)) : 0;
					apply_cmd(ch_index, &cmd, &atmlib_state, ch);
				}
				pos = (uint8_t)(pos + sz);
			}
		}

		if (apply) {
			osc_set_tick_rate(0, atmlib_state.tick_rate);
		}
	}

	if (pos != len) return -1;
	if (gap_out) *gap_out = gap;
	return (int16_t)len;
}

/* Refill the ring as far as the stream allows, directly into the ring. The
 * producer is foreground only; the timer never calls this. */
static void atm_fx_compact_fill(void)
{
	for (;;) {
		const uint8_t used = (uint8_t)(
			atm_fx_compact_state.tail - atm_fx_compact_state.head);
		const uint8_t space = (uint8_t)(ATM_FX_COMPACT_RING - used);
		if (space == 0) {
			break;
		}
		if (atm_fx_compact_state.next_offset >= atm_fx_compact_state.stream_end) {
			break;
		}

		const uint8_t off =
			(uint8_t)(atm_fx_compact_state.tail & ATM_FX_COMPACT_MASK);
		uint8_t n = (uint8_t)(ATM_FX_COMPACT_RING - off);
		if (n > space) {
			n = space;
		}
		if (n > ATM_FX_COMPACT_CHUNK) {
			n = ATM_FX_COMPACT_CHUNK;
		}
		const uint32_t rem =
			atm_fx_compact_state.stream_end - atm_fx_compact_state.next_offset;
		if ((uint32_t)n > rem) {
			n = (uint8_t)rem;
		}

		atm_fx_compact_fetch(atm_fx_compact_state.next_offset,
			&atm_fx_compact_state.buf[off], n);

		/* Publish: the buffer writes must be visible before tail advances. */
		__asm__ __volatile__("" ::: "memory");
		atm_fx_compact_state.tail =
			(uint8_t)(atm_fx_compact_state.tail + n);
		atm_fx_compact_state.next_offset += n;
	}
}

static void atm_fx_compact_tick_handler(uint8_t cb_index, void *priv)
{
	(void)cb_index;
	(void)priv;

#if ATM_FX_COMPACT_DIAG
	if (atm_fx_compact_state.service_gap != 0xFFFF) {
		atm_fx_compact_state.service_gap++;
	}
	if (atm_fx_compact_state.service_gap > atm_fx_compact_state.max_service_gap) {
		atm_fx_compact_state.max_service_gap = atm_fx_compact_state.service_gap;
	}
	if (atm_fx_compact_state.ticks != 0xFFFF) {
		atm_fx_compact_state.ticks++;
	}
#endif

	if (!atm_fx_compact_state.active) {
		osc_set_tick_callback(0, NULL, NULL);
		return;
	}
	if (atm_fx_compact_state.paused) {
		/* Position/live state must not advance while paused. */
		return;
	}

	const uint16_t gap = atm_fx_compact_state.gap;

	if (gap != 0) {
		atm_fx_compact_state.gap = (uint16_t)(gap - 1);
		atm_fx_compact_run_effects();
		return;
	}

	/* Pass tick. Preflight the complete record before any mutation. */
	const uint8_t avail = (uint8_t)(
		atm_fx_compact_state.tail - atm_fx_compact_state.head);

	if (avail < 1) {
#if ATM_FX_COMPACT_DIAG
		atm_fx_compact_state.underruns++;
#endif
		return; /* freeze: no effect or tick state advances */
	}

	const uint8_t rec_len = atm_fx_compact_read(0);

	if (rec_len == 0) {
		/* END: finite completion. */
		atm_fx_compact_stop();
#if ATM_FX_COMPACT_DIAG
		atm_fx_compact_state.stop_tick = atm_fx_compact_state.ticks;
#endif
		return;
	}
	if (rec_len < 5 || rec_len > ATM_FX_COMPACT_RING) {
		atm_fx_compact_state.error = 2; /* oversize / impossible */
		atm_fx_compact_stop();
		return;
	}
	if (avail < rec_len) {
#if ATM_FX_COMPACT_DIAG
		atm_fx_compact_state.underruns++;
#endif
		return; /* freeze: whole record is not yet resident */
	}

	if (atm_fx_compact_walk(0, NULL) != (int16_t)rec_len) {
		atm_fx_compact_state.error = 1; /* malformed */
		atm_fx_compact_stop();
		return;
	}

	uint16_t next_gap = 0;
	(void)atm_fx_compact_walk(1, &next_gap);

	/* Publish consumption of the pinned record. */
	atm_fx_compact_state.head =
		(uint8_t)(atm_fx_compact_state.head + rec_len);

#if ATM_FX_COMPACT_DIAG
	if (rec_len > atm_fx_compact_state.max_record) {
		atm_fx_compact_state.max_record = rec_len;
	}
	{
		const uint16_t w = (uint16_t)atm_fx_compact_state.window + rec_len;
		atm_fx_compact_state.window = w > 0xFF ? 0xFF : (uint8_t)w;
	}
	if (atm_fx_compact_state.window > atm_fx_compact_state.max_window) {
		atm_fx_compact_state.max_window = atm_fx_compact_state.window;
	}
#endif

	atm_fx_compact_state.gap = next_gap;

	/* Match the original score handler: stop as soon as no voice is active. */
	if (!(atmlib_state.channel_active_mute & 0xF0)) {
		atm_fx_compact_stop();
#if ATM_FX_COMPACT_DIAG
		atm_fx_compact_state.stop_tick = atm_fx_compact_state.ticks;
#endif
	}
}

/* ------------------------------------------------------------------------- */
#if ATM_FX_COMPACT_SFX
/*
 * Independent-tempo SFX overlay.
 *
 * The SFX stream is a compact record stream stored in PROGMEM. It is read
 * directly by the timer (pgm_read_byte); no FX SPI and no second ring are
 * required, so there is no mandatory second queue. It drives one borrowed music
 * channel on its own tick callback (index 1) at its own tempo, exactly the way
 * the original library borrows a channel for a sound effect.
 */

/* Read one byte of the SFX record, offset from the current SFX position. */
static inline uint8_t atm_fx_compact_sfx_read(const uint8_t off)
{
	return pgm_read_byte(atm_fx_compact_state.sfx_ptr +
		atm_fx_compact_state.sfx_pos + off);
}

/* Preflight (apply==0) or apply one SFX pass. Returns the record length, 0 for
 * an END record, or a negative error. The record's bitmap must name exactly the
 * borrowed channel. */
static int16_t atm_fx_compact_sfx_walk(const uint8_t apply, uint16_t *gap_out)
{
	const uint8_t len = atm_fx_compact_sfx_read(0);
	if (len == 0) return 0;
	if (len < 5) return -1;

	uint8_t pos = 1;
	uint16_t gap;
	const uint8_t b0 = atm_fx_compact_sfx_read(pos++);
	if (b0 < 0x80) {
		gap = b0;
	} else if (b0 != 0xFF) {
		gap = (uint16_t)(((uint16_t)(b0 & 0x7F) << 8) |
			atm_fx_compact_sfx_read(pos++));
	} else {
		gap = (uint16_t)(((uint16_t)atm_fx_compact_sfx_read(pos) << 8) |
			atm_fx_compact_sfx_read((uint8_t)(pos + 1)));
		pos = (uint8_t)(pos + 2);
	}
	if (pos >= len) return -1;

	const uint8_t bitmap = atm_fx_compact_sfx_read(pos++);
	const uint8_t ch_index = atm_fx_compact_state.sfx_ch;
	if (bitmap != (uint8_t)(1u << ch_index)) return -1;

	if (pos >= len) return -1;
	const uint8_t glen = atm_fx_compact_sfx_read(pos++);
	if (glen == 0) return -1;
	const uint8_t end = (uint8_t)(pos + glen);
	if (end > len || end < pos) return -1;

	struct atm_channel_state *ch = &atm_fx_compact_state.sfx_channel;
	struct atm_synth_state *track = &atm_fx_compact_state.sfx_track;

	if (apply) {
		process_fx(ch_index, track, ch);
	}

	while (pos < end) {
		const uint8_t id = atm_fx_compact_sfx_read(pos);
		const uint8_t sz = atm_fx_compact_cmd_bytes(id);
		if ((uint8_t)(pos + sz) > end || (uint8_t)(pos + sz) < pos) {
			return -1;
		}
		if (apply) {
			struct atm_cmd_data cmd;
			cmd.id = id;
			cmd.params[0] = sz > 1 ? atm_fx_compact_sfx_read((uint8_t)(pos + 1)) : 0;
			cmd.params[1] = sz > 2 ? atm_fx_compact_sfx_read((uint8_t)(pos + 2)) : 0;
			cmd.params[2] = sz > 3 ? atm_fx_compact_sfx_read((uint8_t)(pos + 3)) : 0;
			apply_cmd(ch_index, &cmd, track, ch);
		}
		pos = (uint8_t)(pos + sz);
	}

	if (pos != len) return -1;
	if (gap_out) *gap_out = gap;
	return (int16_t)len;
}

static void atm_fx_compact_sfx_tick_handler(uint8_t cb_index, void *priv)
{
	(void)cb_index;
	(void)priv;

#if ATM_FX_COMPACT_DIAG
	if (atm_fx_compact_state.sfx_ticks != 0xFFFF) {
		atm_fx_compact_state.sfx_ticks++;
	}
#endif

	if (!atm_fx_compact_state.sfx_active) {
		osc_set_tick_callback(1, NULL, NULL);
		return;
	}

	const uint16_t gap = atm_fx_compact_state.sfx_gap;

	if (gap != 0) {
		atm_fx_compact_state.sfx_gap = (uint16_t)(gap - 1);
		process_fx(atm_fx_compact_state.sfx_ch,
			&atm_fx_compact_state.sfx_track,
			&atm_fx_compact_state.sfx_channel);
		osc_set_tick_rate(1, atm_fx_compact_state.sfx_track.tick_rate);
	} else {
		/* Pass tick. Preflight before mutation; PROGMEM is resident. */
		if (atm_fx_compact_state.sfx_pos >= atm_fx_compact_state.sfx_end) {
			atm_fx_compact_stop_sfx();
			return;
		}
		const int16_t rec_len = atm_fx_compact_sfx_walk(0, NULL);
		if (rec_len <= 0) {
			/* END or malformed: restore the borrowed voice and unregister. */
			atm_fx_compact_stop_sfx();
			return;
		}

		uint16_t next_gap = 0;
		(void)atm_fx_compact_sfx_walk(1, &next_gap);
		atm_fx_compact_state.sfx_pos += (uint16_t)rec_len;
		atm_fx_compact_state.sfx_gap = next_gap;
		osc_set_tick_rate(1, atm_fx_compact_state.sfx_track.tick_rate);

		if (!(atm_fx_compact_state.sfx_track.channel_active_mute & 0xF0)) {
			/* SFX ran its course. */
			atm_fx_compact_stop_sfx();
		}
	}

#if ATM_FX_COMPACT_DIAG
	atm_fx_compact_state.sfx_last_inc =
		osc_params_array[atm_fx_compact_state.sfx_ch].phase_increment;
#endif
}
#endif /* ATM_FX_COMPACT_SFX */

/* ------------------------------------------------------------------------- */

void atm_fx_compact_stop(void)
{
	ATM_FX_COMPACT_ATOMIC {
		atm_fx_compact_state.active = 0;
		atm_fx_compact_state.paused = 0;
		osc_set_tick_callback(0, NULL, NULL);
	}
#if ATM_FX_COMPACT_SFX
	atm_fx_compact_stop_sfx();
#endif
	/* Mute the owned voices. */
	for (uint8_t n = 0; n < OSC_CH_COUNT; n++) {
		osc_params_array[n].vol = 0;
	}
}

uint8_t atm_fx_compact_is_active(void)
{
	return atm_fx_compact_state.active;
}

void atm_fx_compact_pause(void)
{
	if (!atm_fx_compact_state.active || atm_fx_compact_state.paused) {
		return;
	}
	ATM_FX_COMPACT_ATOMIC {
		for (uint8_t n = 0; n < OSC_CH_COUNT; n++) {
			struct osc_params *p = channels[n].dst_osc_params;
			atm_fx_compact_state.paused_vol[n] = p->vol;
			p->vol = 0;
		}
		atm_fx_compact_state.paused = 1;
		osc_set_tick_callback(0, NULL, NULL);
	}
}

void atm_fx_compact_resume(void)
{
	if (!atm_fx_compact_state.active || !atm_fx_compact_state.paused) {
		return;
	}
	ATM_FX_COMPACT_ATOMIC {
		for (uint8_t n = 0; n < OSC_CH_COUNT; n++) {
			channels[n].dst_osc_params->vol =
				atm_fx_compact_state.paused_vol[n];
		}
		atm_fx_compact_state.paused = 0;
		osc_set_tick_rate(0, atmlib_state.tick_rate);
		osc_set_tick_callback(0, atm_fx_compact_tick_handler, NULL);
	}
}

uint8_t atm_fx_compact_is_paused(void)
{
	return atm_fx_compact_state.paused;
}

void atm_fx_compact_play(uint32_t offset, uint32_t length)
{
	/* Atomic replacement: stop previous playback (mutes owned voices and
	 * restores any borrowed SFX voice) before touching the descriptor. */
	atm_fx_compact_stop();

	atm_fx_compact_channels_init();
	atmlib_state.channel_active_mute = 0b11110000;
	atmlib_state.tick_rate = 25;

	ATM_FX_COMPACT_ATOMIC {
		atm_fx_compact_state.head = 0;
		atm_fx_compact_state.tail = 0;
		/* byte 0 is the compact magic/version header, skipped by the decoder */
		atm_fx_compact_state.next_offset = offset + 1;
		atm_fx_compact_state.stream_end = offset + length;
		atm_fx_compact_state.active = 1;
		atm_fx_compact_state.paused = 0;
		atm_fx_compact_state.gap = 0;
		atm_fx_compact_state.error = 0;
#if ATM_FX_COMPACT_DIAG
		atm_fx_compact_state.ticks = 0;
		atm_fx_compact_state.underruns = 0;
		atm_fx_compact_state.service_gap = 0;
		atm_fx_compact_state.max_service_gap = 0;
		atm_fx_compact_state.serviced = 0;
		atm_fx_compact_state.stop_tick = 0;
		atm_fx_compact_state.max_record = 0;
		atm_fx_compact_state.window = 0;
		atm_fx_compact_state.max_window = 0;
#endif
	}

	/* Prefill the first record before arming. The callback is still
	 * unregistered, so SPI runs with sample interrupts enabled and the timer
	 * cannot observe a partial ring. */
	atm_fx_compact_fill();

	osc_set_tick_rate(0, atmlib_state.tick_rate);
	ATM_FX_COMPACT_ATOMIC {
		osc_set_tick_callback(0, atm_fx_compact_tick_handler, NULL);
	}
}

void atm_fx_compact_service(void)
{
#if ATM_FX_COMPACT_DIAG
	atm_fx_compact_state.serviced++;
	atm_fx_compact_state.service_gap = 0;
	atm_fx_compact_state.window = 0;
#endif

	if (!atm_fx_compact_state.active || atm_fx_compact_state.paused) {
		return;
	}

	atm_fx_compact_fill();
}

#if ATM_FX_COMPACT_SFX
void atm_fx_compact_play_sfx(uint8_t channel_index, const uint8_t *stream, uint32_t length)
{
	/* Replace any current SFX first: restores its borrowed voice. */
	atm_fx_compact_stop_sfx();

	struct atm_channel_state *mch = &channels[channel_index];

	ATM_FX_COMPACT_ATOMIC {
		/* Borrow: save the audible music voice, silence it, and redirect the
		 * music channel's effects into the saved shadow so music keeps
		 * advancing behind the borrowed channel. */
		atm_fx_compact_state.sfx_save = osc_params_array[channel_index];
		memset(&osc_params_array[channel_index], 0, sizeof(osc_params_array[0]));
		mch->dst_osc_params = &atm_fx_compact_state.sfx_save;

		struct atm_channel_state *sch = &atm_fx_compact_state.sfx_channel;
		memset(sch, 0, sizeof(*sch));
#if ATM_HAS_FX_NOTE_RETRIG
		sch->arpCount = 0x80;
#endif
		sch->mod = 0x7F;
		sch->dst_osc_params = &osc_params_array[channel_index];

		atm_fx_compact_state.sfx_track.tick_rate = 25;
		atm_fx_compact_state.sfx_track.channel_active_mute =
			(uint8_t)(1u << (channel_index + OSC_CH_COUNT));

		atm_fx_compact_state.sfx_ptr = stream;
		atm_fx_compact_state.sfx_end = length;
		atm_fx_compact_state.sfx_pos = 1; /* skip magic/version header */
		atm_fx_compact_state.sfx_gap = 0;
		atm_fx_compact_state.sfx_ch = channel_index;
		atm_fx_compact_state.sfx_active = 1;
#if ATM_FX_COMPACT_DIAG
		atm_fx_compact_state.sfx_ticks = 0;
		atm_fx_compact_state.sfx_start_tick = atm_fx_compact_state.ticks;
		atm_fx_compact_state.sfx_stop_tick = 0;
		atm_fx_compact_state.sfx_last_inc = 0;
		atm_fx_compact_state.sfx_restore_inc = 0;
		atm_fx_compact_state.sfx_borrow = channel_index;
		atm_fx_compact_state.sfx_restore_ok = 0;
#endif
	}

	osc_set_tick_rate(1, atm_fx_compact_state.sfx_track.tick_rate);
	ATM_FX_COMPACT_ATOMIC {
		osc_set_tick_callback(1, atm_fx_compact_sfx_tick_handler, NULL);
	}
}

void atm_fx_compact_stop_sfx(void)
{
	if (!atm_fx_compact_state.sfx_active) {
		return;
	}
	const uint8_t ch = atm_fx_compact_state.sfx_ch;

	ATM_FX_COMPACT_ATOMIC {
		osc_set_tick_callback(1, NULL, NULL);
		atm_fx_compact_state.sfx_active = 0;
	}

	/* Restore the music voice from the (possibly music-updated) shadow. */
	osc_params_array[ch] = *channels[ch].dst_osc_params;
	channels[ch].dst_osc_params = &osc_params_array[ch];

#if ATM_FX_COMPACT_DIAG
	atm_fx_compact_state.sfx_stop_tick = atm_fx_compact_state.ticks;
	atm_fx_compact_state.sfx_restore_inc = osc_params_array[ch].phase_increment;
	atm_fx_compact_state.sfx_restore_ok = 1;
#endif
}

uint8_t atm_fx_compact_is_sfx_active(void)
{
	return atm_fx_compact_state.sfx_active;
}
#endif /* ATM_FX_COMPACT_SFX */

#endif /* ATM_FX_COMPACT_IMPL */
