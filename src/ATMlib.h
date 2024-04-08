#ifndef _ATMLIB_H_
#define _ATMLIB_H_

#include <ArduboyFX.h>

extern "C" {
#include "atm_synth.h"
}

class ATMsynth {

  private:
    bool setup_done = false;
    struct buffer {
        uint8_t synthBuffer[ATM_BUFFER_LENGTH];
    } channelBuffers[4];

    uint8_t writeIndex;
    uint24_t channelPointer[4];

  public:
    ATMsynth(){};

    void setup(void);

    // Load and play specified song
    void play(const uint8_t *song);

    // Play or Pause playback
    void playPause();

    // Stop playback (unloads song)
    void stop();

    void muteChannel(uint8_t ch);

    void unMuteChannel(uint8_t ch);

    void init(uint24_t songAddr, uint16_t songLength);

    void update();
};

#endif
