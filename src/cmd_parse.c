
/* compile only when included by atm_synth.c */
#ifdef ATM_PATTERN_STACK_DEPTH

#include "cmd_constants.h"

/* #define log_cmd() to oblivion */
#define log_cmd(a,b,c,d)

static void cmd_note(const uint8_t cmd, struct channel_state *ch)
{
	ch->note = cmd;
	if (ch->note) {
		ch->note += ch->trans_config;
	}
	ch->dst_osc_params->phase_increment = note_index_2_phase_inc(ch->note);
	ch->dst_osc_params->vol = cmd ? ch->vol : 0;
	ch->dst_osc_params->mod = ch->mod;	
}

static void process_immediate_cmd(const uint8_t ch_index, const uint8_t cmd, struct atm_player_state *score_state, struct channel_state *ch)
{
/* Immediate commands */
	(void)(ch_index);
	switch (cmd) {
		case ATM_CMD_I_STOP:
			goto stop_channel;
		case ATM_CMD_I_RETURN:
		{
			if (pattern_repetition_counter(ch) > 0 || ch->pstack_index == 0) {
				/* Repeat track */
				if (pattern_repetition_counter(ch)) {
					pattern_repetition_counter(ch)--;
				}
				pattern_cmd_ptr(ch) = get_track_start_ptr(score_state, pattern_index(ch));
			} else {
				/* Check stack depth */
				if (ch->pstack_index == 0) {
					goto stop_channel;
				} else {
					/* pop stack */
					ch->pstack_index--;
				}
			}
			break;
		}

#if ATM_HAS_FX_GLISSANDO
		case ATM_CMD_I_GLISSANDO_OFF:
			ch->glisConfig = 0;
			break;
#endif

#if ATM_HAS_FX_ARPEGGIO
		case ATM_CMD_I_ARPEGGIO_OFF:
			ch->arpNotes = 0;
			break;
#endif

#if ATM_HAS_FX_NOTECUT
		case ATM_CMD_I_NOTECUT_OFF:
			ch->arpNotes = 0;
			break;
#endif

#if ATM_HAS_FX_NOISE_RETRIG
		case ATM_CMD_I_NOISE_RETRIG_OFF:
			ch->reConfig = 0;
			break;
#endif

		case ATM_CMD_I_TRANSPOSITION_OFF:
			ch->trans_config = 0;
			break;
	}
	return;

stop_channel:
	score_state->channel_active_mute = score_state->channel_active_mute ^ (1 << (ch_index + OSC_CH_COUNT));
	ch->dst_osc_params->vol = 0;
	ch->delay = 0xFFFF;
}

static void process_parametrised_cmd(const uint8_t ch_index, const uint8_t cmd, struct atm_player_state *score_state, struct channel_state *ch)
{
/* Parametrised commands */

	const uint8_t csz = ((cmd >> 4) & 0x7)+1;
{
	uint8_t data[csz];

	memcpy_P(data, pattern_cmd_ptr(ch), csz);
	pattern_cmd_ptr(ch) += csz;

	log_cmd(ch_index, cmd, csz, data);
	switch (cmd & 0x0F) {
		case ATM_CMD_ID_CALL:
			/* ignore call command if the stack is full */
			if (ch->pstack_index < ATM_PATTERN_STACK_DEPTH-1) {
				uint8_t new_track = data[0];
				uint8_t new_counter = csz > 1 ? data[1] : 0;
				if (new_track != pattern_index(ch)) {
					/* push new patten on stack */
					ch->pstack_index++;
					pattern_index(ch) = new_track;
				}
				pattern_repetition_counter(ch) = new_counter;
				pattern_cmd_ptr(ch) = get_track_start_ptr(score_state, pattern_index(ch));
			}
			break;

#if ATM_HAS_FX_GLISSANDO
		case ATM_CMD_ID_GLISSANDO_ON:
			ch->glisConfig = *data;
			ch->glisCount = 0;
			break;
#endif

#if ATM_HAS_FX_ARPEGGIO
		case ATM_CMD_ID_ARPEGGIO_ON:
			ch->arpNotes = data[0];
			ch->arpTiming = data[1];
			break;
#endif

#if ATM_HAS_FX_NOTECUT
		case ATM_CMD_ID_NOTECUT_ON:
			ch->arpNotes = 0xFF;
			ch->arpTiming = data[0];
			break;
#endif

#if ATM_HAS_FX_NOISE_RETRIG
		case ATM_CMD_ID_NOISE_RETRIG_ON:
			ch->reConfig = data[0];
			ch->reCount = 0;
			break;
#endif

		case ATM_CMD_ID_SET_TRANSPOSITION:
			ch->trans_config = data[0];
			break;
		case ATM_CMD_ID_ADD_TRANSPOSITION:
			ch->trans_config += (int8_t)data[0];
			break;
		case ATM_CMD_ID_SET_TEMPO:
			score_state->tick_rate = data[0];
			break;
		case ATM_CMD_ID_ADD_TEMPO:
			score_state->tick_rate += (int8_t)data[0];
			break;
		case ATM_CMD_ID_SET_VOLUME:
		{
			const uint8_t vol = data[0];
			ch->vol = vol;
			ch->dst_osc_params->vol = vol;
			break;
		}
		case ATM_CMD_ID_SET_MOD:
		{
			const uint8_t mod = data[0];
			ch->mod = mod;
			ch->dst_osc_params->mod = mod;
			break;
		}
		case ATM_CMD_ID_SET_LOOP_PATTERN:
			ch->loop_pattern_index = data[0];
			break;

#if ATM_HAS_FX_SLIDE
		case ATM_CMD_ID_SLIDE:
			/* b------pp s = 1:on 0:off, pp = param: vol, freq, mod */
			if (csz > 1) {
				/* FX on */
				ch->vf_slide.slide_count = data[0] << 6;
				ch->vf_slide.slide_amount = data[1];
				ch->vf_slide.slide_config = csz > 2 ? data[2] : 0;
			} else {
				/* FX off */
				ch->vf_slide.slide_amount = 0;
			}
			break;
#endif

#if ATM_HAS_FX_LFO
		case ATM_CMD_ID_LFO:
			/* b------pp s = 1:on 0:off, pp = param: vol, freq, mod */
			if (csz > 1) {
				/* FX on */
				ch->treviDepth = data[1];
				ch->treviConfig = data[2] | (data[0] << 6);
				ch->treviCount = 0;
			} else {
				/* FX off */
				ch->treviDepth = 0;
			}
			break;
#endif
	}
}
}

static void process_cmd(const uint8_t ch_index, const uint8_t cmd, struct atm_player_state *score_state, struct channel_state *ch)
{
	if (cmd < 64) {
		/* 0 … 63 : NOTE ON/OFF */
		cmd_note(cmd, ch);

#if ATM_HAS_FX_NOTE_RETRIG
		/* ARP retriggering */
		if (ch->arpTiming & 0x20) {
			ch->arpCount = 0;
		}
#endif
		log_cmd(ch_index, cmd, 0, NULL);
		return;
	}

	/* Cmd type is the 3 MSBs */
	const uint8_t type = cmd & 0xE0;
	if (type == 0x40) {
		/* delay */
		ch->delay = (cmd & 0x3F)+1;
		log_cmd(ch_index, cmd, 0, NULL);
	} else if (type == 0x60) {
		/* immediate */
		process_immediate_cmd(ch_index, cmd, score_state, ch);
		log_cmd(ch_index, cmd, 0, NULL);
	} else if (type & 0x80) {
		process_parametrised_cmd(ch_index, cmd, score_state, ch);
	}
}
#endif
