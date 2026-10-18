/*
 * extrapass/song.h - ATMlib2FX-hlh.8 loop fixture: immediate same-tick extra
 * effect pass with live effect state carried across.
 *
 * ch0 starts a volume slide that is never turned off, so the slide keeps
 * running across the loop boundary. At every all-stopped restart the original
 * engine runs a second pass in the same tick, advancing the slide once more
 * with the live effect state carried over. ch0 then loops on pattern 1.
 */
#ifndef SONG_H
#define SONG_H

#include "atm_cmd_constants.h"

/* ch0 entry: arm a fast volume slide, note, two delays (stop at tick 8). */
#define pattern0_data { \
    ATM_CMD_M_SET_VOLUME(100), \
    ATM_CMD_M_SET_LOOP_PATTERN(1), \
    ATM_CMD_M_SLIDE_VOL_ON(-3), \
    ATM_CMD_M_NOTE(10), \
    ATM_CMD_M_DELAY_TICKS(4), \
    ATM_CMD_M_DELAY_TICKS(4), \
    ATM_CMD_I_STOP, \
}
/* ch0 loop pattern: the slide keeps running; effect state is not reset. */
#define pattern1_data { \
    ATM_CMD_M_NOTE(11), \
    ATM_CMD_M_DELAY_TICKS(4), \
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
