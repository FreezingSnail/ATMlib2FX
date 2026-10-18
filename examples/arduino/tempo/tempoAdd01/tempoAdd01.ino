#include <Arduino.h>
#include <Arduboy2.h>
#include <ATMlib.h>
#include "bitmaps.h"
#include "song.h"


Arduboy2Base arduboy;
Sprites sprites;
ATMsynth ATM;

// Sketch-side runtime tempo change (ATMlib2FX-y1w): no score command needed.
// Press UP/DOWN to cycle the music tick rate in Hz via atm_synth_set_tempo().
// Rates below 8 are outside the osc timer's supported range; keep to 8..255.
static const uint8_t kTempos[] = { 25, 50, 100, 150, 200, 255 };
static uint8_t tempo_idx = 0;

void setup() {
  arduboy.begin();
  // set the framerate of the game at 60 fps
  arduboy.setFrameRate(60);
  // let's make sure the sound was not muted in a previous sketch
  arduboy.audio.on();
  // Initializes ATMSynth and samplerate
  // Begin playback of song.
  ATM.play(music);
}

void loop() {

  if (!(arduboy.nextFrame())) return;
  arduboy.pollButtons();
  arduboy.clear();
  sprites.drawSelfMasked(34, 4, T_arg, 0);
  if (arduboy.justPressed(B_BUTTON)) ATM.playPause();
  if (arduboy.justPressed(A_BUTTON)) ATM.playPause();
  // Sketch-side tempo change while the score plays (or is paused).
  if (arduboy.justPressed(UP_BUTTON)) {
    tempo_idx = (uint8_t)((tempo_idx + 1) % (sizeof(kTempos) / sizeof(kTempos[0])));
    atm_synth_set_tempo(kTempos[tempo_idx]);
  }
  if (arduboy.justPressed(DOWN_BUTTON)) {
    tempo_idx = (uint8_t)((tempo_idx + sizeof(kTempos) / sizeof(kTempos[0]) - 1) %
                          (sizeof(kTempos) / sizeof(kTempos[0])));
    atm_synth_set_tempo(kTempos[tempo_idx]);
  }
  arduboy.display();
  // test
}
