/*
 * Compiled FX stream spike fixture (ATMlib2FX-aoe).
 *
 * One sketch shell selected at compile time by -DFS_MODE:
 *   FS_MODE=0  shell: Arduboy2 + T_arg sprite + display (no audio, no FX)
 *   FS_MODE=1  fx_gfx: ArduboyFX + FX bitmap read + FX::display (no audio)
 *   FS_MODE=2  fx_stream: fx_gfx + compiled stream decoder (production size)
 *   FS_MODE=3  fx_diag:  fx_stream + counters + one USB-CDC report
 *
 * FS_MODE=2/3 must be compiled with -DATM_HAS_FX_STREAM=1 (the library ABI
 * changes with it). The stream and the stress bitmap live in the external FX
 * image; see tools/build-fx-stream.sh. No game save integration, no SFX.
 *
 * Frame cadence is 52 fps like the reference game. The foreground calls
 * atm_fx_stream_service() only after FX::display() has finished its bus
 * transaction; the Timer3 consumer never touches SPI.
 */
#include <Arduino.h>
#include <Arduboy2.h>

#include "bitmaps.h"

#ifndef FS_MODE
#define FS_MODE 2
#endif

#ifndef FS_FRAMERATE
#define FS_FRAMERATE 52
#endif

/* Report frame for FS_MODE=3 (about 10 s at 52 fps). */
#ifndef FS_REPORT_FRAME
#define FS_REPORT_FRAME 520
#endif

#if FS_MODE >= 1
#include <ArduboyFX.h>
#endif

#if FS_MODE >= 2
extern "C" {
#include <atm_synth.h>
#include <atm_fx_stream.h>
}
#endif

Arduboy2Base arduboy;
Sprites sprites;

#if FS_MODE >= 1
#ifndef FS_FX_DATA_PAGE
#error "FS_FX_DATA_PAGE must be defined for FX modes"
#endif
#ifndef FS_BITMAP_OFFSET
#error "FS_BITMAP_OFFSET must be defined"
#endif

static const uint24_t kBitmapOffset = FS_BITMAP_OFFSET;

#if FS_MODE >= 2
#ifndef FS_STREAM_OFFSET
#error "FS_STREAM_OFFSET must be defined"
#endif
#ifndef FS_STREAM_LEN
#error "FS_STREAM_LEN must be defined"
#endif
static const uint24_t kStreamOffset = FS_STREAM_OFFSET;
static const uint32_t kStreamLen = FS_STREAM_LEN;

extern "C" void atm_fx_stream_fetch(uint32_t offset, uint8_t *dst, uint8_t n)
{
  FX::readDataBytes(offset, dst, n);
}
#endif
#endif /* FS_MODE >= 1 */

void setup()
{
  arduboy.begin();
  arduboy.setFrameRate(FS_FRAMERATE);
  arduboy.audio.on();

#if FS_MODE >= 1
  FX::begin(FS_FX_DATA_PAGE);
#endif

#if FS_MODE >= 2
  atm_synth_setup();
  atm_fx_stream_play(kStreamOffset, kStreamLen);
#endif
}

#if FS_MODE == 3
static void fs_report()
{
  Serial.print(F("FSDIAG ticks="));
  Serial.print(atm_fx_stream_state.ticks);
  Serial.print(F(" underruns="));
  Serial.print(atm_fx_stream_state.underruns);
  Serial.print(F(" max_gap="));
  Serial.print(atm_fx_stream_state.max_gap);
  Serial.print(F(" overflow="));
  Serial.print(atm_fx_stream_state.overflow);
  Serial.print(F(" serviced="));
  Serial.print(atm_fx_stream_state.serviced);
  Serial.print(F(" frames="));
  Serial.print(arduboy.frameCount);
  Serial.println();
}
#endif

void loop()
{
  if (!arduboy.nextFrame())
    return;

#if FS_MODE == 0
  arduboy.pollButtons();
  arduboy.clear();
  sprites.drawSelfMasked(34, 4, T_arg, 0);
  arduboy.display();
#else
  FX::drawBitmap(8, 16, kBitmapOffset, 0, dbmNormal);
  FX::display(CLEAR_BUFFER);
#if FS_MODE >= 2
  /* foreground refill: only after the display transaction has ended */
  atm_fx_stream_service();
#endif
#endif

#if FS_MODE == 3
  if (arduboy.frameCount == FS_REPORT_FRAME) {
    fs_report();
  }
#endif
}
