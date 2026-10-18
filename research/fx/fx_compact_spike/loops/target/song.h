/*
 * target/song.h - ATMlib2FX-hlh.8 loop fixture: changed loop targets,
 * including the original "cannot loop to pattern 0" quirk path.
 *
 * ch0 starts looping to pattern 1, but pattern 1 re-issues SET_LOOP_PATTERN(0),
 * so the next restart uses pattern 0 (which is legal because the engine
 * reserves 255, not 0, as the no-loop marker; commit 27c09a7). Pattern 0 then
 * re-issues SET_LOOP_PATTERN(1), so the target alternates 1 -> 0 -> 1.
 */
#ifndef SONG_H
#define SONG_H

#include "atm_cmd_constants.h"

/* ch0 entry: loop to pattern 1. */
#define pattern0_data { \
    ATM_CMD_M_SET_LOOP_PATTERN(1), \
    ATM_CMD_M_NOTE(10), \
    ATM_CMD_M_DELAY_TICKS(2), \
    ATM_CMD_I_STOP, \
}
/* changed target: loop to pattern 0 next time (the quirk path). */
#define pattern1_data { \
    ATM_CMD_M_SET_LOOP_PATTERN(0), \
    ATM_CMD_M_NOTE(11), \
    ATM_CMD_M_DELAY_TICKS(2), \
    ATM_CMD_I_STOP, \
}
/* ch1/ch2/ch3: stop immediately, no loop. */
#define pattern2_data { ATM_CMD_I_STOP, }

const PROGMEM struct score_data {
  uint8_t fmt;
  uint8_t num_patterns;
  uint16_t patterns_offset[3];
  uint8_t num_channels;
  uint8_t start_patterns[4];
  uint8_t pattern0[sizeof((uint8_t[])pattern0_data)];
  uint8_t pattern1[sizeof((uint8_t[])pattern1_data)];
  uint8_t pattern2[sizeof((uint8_t[])pattern2_data)];
} score = {
  .fmt = ATM_SCORE_FMT_FULL,
  .num_patterns = 3,
  .patterns_offset = {
      offsetof(struct score_data, pattern0),
      offsetof(struct score_data, pattern1),
      offsetof(struct score_data, pattern2),
  },
  .num_channels = 4,
  .start_patterns = { 0x00, 0x02, 0x02, 0x02 },
  .pattern0 = pattern0_data,
  .pattern1 = pattern1_data,
  .pattern2 = pattern2_data,
};

#endif
