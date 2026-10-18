/*
 * atm_fx_stream.c - compiled FX music stream decoder (ATMlib2FX-aoe prototype).
 *
 * This file is #included by src/atm_synth.c (after the static effect/command
 * helpers and after src/cmd_parse.c) when ATM_HAS_FX_STREAM == 1, so it can
 * reuse process_fx(), apply_cmd() and the shared channel/oscillator arrays.
 * The whole body is guarded so a standalone compile (arduino-cli compiles every
 * .c in src/) produces nothing, exactly like src/cmd_parse.c.
 */
#ifdef ATM_FX_STREAM_IMPL

#define ATM_FX_MAGIC (0xF5u)
#define ATM_FX_END (0x10u)
#define ATM_FX_SKIP (0x00u)
#define ATM_FX_RING_MASK (ATM_FX_REFILL_BYTES - 1)

#if (ATM_FX_REFILL_BYTES & ATM_FX_RING_MASK) != 0
#error "ATM_FX_REFILL_BYTES must be a power of two"
#endif

struct atm_fx_stream_state atm_fx_stream_state;

/* Byte length of one command, matching the original encoding. */
static uint8_t atm_fx_cmd_bytes(const uint8_t id)
{
	if (id < ATM_CMD_BLK_DELAY)       return 1;
	if (id < ATM_CMD_BLK_IMMEDIATE)   return 1;
	if (id < ATM_CMD_BLK_1_PARAMETER) return 1;
	if (id < ATM_CMD_BLK_N_PARAMETER) return 2;
	return (uint8_t)(1 + (((id >> 4) & 0x07) + 1));
}

static void atm_fx_channels_init(void)
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

/* One tick with no commands: effects advance, delays count down. Mirrors the
 * delayed branch of process_channel(). */
static void atm_fx_run_silent_tick(void)
{
	for (uint8_t ch_index = 0; ch_index < OSC_CH_COUNT; ch_index++) {
		process_fx(ch_index, &atmlib_state, &channels[ch_index]);
		if (channels[ch_index].delay != 0xFFFF) {
			channels[ch_index].delay--;
		}
	}
	osc_set_tick_rate(0, atmlib_state.tick_rate);
}

/* Apply one staged APPLY frame: for every channel in order, run effects, then
 * replay that channel's commands. Never advances channels of other ticks. */
static void atm_fx_apply_frame(const uint8_t *frame)
{
	const uint8_t ctl = frame[0];
	uint8_t off = 1;

	for (uint8_t ch_index = 0; ch_index < OSC_CH_COUNT; ch_index++) {
		struct atm_channel_state *ch = &channels[ch_index];

		process_fx(ch_index, &atmlib_state, ch);

		if (ctl & (1u << ch_index)) {
			const uint8_t len = frame[off++];
			const uint8_t end = (uint8_t)(off + len);
			while (off < end) {
				struct atm_cmd_data cmd;
				const uint8_t id = frame[off];
				const uint8_t sz = atm_fx_cmd_bytes(id);
				cmd.id = id;
				cmd.params[0] = sz > 1 ? frame[off + 1] : 0;
				cmd.params[1] = sz > 2 ? frame[off + 2] : 0;
				cmd.params[2] = sz > 3 ? frame[off + 3] : 0;
				off = (uint8_t)(off + sz);
				apply_cmd(ch_index, &cmd, &atmlib_state, ch);
			}
		}

		if (ch->delay != 0xFFFF) {
			ch->delay--;
		}
	}
	osc_set_tick_rate(0, atmlib_state.tick_rate);
}

