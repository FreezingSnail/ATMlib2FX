#ifndef ATM_SYNTH_H
#define ATM_SYNTH_H

#include <stddef.h>
#include <stdint.h>

#include "osc.h"
#include "atm_cmd_constants.h"

/* Compile-time mixer/effect gates. The compact FX decoder is the only playback
 * backend; these switches keep unused effect families out of small builds. */
/* Disable all FX to save space */
#define ATM_HAS_FX_NONE (0)

#if ATM_HAS_FX_NONE
#define ATM_HAS_FX_NOISE_RETRIG (0)
#define ATM_HAS_FX_NOTE_RETRIG (0)
#define ATM_HAS_FX_SLIDE (0)
#define ATM_HAS_FX_LFO (0)
#define ATM_HAS_FX_GLISSANDO (0)
#define ATM_HAS_FX_LOOP (0)
#else
#define ATM_HAS_FX_NOISE_RETRIG (1)
#define ATM_HAS_FX_NOTE_RETRIG (1)
#define ATM_HAS_FX_SLIDE (1)
#define ATM_HAS_FX_LFO (1)
#define ATM_HAS_FX_GLISSANDO (1)
#define ATM_HAS_FX_LOOP (1)
#endif

struct atm_synth_state;
struct atm_channel_state;
struct atm_cmd_data;

extern struct atm_synth_state atmlib_state;

void atm_synth_setup(void);

/* Stop the compact stream and mute the owned voices. */
void atm_synth_stop_score(void);
uint8_t atm_synth_is_score_stopped(void);

/* Compact-backend pause/resume (position and live state are preserved). */
void atm_synth_set_score_paused(uint8_t paused);
uint8_t atm_synth_get_score_paused(void);

/* Change the music tick rate (Hz) without a score command.
 *
 * Stored in atmlib_state.tick_rate and applied to the music callback
 * immediately. 0 is clamped to 1; the upper bound is 255. Rates below 8 are
 * accepted only for upstream parity because the timer divider wraps there. */
void atm_synth_set_tempo(uint8_t tick_rate);

/* Cue channel (ATM_CMD_M_CUE). The compact stream and any future overlay share
 * one cue byte; the most recent CUE wins. */
uint8_t atm_synth_get_cue(void);
uint8_t atm_synth_check_cue(uint8_t id);

/* Private structures: clients should not depend on these fields. */

struct atm_synth_state {
	uint8_t tick_rate;
	uint8_t channel_active_mute;
	uint8_t cue;
};

#if ATM_HAS_FX_SLIDE
struct atm_slide_params {
	int8_t slide_amount;
	uint8_t slide_config;
	uint8_t slide_count;
};
#endif

struct atm_channel_state {
	uint8_t note;
	uint8_t vol;
	uint8_t mod;
	uint16_t delay;
	int8_t trans_config;
	struct osc_params *dst_osc_params;

#if ATM_HAS_FX_SLIDE
	struct atm_slide_params vf_slide;
#endif

#if ATM_HAS_FX_NOTE_RETRIG
	uint8_t arpNotes;
	uint8_t arpTiming;
	uint8_t arpCount;
#endif

#if ATM_HAS_FX_NOISE_RETRIG
	uint8_t reConfig;
	uint8_t reCount;
#endif

#if ATM_HAS_FX_LFO
	uint8_t treviDepth;
	uint8_t treviConfig;
	uint8_t treviCount;
#endif

#if ATM_HAS_FX_GLISSANDO
	int8_t glisConfig;
	uint8_t glisCount;
#endif
};

struct atm_cmd_data {
	uint8_t id;
	uint8_t params[3];
};

#endif
