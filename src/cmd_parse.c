
/* compile only when included by atm_synth.c */
#ifdef ATM_CMD_PARSE_IMPL

#include "atm_cmd_constants.h"

static void trigger_note(const uint8_t note, struct atm_channel_state *ch)
{
	ch->dst_osc_params->phase_increment = note_index_2_phase_inc(note + ch->trans_config);
	if (!note) {
		/* Note off / note cut: silence the channel. Keep the current mod
		 * so an in-flight mod slide and the last SET_MOD value are preserved. */
		ch->dst_osc_params->vol = 0;
		return;
	} else {
#if ATM_HAS_FX_SLIDE
		if (!ch->vf_slide.slide_amount) {
			/* No slide */
			goto trigger_both;
		} else if (ch->vf_slide.slide_config & 0x40) {
			/* Slide is re-triggered */
			ch->vf_slide.slide_count &= 0x3F;
			goto trigger_both;
		} else {
			/* Slide is not re-triggered */
			const uint8_t q = ch->vf_slide.slide_count & 0xC0;
			if (q == 0) {
				/* Vol slide, don't trigger vol */
				ch->dst_osc_params->mod = ch->mod;
			} else if (q == 0x80) {
				/* Mod slide, don't trigger mod */
				ch->dst_osc_params->vol = ch->vol;
			} else {
				goto trigger_both;
			}
		}
		return;
#else
		goto trigger_both;
#endif
	}

trigger_both:
	ch->dst_osc_params->vol = ch->vol;
	ch->dst_osc_params->mod = ch->mod;
}

static void process_immediate_cmd(const uint8_t ch_index, const uint8_t cmd_id, struct atm_synth_state *score_state, struct atm_channel_state *ch)
{
	const enum atm_immediate_cmd_constants cid = cmd_id;

	/* Immediate commands */
	switch (cid) {

		case ATM_CMD_I_TRANSPOSITION_OFF:
			ch->trans_config = 0;
			break;

		case ATM_CMD_I_PATTERN_END:
			/* The compact stream emits PATTERN_END only for a real channel
			 * stop; calls, repeats and returns are resolved offline. */
			goto stop_channel;

		case ATM_CMD_I_GLISSANDO_OFF:
#if ATM_HAS_FX_GLISSANDO
			ch->glisConfig = 0;
#endif
			break;


		case ATM_CMD_I_ARPEGGIO_OFF:
#if ATM_HAS_FX_NOTE_RETRIG
			ch->arpCount = 0x80;
#endif
			break;

		case ATM_CMD_I_NOISE_RETRIG_OFF:
#if ATM_HAS_FX_NOISE_RETRIG
			ch->reConfig = 0;
#endif
			break;
	}
	return;

stop_channel:
	score_state->channel_active_mute = score_state->channel_active_mute ^ (1 << (ch_index + OSC_CH_COUNT));
	ch->dst_osc_params->vol = 0;
	ch->delay = 0xFFFF;
}

static void process_1p_cmd(const struct atm_cmd_data *cmd, struct atm_synth_state *score_state, struct atm_channel_state *ch)
{
	const enum atm_single_byte_cmd_id_constants cid = cmd->id;

	switch (cid) {
		case ATM_CMD_1P_NOISE_RETRIG_ON:
#if ATM_HAS_FX_NOISE_RETRIG
			ch->reConfig = cmd->params[0];
			ch->reCount = 0;
#endif
			break;

		case ATM_CMD_1P_SET_TRANSPOSITION:
			ch->trans_config = cmd->params[0];
			break;

		case ATM_CMD_1P_ADD_TRANSPOSITION:
			ch->trans_config += (int8_t)cmd->params[0];
			break;

		case ATM_CMD_1P_SET_TEMPO:
			score_state->tick_rate = cmd->params[0];
			break;

		case ATM_CMD_1P_ADD_TEMPO:
			score_state->tick_rate += (int8_t)cmd->params[0];
			break;

		case ATM_CMD_1P_SET_VOLUME:
		{
			const uint8_t vol = cmd->params[0];
			ch->vol = vol;
			ch->dst_osc_params->vol = vol;
			break;
		}

		case ATM_CMD_1P_SET_MOD:
		{
			const uint8_t mod = cmd->params[0];
			ch->mod = mod;
			ch->dst_osc_params->mod = mod;
			break;
		}

		case ATM_CMD_1P_SET_CUE:
			/* CUE latches into the single shared cue byte so game
			 * code sees the most recent command. */
			atmlib_state.cue = cmd->params[0];
			break;
	}
}