static void atm_fx_stream_tick_handler(uint8_t cb_index, void *priv)
{
	(void)cb_index;
	(void)priv;

#if ATM_FX_STREAM_DIAG
	if (atm_fx_stream_state.gap != 0xFFFF) {
		atm_fx_stream_state.gap++;
	}
	if (atm_fx_stream_state.gap > atm_fx_stream_state.max_gap) {
		atm_fx_stream_state.max_gap = atm_fx_stream_state.gap;
	}
	if (atm_fx_stream_state.ticks != 0xFFFF) {
		atm_fx_stream_state.ticks++;
	}
#endif

	if (!atm_fx_stream_state.active) {
		osc_set_tick_callback(0, NULL, NULL);
		return;
	}

	/* A SKIP record covers a run of silent ticks; the timer still fires once
	 * per tick, so each callback advances exactly one tick. */
	if (atm_fx_stream_state.silent_remaining) {
		atm_fx_stream_state.silent_remaining--;
		atm_fx_run_silent_tick();
		return;
	}

	const uint8_t h = atm_fx_stream_state.head;
	const uint8_t avail = (uint8_t)(atm_fx_stream_state.tail - h);

	if (avail < 1) {
#if ATM_FX_STREAM_DIAG
		atm_fx_stream_state.underruns++;
#endif
		return;
	}

	const uint8_t ctl = atm_fx_stream_state.buf[h & ATM_FX_RING_MASK];

	if (ctl == ATM_FX_END) {
		atm_fx_stream_state.active = 0;
		osc_set_tick_callback(0, NULL, NULL);
		return;
	}

	if (ctl == ATM_FX_SKIP) {
		if (avail < 2) {
#if ATM_FX_STREAM_DIAG
			atm_fx_stream_state.underruns++;
#endif
			return;
		}
		const uint8_t n = (uint8_t)(
			atm_fx_stream_state.buf[(uint8_t)(h + 1) & ATM_FX_RING_MASK] + 1);
		atm_fx_stream_state.head = (uint8_t)(h + 2);
		atm_fx_stream_state.silent_remaining = (uint8_t)(n - 1);
		atm_fx_run_silent_tick();
		return;
	}

	/* APPLY: stage the complete frame before mutating any channel state, so an
	 * underrun can never apply a partial music tick. */
	uint8_t frame[ATM_FX_MAX_FRAME];
	uint8_t need = 1;
	frame[0] = ctl;

	for (uint8_t ch_index = 0; ch_index < OSC_CH_COUNT; ch_index++) {
		if (!(ctl & (1u << ch_index))) {
			continue;
		}
		if (need >= ATM_FX_MAX_FRAME || avail < (uint8_t)(need + 1)) {
#if ATM_FX_STREAM_DIAG
			atm_fx_stream_state.underruns++;
#endif
			return;
		}
		const uint8_t len = atm_fx_stream_state.buf[(uint8_t)(h + need) & ATM_FX_RING_MASK];
		frame[need] = len;
		need = (uint8_t)(need + 1);
		if ((uint8_t)(need + len) < need || avail < (uint8_t)(need + len)) {
#if ATM_FX_STREAM_DIAG
			atm_fx_stream_state.underruns++;
#endif
			return;
		}
		if ((uint16_t)need + len > ATM_FX_MAX_FRAME) {
#if ATM_FX_STREAM_DIAG
			atm_fx_stream_state.overflow++;
#endif
			atm_fx_stream_state.active = 0;
			osc_set_tick_callback(0, NULL, NULL);
			return;
		}
		for (uint8_t i = 0; i < len; i++) {
			frame[need + i] =
				atm_fx_stream_state.buf[(uint8_t)(h + need + i) & ATM_FX_RING_MASK];
		}
		need = (uint8_t)(need + len);
	}

	atm_fx_stream_state.head = (uint8_t)(h + need);
	atm_fx_apply_frame(frame);
}

void atm_fx_stream_stop(void)
{
	atm_fx_stream_state.active = 0;
	osc_set_tick_callback(0, NULL, NULL);
}

uint8_t atm_fx_stream_is_active(void)
{
	return atm_fx_stream_state.active;
}

void atm_fx_stream_play(uint32_t offset, uint32_t length)
{
	atm_fx_stream_stop();

	atm_fx_channels_init();
	atmlib_state.channel_active_mute = 0b11110000;
	atmlib_state.tick_rate = 25;

	atm_fx_stream_state.head = 0;
	atm_fx_stream_state.tail = 0;
	/* byte 0 is the stream magic/version header, skipped by the decoder */
	atm_fx_stream_state.next_offset = offset + 1;
	atm_fx_stream_state.stream_end = offset + length;
	atm_fx_stream_state.active = 1;
	atm_fx_stream_state.silent_remaining = 0;
#if ATM_FX_STREAM_DIAG
	atm_fx_stream_state.ticks = 0;
	atm_fx_stream_state.underruns = 0;
	atm_fx_stream_state.gap = 0;
	atm_fx_stream_state.max_gap = 0;
	atm_fx_stream_state.overflow = 0;
	atm_fx_stream_state.serviced = 0;
#endif

	osc_set_tick_rate(0, atmlib_state.tick_rate);
	osc_set_tick_callback(0, atm_fx_stream_tick_handler, NULL);
}

void atm_fx_stream_service(void)
{
#if ATM_FX_STREAM_DIAG
	atm_fx_stream_state.serviced++;
	atm_fx_stream_state.gap = 0;
#endif

	if (!atm_fx_stream_state.active) {
		return;
	}

	/* Fill the ring as far as the stream allows, in bounded chunks. */
	for (;;) {
		const uint8_t used = (uint8_t)(atm_fx_stream_state.tail - atm_fx_stream_state.head);
		const uint8_t space = (uint8_t)(ATM_FX_REFILL_BYTES - used);
		if (space == 0) {
			break;
		}

		uint8_t n = space > ATM_FX_REFILL_CHUNK ? ATM_FX_REFILL_CHUNK : space;
		if (atm_fx_stream_state.next_offset + n > atm_fx_stream_state.stream_end) {
			const uint32_t rem = atm_fx_stream_state.stream_end - atm_fx_stream_state.next_offset;
			if (rem == 0) {
				break;
			}
			if (rem < n) {
				n = (uint8_t)rem;
			}
		}

		uint8_t tmp[ATM_FX_REFILL_CHUNK];
		atm_fx_stream_fetch(atm_fx_stream_state.next_offset, tmp, n);

		for (uint8_t i = 0; i < n; i++) {
			atm_fx_stream_state.buf[
				(uint8_t)(atm_fx_stream_state.tail + i) & ATM_FX_RING_MASK] = tmp[i];
		}
		/* Publish: the buffer writes must be visible before tail advances. */
		__asm__ __volatile__("" ::: "memory");
		atm_fx_stream_state.tail = (uint8_t)(atm_fx_stream_state.tail + n);
		atm_fx_stream_state.next_offset += n;
	}
}

#endif /* ATM_FX_STREAM_IMPL */
