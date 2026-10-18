/*
 * sync/song.h - ATMlib2FX-hlh.8 loop fixture: all-stopped loop
 * synchronization.
 *
 * Two channels loop on different periods (4 and 6 ticks). After the intro the
 * original engine only restarts a channel when *every* channel has stopped, so
 * the channels re-synchronize at the common all-stopped tick and then run an
 * immediate same-tick second pass (the restart). This fixture is converted by
 * tests/fx_pack and research/fx/fx_compact_spike/loops/run-loops.sh and traced
 * by the unmodified engine.
 */
#ifndef SONG_H
#define SONG_H

#include "atm_cmd_constants.h"

/* ch0 entry: intro note, then loop target pattern 4 every time all stop. */
#define pattern0_data { \
    ATM_CMD_M_SET_VOLUME(100), \
    ATM_CMD_M_SET_LOOP_PATTERN(4), \
    ATM_CMD_M_NOTE(10), \
    ATM_CMD_M_DELAY_TICKS(4), \
    ATM_CMD_I_STOP, \
}
/* ch1 entry: intro note, then loop target pattern 5. */
#define pattern1_data { \
    ATM_CMD_M_SET_LOOP_PATTERN(5), \
    ATM_CMD_M_NOTE(20), \
    ATM_CMD_M_DELAY_TICKS(6), \
    ATM_CMD_I_STOP, \
}
/* ch2/ch3: stop immediately, no loop (must stay stopped while ch0/ch1 loop). */
#define pattern2_data { ATM_CMD_I_STOP, }
#define pattern3_data { ATM_CMD_I_STOP, }
/* ch0 loop pattern: period 4. */
#define pattern4_data { \
    ATM_CMD_M_NOTE(11), \
    ATM_CMD_M_DELAY_TICKS(4), \
    ATM_CMD_I_STOP, \
}
/* ch1 loop pattern: period 6. */
#define pattern5_data { \
    ATM_CMD_M_NOTE(21), \
    ATM_CMD_M_DELAY_TICKS(6), \
    ATM_CMD_I_STOP, \
}

const PROGMEM struct score_data {
  uint8_t fmt;
  uint8_t num_patterns;
  uint16_t patterns_offset[6];
  uint8_t num_channels;
  uint8_t start_patterns[4];
  uint8_t pattern0[sizeof((uint8_t[])pattern0_data)];
  uint8_t pattern1[sizeof((uint8_t[])pattern1_data)];
  uint8_t pattern2[sizeof((uint8_t[])pattern2_data)];
  uint8_t pattern3[sizeof((uint8_t[])pattern3_data)];
  uint8_t pattern4[sizeof((uint8_t[])pattern4_data)];
  uint8_t pattern5[sizeof((uint8_t[])pattern5_data)];
} score = {
  .fmt = ATM_SCORE_FMT_FULL,
  .num_patterns = 6,
  .patterns_offset = {
      offsetof(struct score_data, pattern0),
      offsetof(struct score_data, pattern1),
      offsetof(struct score_data, pattern2),
      offsetof(struct score_data, pattern3),
      offsetof(struct score_data, pattern4),
      offsetof(struct score_data, pattern5),
  },
  .num_channels = 4,
  .start_patterns = { 0x00, 0x01, 0x02, 0x03 },
  .pattern0 = pattern0_data,
  .pattern1 = pattern1_data,
  .pattern2 = pattern2_data,
  .pattern3 = pattern3_data,
  .pattern4 = pattern4_data,
  .pattern5 = pattern5_data,
};

#endif
