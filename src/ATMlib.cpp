
#include "ATMlib.h"
#include <ArduboyFX.h>

void ATMsynth::setup(void) {
    if (!setup_done) {
        atm_synth_setup();
        uint8_t *channelPointers[4] = {
            channelBuffers[0].synthBuffer,
            channelBuffers[0].synthBuffer,
            channelBuffers[0].synthBuffer,
            channelBuffers[0].synthBuffer,
        };
        link_channels(channelPointers);
        setup_done = true;
    }
}

void ATMsynth::play(const uint8_t *score) {
    setup();
    atm_synth_play_score(score);
}

// Stop playing, unload melody
void ATMsynth::stop() {
    atm_synth_stop_score();
}

// Start grinding samples or Pause playback
void ATMsynth::playPause() {
    atm_synth_set_score_paused(!atm_synth_get_score_paused());
}

void ATMsynth::init(uint24_t songAddr, uint16_t songLength) {
    FX::seekData(songAddr);
    for (uint8_t i = 0; i < 4; i++) {
        uint24_t channelAddr = FX::readIndexedUInt24(songAddr, i);
        FX::seekData(channelAddr);
        for (uint8_t j = 0; j < ATM_BUFFER_LENGTH; j++) {
            channelBuffers[i].synthBuffer[j] = FX::readPendingUInt8();
        }
        (void)FX::readEnd();
    }
    writeIndex = ATM_BUFFER_LENGTH - 1;
}

void ATMsynth::update() {
    // prevent ISR interupts during buffer loading
    uint8_t sreg = SREG;
    cli();

    // update buffers
    uint8_t readerIndex = readerPos();
    for (uint8_t i = 0; i < 4; i++) {
        uint8_t chnlWriteIdx = writeIndex;
        // Seek to track data
        FX::seekData(channelPointer[i]);
        while (chnlWriteIdx != readerIndex) {
            channelBuffers[i].synthBuffer[chnlWriteIdx] = FX::readPendingUInt8();
            chnlWriteIdx = incrementWriteIndex(chnlWriteIdx);
            channelPointer[i]++;
        }
        (void)FX::readEnd();
    }
    // allow ISR to interupt
    SREG = sreg;
}
