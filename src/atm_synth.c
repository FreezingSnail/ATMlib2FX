#include <string.h>
#include <avr/pgmspace.h>

#include "atm_synth.h"

#define ARRAY_SIZE(a) (sizeof (a) / sizeof ((a)[0]))

struct atm_synth_state atmlib_state;

#define MAX_VOLUME (127)
#define LAST_NOTE (63)
const uint16_t noteTable[64] PROGMEM = {
	0,
	268,  284,  301,  319,  338,  358,  379,  401,  425,  451,  477,  506,
	536,  568,  601,  637,  675,  715,  758,  803,  851,  901,  955,  1011,
	1072, 1135, 1203, 1274, 1350, 1430, 1515, 1606, 1701, 1802, 1909, 2023,
	2143, 2271, 2406, 2549, 2700, 2861, 3031, 3211, 3402, 3604, 3819, 4046,
	4286, 4541, 4811, 5098, 5401, 5722, 6062, 6422, 6804, 7209, 7638, 8092,
	8573, 9083, 9623
};

static uint16_t note_index_2_phase_inc(const uint8_t note_idx)
{
	return pgm_read_word(&noteTable[(note_idx) & 0x3F]);
}

struct atm_channel_state channels[OSC_CH_COUNT];

/* ---- effect helpers ---- */

#if ATM_HAS_FX_GLISSANDO || ATM_HAS_FX_SLIDE || ATM_HAS_FX_LFO
/* flags: bit 7 = 0 clamp, 1 overflow */
static uint16_t slide_quantity(int8_t amount, int16_t value, int16_t bottom, int16_t top, uint8_t flags)
{
	const bool clamp = !(flags & 0x80);
	const int16_t res = value + amount;
	if (clamp) {
		if (res < bottom) {
			return bottom;
		} else if (res > top) {
			return top;
		}
	}
	return res;
}
#endif

#if ATM_HAS_FX_SLIDE || ATM_HAS_FX_LFO
static void addto_osc_param(const int8_t amount, const uint8_t param, struct osc_params *osc_params, const uint8_t flags)
{
	switch (param & 0xC0) {
		case 0:
			osc_params->vol = slide_quantity(amount, osc_params->vol, 0, MAX_VOLUME, flags);
			break;
		case 0x40:
			osc_params->phase_increment = slide_quantity(amount, osc_params->phase_increment, 0, OSC_PHASE_INC_MAX, flags);
			break;
		case 0x80:
			osc_params->mod = slide_quantity(amount, osc_params->mod, 0, OSC_MOD_MAX, flags);
			break;
	}
}
#endif

#if ATM_HAS_FX_SLIDE
static void slidefx(struct atm_slide_params *slide_params, struct osc_params *osc_params)
{
	if (slide_params->slide_amount) {
		if ((slide_params->slide_count & 0x3F) >= (slide_params->slide_config & 0x3F)) {
			addto_osc_param(slide_params->slide_amount, slide_params->slide_count & 0xC0, osc_params, slide_params->slide_config & 0x80);
			slide_params->slide_count &= 0xC0;
		} else {
			slide_params->slide_count++;
		}
	}
}
#endif

void atm_synth_setup(void)
{
	osc_setup();
	atmlib_state.channel_active_mute = 0;
	atmlib_state.cue = 0;
	for (unsigned n = 0; n < ARRAY_SIZE(channels); n++) {
		channels[n].dst_osc_params = &osc_params_array[n];
	}
}

uint8_t atm_synth_is_score_stopped(void)
{
	return !(atmlib_state.channel_active_mute & 0xF0);
}

uint8_t atm_synth_get_cue(void)
{
	const uint8_t cue = atmlib_state.cue;
	atmlib_state.cue = 0;
	return cue;
}

uint8_t atm_synth_check_cue(uint8_t id)
{
	return atmlib_state.cue == id;
}

void atm_synth_set_tempo(uint8_t tick_rate)
{
	if (tick_rate == 0) {
		tick_rate = 1;
	}
	atmlib_state.tick_rate = tick_rate;
	osc_set_tick_rate(0, atmlib_state.tick_rate);
}

/* The command interpreter is statically included so the compact decoder can
 * inline its effects/commands. */
#define ATM_CMD_PARSE_IMPL
#include "cmd_parse.c"
#undef ATM_CMD_PARSE_IMPL

/* Shared engine processing used by the compact decoder. */
static void process_fx(const uint8_t ch_index, struct atm_synth_state *score_state, struct atm_channel_state *ch)
{
	(void)(score_state);

#if ATM_HAS_FX_NOISE_RETRIG
	if (ch_index == OSC_CH_THREE && ch->reConfig && (ch->reCount++ >= (ch->reConfig & 0x03))) {
		ch->dst_osc_params->phase_increment = note_index_2_phase_inc(ch->reConfig >> 2);
		ch->reCount = 0;
	}
#endif

#if ATM_HAS_FX_GLISSANDO
	if (ch->glisConfig && (ch->glisCount++ >= (ch->glisConfig & 0x7F))) {
		const uint8_t amount = (ch->glisConfig & 0x80) ? -1 : 1;
		const uint8_t note = slide_quantity(amount, ch->note, 1, LAST_NOTE, 0);
		ch->note = note;
		ch->dst_osc_params->phase_increment = note_index_2_phase_inc(note);
		ch->glisCount = 0;
	}
#endif

#if ATM_HAS_FX_SLIDE
	slidefx(&ch->vf_slide, ch->dst_osc_params);
#endif

#if ATM_HAS_FX_NOTE_RETRIG
	{
		uint8_t arp_flags = ch->arpCount & 0xE0;
		if ((arp_flags != 0x80) && ch->note) {
			if ((ch->arpCount & 0x1F) < (ch->arpTiming & 0x1F)) {
				ch->arpCount++;
			} else {
				const uint8_t note = ch->note;
				const uint8_t num_notes = ch->arpTiming & 0x40 ? 0x20 : 0x40;
				uint8_t arp_note;

				if (arp_flags == num_notes) {
					const uint8_t disable_auto_trigger = ch->arpTiming & 0x20;
					arp_flags = disable_auto_trigger ? 0x80 : 0;
					arp_note = disable_auto_trigger ? 0 : note;
				} else {
					const uint8_t note_inc = arp_flags ? ch->arpNotes & 0x0F : ch->arpNotes >> 4;
					arp_note = note_inc == 0x0F ? 0 : note + note_inc;
					arp_flags += 0x20;
				}
				trigger_note(arp_note, ch);
				ch->arpCount = arp_flags;
			}
		}
	}
#endif

#if ATM_HAS_FX_LFO
	if (ch->treviDepth) {
		const int8_t amount = ch->treviCount & 0x80 ? ch->treviDepth : -ch->treviDepth;
		addto_osc_param(amount, ch->treviConfig & 0xC0, ch->dst_osc_params, 0);
		if ((ch->treviCount & 0x1F) < (ch->treviConfig & 0x1F)) {
			ch->treviCount++;
		} else {
			ch->treviCount = (ch->treviCount & 0x80) ? 0 : 0x80;
		}
	}
#endif
}

#include "atm_fx_compact.h"
#define ATM_FX_COMPACT_IMPL
#include "atm_fx_compact.c"
#undef ATM_FX_COMPACT_IMPL

void atm_synth_stop_score(void)
{
	atm_fx_compact_stop();
}

uint8_t atm_synth_get_score_paused(void)
{
	return atm_fx_compact_is_paused();
}

void atm_synth_set_score_paused(const uint8_t paused)
{
	if (paused) {
		atm_fx_compact_pause();
	} else {
		atm_fx_compact_resume();
	}
}
