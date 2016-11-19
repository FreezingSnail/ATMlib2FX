#ifndef SONG_H
#define SONG_H

#define Song const uint8_t PROGMEM

Song music[] = {                // total song in bytes = 27 
                                // setup bytes 11
  0x04,                         // Number of tracks
  0x00, 0x00,                   // Address of track 0
  0x03, 0x00,                   // Address of track 1
  0x09, 0x00,                   // Address of track 2
  0x13, 0x00,                   // Address of track 3
  0x00,                         // Channel 0 entry track (PULSE)
  0x01,                         // Channel 1 entry track (SQUARE)
  0x00,                         // Channel 2 entry track (TRIANGLE)
  0x00,                         // Channel 3 entry track (NOISE)

  //"Track 0"                   // ticks = 0, bytes = 3
  0x40, 0,                      // FX: SET VOLUME: volume = 0
  0xFE,                         // RETURN (empty track used for silent channels)

  //"Track 1"                   // ticks = 2048, bytes = 6
  0x40, 63,                     // FX: SET VOLUME: volume = 63
  0xFD, 32, 2,                  // REPEAT: count = 32 - track = 2  (32 * 64 ticks)
  0xFE,                         // RETURN

  //"Track 2"                   // ticks = 64, bytes = 7
  0x00 + 36,                    // NOTE ON: note = 36 (delay 1 tick)
  0x47, 0x43, 0x00 + 0x00 + 20, // FX: ARPEGGIO ON: notes =  +4 +3 / don't play third note = OFF / ritrigger = OFF / ticks = 20
  0x9F + 63,                    // DELAY: 63 ticks
  0x48,                         // FX: ARPEGGIO OFF
  0xFE,                         // RETURN

};

#endif