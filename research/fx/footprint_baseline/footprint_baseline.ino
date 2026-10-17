/*
 * Footprint baseline fixture for ATMlib2FX footprint research (ATMlib2FX-hlh.1).
 *
 * One identical sketch shell, selected at compile time by -DFP_AUDIO=<n> so
 * that every variant shares the same display/loop code and differs only in the
 * audio backend that is linked in.
 *
 *   FP_AUDIO=0  shell only, no audio library linked        (baseline)
 *   FP_AUDIO=1  original PROGMEM music (song01_sfx score)  (music)
 *   FP_AUDIO=2  original PROGMEM music + PROGMEM SFX       (music+sfx)
 *   FP_AUDIO=3  ArduboyFX linked and initialized, no music (fx-control)
 *
 * Input asset: examples/arduino/songs/song01_sfx/song.h, used unchanged. The shell is
 * deliberately the same as the song01_sfx example (Arduboy2Base + Sprites +
 * the T_arg bitmap) so measurements are relative, not absolute product sizes.
 *
 * The song/bitmap include directory is supplied by the measurement script with
 * -Iexamples/arduino/songs/song01_sfx, because arduino-cli preprocesses the .ino into
 * the build directory and relative includes would otherwise resolve there.
 *
 * FP_DIAG_ONLY is used only by the separate diagnostic builds and must never be
 * set for production-size measurement builds.
 *
 * This file is a measurement fixture. It is not shipped code and does not
 * change any library behavior.
 */

#include <Arduino.h>
#include <Arduboy2.h>

#include "bitmaps.h"

#ifndef FP_AUDIO
#define FP_AUDIO 0
#endif

#ifndef FP_FRAMERATE
#define FP_FRAMERATE 15
#endif

/* Frame at which the single SFX is started in FP_AUDIO=2 (deterministic). */
#ifndef FP_SFX_FRAME
#define FP_SFX_FRAME 30
#endif

#if FP_AUDIO == 1 || FP_AUDIO == 2
#include <ATMlib.h>
#include "song.h"
#elif FP_AUDIO == 3
#include <ArduboyFX.h>
#elif FP_AUDIO != 0
#error "FP_AUDIO must be 0, 1, 2 or 3"
#endif

Arduboy2Base arduboy;
Sprites sprites;

#if FP_AUDIO == 2
struct atm_sfx_state sfx_state;
static bool sfx_started = false;
#endif

void setup() {
  arduboy.begin();
  arduboy.setFrameRate(FP_FRAMERATE);
  /* make sure the sound was not muted in a previous sketch */
  arduboy.audio.on();

#if FP_AUDIO == 1 || FP_AUDIO == 2
  atm_synth_setup();
  atm_synth_play_score((const uint8_t*)&score);
#elif FP_AUDIO == 3
  FX::begin();
#endif
}

void loop() {
  if (!(arduboy.nextFrame()))
    return;

  arduboy.pollButtons();
  arduboy.clear();
  sprites.drawSelfMasked(34, 4, T_arg, 0);

#if FP_AUDIO == 2
  if (!sfx_started && arduboy.frameCount == FP_SFX_FRAME) {
    atm_synth_play_sfx_track(OSC_CH_TWO, (const uint8_t*)&sfx1, &sfx_state);
    sfx_started = true;
  }
#endif

  arduboy.display();
}