static void process_np_cmd(const struct atm_cmd_data *cmd, const uint8_t csz, struct atm_synth_state *score_state, struct atm_channel_state *ch)
{
	(void)score_state;
	const enum atm_parametrised_cmd_id_constants cid = cmd->id & 0x0F;

	/* Parametrised commands */
	switch (cid) {
		case ATM_CMD_NP_GLISSANDO_ON:
#if ATM_HAS_FX_GLISSANDO
			ch->glisConfig = cmd->params[0];
			ch->glisCount = 0;
#endif
			break;

		case ATM_CMD_NP_ARPEGGIO_ON:
#if ATM_HAS_FX_NOTE_RETRIG
			ch->arpTiming = cmd->params[0];
			/* arpeggio or notecut */
			ch->arpNotes = csz > 1 ? cmd->params[1] : 0xFF;
			ch->arpCount = 0x00;
#endif
			break;

		case ATM_CMD_NP_SLIDE:
#if ATM_HAS_FX_SLIDE
			/* b------pp s = pp = param: vol, freq, mod */
			if (csz > 1) {
				/* FX on */
				ch->vf_slide.slide_count = cmd->params[0] << 6;
				ch->vf_slide.slide_amount = (int8_t)cmd->params[1];
				ch->vf_slide.slide_config = csz > 2 ? cmd->params[2] : 0;
			} else {
				/* FX off */
				ch->vf_slide.slide_amount = 0;
			}
#endif
			break;

		case ATM_CMD_NP_LFO:
#if ATM_HAS_FX_LFO
			/* b------pp s = pp = param: vol, freq, mod */
			if (csz > 1) {
				/* FX on */
				ch->treviDepth = cmd->params[1];
				ch->treviConfig = cmd->params[2] | (cmd->params[0] << 6);
				/* Effect starts from center point so it must run for 1/4 period
				   before changing sign. params[2] carries half period so div by 2
				*/
				ch->treviCount = (cmd->params[2] & 0x1F) >> 1;
			} else {
				/* FX off */
				ch->treviDepth = 0;
				/* This effect does not reset volume, pitch or mod to the center
				   value in case it is not interrupted on a period boundary.
				   Fixing this costs ~ +30 bytes of code so I'm calling it a
				   feature for the time being.
				trigger_note(ch->note, ch);
				*/
			}
#endif
			break;

		case ATM_CMD_NP_LONG_DELAY:
			ch->delay = csz > 1 ? (cmd->params[0]<<8)|cmd->params[1] : cmd->params[0];
			ch->delay += 1;
			break;
	}
}

/* Apply one command already fetched from the compact stream. Traversal was
 * resolved offline, so no pattern pointers or stacks are involved. */
static void apply_cmd(const uint8_t ch_index, const struct atm_cmd_data *cmd, struct atm_synth_state *score_state, struct atm_channel_state *ch)
{
	if (cmd->id < ATM_CMD_BLK_DELAY) {
		/* 0 … 63 : NOTE ON/OFF */
		ch->note = cmd->id;
		trigger_note(cmd->id, ch);

#if ATM_HAS_FX_NOTE_RETRIG
		/* ARP retriggering */
		if (ch->arpTiming & 0x20) {
			ch->arpCount = 0;
		}
#endif
	} else if (cmd->id < ATM_CMD_BLK_IMMEDIATE) {
		/* delay */
		ch->delay = cmd->id - 63;
	} else if (cmd->id < ATM_CMD_BLK_1_PARAMETER) {
		/* immediate */
		process_immediate_cmd(ch_index, cmd->id, score_state, ch);
	} else if (cmd->id < ATM_CMD_BLK_N_PARAMETER) {
		/* 1 parameter byte command */
		process_1p_cmd(cmd, score_state, ch);
	} else {
		const uint8_t csz = ((cmd->id >> 4) & 0x07) + 1;
		/* n parameter byte command */
		process_np_cmd(cmd, csz, score_state, ch);
	}
}

#endif
