/*
 * Compact directly-consumed FX stream spike fixture (ATMlib2FX-hlh.5).
 *
 * One sketch shell selected at compile time by -DFC_MODE so every variant shares
 * the SAME FX graphics work (32x16 FX bitmap read + FX::display, 52 fps) and
 * differs only in the audio backend that is linked in:
 *
 *   FC_MODE=0  noaudio : ArduboyFX + FX bitmap read + FX::display (no audio)
 *   FC_MODE=1  music   : + original PROGMEM score (song01_sfx) via ATMlib
 *   FC_MODE=2  oldfx   : + retained 64-byte-ring FX stream (atm_fx_stream)
 *   FC_MODE=3  compact : + compact 32-byte-ring FX stream (atm_fx_compact)
 *   FC_MODE=4  compact_sfx : compact stream + independent-tempo PROGMEM SFX
 *                            overlay on a borrowed channel (ATMlib2FX-hlh.9)
 *
 * The backend diagnostic macro (ATM_FX_COMPACT_DIAG / ATM_FX_STREAM_DIAG) adds
 * counters and one USB-CDC report (diagnostic builds only). The stream, the
 * stress bitmap and the FX data page come from tools/build-fx-compact.sh; the
 * input score (examples/arduino/songs/song01_sfx) is used unchanged. Mode 4
 * additionally includes the generated PROGMEM SFX stream header and starts it
 * once at FC_SFX_FRAME.
 *
 * Frame cadence is 52 fps like the reference game. Foreground refill runs only
 * after FX::display() has finished its bus transaction; the Timer3 consumer
 * never touches SPI.
 */
#include <Arduino.h>
#include <Arduboy2.h>
#include <ArduboyFX.h>

#ifndef FC_MODE
#define FC_MODE 3
#endif
#ifndef FC_FRAMERATE
#define FC_FRAMERATE 52
#endif
/* Report frame for the diagnostic builds (about 10 s at 52 fps). */
#ifndef FC_REPORT_FRAME
#define FC_REPORT_FRAME 520
#endif

#if FC_MODE == 1
#include <ATMlib.h>
#include "song.h"
#elif FC_MODE == 2
extern "C" {
#include <atm_synth.h>
#include <atm_fx_stream.h>
}
#elif FC_MODE == 3
extern "C" {
#include <atm_synth.h>
#include <atm_fx_compact.h>
}
#elif FC_MODE == 4
extern "C" {
#include <atm_synth.h>
#include <atm_fx_compact.h>
}
#include "sfx_compact.h"
#elif FC_MODE != 0
#error "FC_MODE must be 0, 1, 2, 3 or 4"
#endif

#ifndef FC_FX_DATA_PAGE
#error "FC_FX_DATA_PAGE must be defined"
#endif
#ifndef FC_BITMAP_OFFSET
#error "FC_BITMAP_OFFSET must be defined"
#endif

static const uint24_t kBitmapOffset = FC_BITMAP_OFFSET;

#if FC_MODE == 2 || FC_MODE == 3 || FC_MODE == 4
#ifndef FC_STREAM_OFFSET
#error "FC_STREAM_OFFSET must be defined"
#endif
#ifndef FC_STREAM_LEN
#error "FC_STREAM_LEN must be defined"
#endif
static const uint24_t kStreamOffset = FC_STREAM_OFFSET;
static const uint32_t kStreamLen = FC_STREAM_LEN;
#endif

#if FC_MODE == 4
/* Frame at which the independent-tempo SFX overlay is started once. */
#ifndef FC_SFX_FRAME
#define FC_SFX_FRAME 60
#endif
static bool g_sfx_done = false;
#endif

#if FC_MODE == 2
extern "C" void atm_fx_stream_fetch(uint32_t offset, uint8_t *dst, uint8_t n)
{
  FX::readDataBytes(offset, dst, n);
}
#elif FC_MODE == 3 || FC_MODE == 4
extern "C" void atm_fx_compact_fetch(uint32_t offset, uint8_t *dst, uint8_t n)
{
  FX::readDataBytes(offset, dst, n);
}
#endif

Arduboy2Base arduboy;

void setup()
{
  arduboy.begin();
  arduboy.setFrameRate(FC_FRAMERATE);
  arduboy.audio.on();

  FX::begin(FC_FX_DATA_PAGE);

#if FC_MODE == 1
  atm_synth_setup();
  atm_synth_play_score((const uint8_t *)&score);
#elif FC_MODE == 2
  atm_synth_setup();
  atm_fx_stream_play(kStreamOffset, kStreamLen);
#elif FC_MODE == 3
  atm_synth_setup();
  atm_fx_compact_play(kStreamOffset, kStreamLen);
#elif FC_MODE == 4
  atm_synth_setup();
  atm_fx_compact_play(kStreamOffset, kStreamLen);
#endif
}

#if FC_MODE == 3 && ATM_FX_COMPACT_DIAG
static void fc_report()
{
  Serial.print(F("FCDIAG ticks="));
  Serial.print(atm_fx_compact_state.ticks);
  Serial.print(F(" underruns="));
  Serial.print(atm_fx_compact_state.underruns);
  Serial.print(F(" max_gap="));
  Serial.print(atm_fx_compact_state.max_service_gap);
  Serial.print(F(" max_record="));
  Serial.print(atm_fx_compact_state.max_record);
  Serial.print(F(" max_window="));
  Serial.print(atm_fx_compact_state.max_window);
  Serial.print(F(" error="));
  Serial.print(atm_fx_compact_state.error);
  Serial.print(F(" stop_tick="));
  Serial.print(atm_fx_compact_state.stop_tick);
  Serial.print(F(" serviced="));
  Serial.print(atm_fx_compact_state.serviced);
  Serial.print(F(" frames="));
  Serial.print(arduboy.frameCount);
  Serial.println();
}
#elif FC_MODE == 4 && ATM_FX_COMPACT_DIAG
static void fc_report()
{
  Serial.print(F("FCSFXDIAG borrow="));
  Serial.print(atm_fx_compact_state.sfx_borrow);
  Serial.print(F(" sfx_ticks="));
  Serial.print(atm_fx_compact_state.sfx_ticks);
  Serial.print(F(" restore_ok="));
  Serial.print(atm_fx_compact_state.sfx_restore_ok);
  Serial.print(F(" start="));
  Serial.print(atm_fx_compact_state.sfx_start_tick);
  Serial.print(F(" stop="));
  Serial.print(atm_fx_compact_state.sfx_stop_tick);
  Serial.print(F(" last_inc=0x"));
  Serial.print(atm_fx_compact_state.sfx_last_inc, HEX);
  Serial.print(F(" restore_inc=0x"));
  Serial.print(atm_fx_compact_state.sfx_restore_inc, HEX);
  Serial.print(F(" underruns="));
  Serial.print(atm_fx_compact_state.underruns);
  Serial.print(F(" error="));
  Serial.print(atm_fx_compact_state.error);
  Serial.print(F(" ticks="));
  Serial.print(atm_fx_compact_state.ticks);
  Serial.print(F(" frames="));
  Serial.print(arduboy.frameCount);
  Serial.println();
}
#elif FC_MODE == 2 && ATM_FX_STREAM_DIAG
static void fc_report()
{
  Serial.print(F("FCDIAG ticks="));
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

  FX::drawBitmap(8, 16, kBitmapOffset, 0, dbmNormal);
  FX::display(CLEAR_BUFFER);

#if FC_MODE == 2
  atm_fx_stream_service();
#elif FC_MODE == 3 || FC_MODE == 4
  atm_fx_compact_service();
#endif

#if FC_MODE == 4
  if (!g_sfx_done && arduboy.frameCount == FC_SFX_FRAME) {
    atm_fx_compact_play_sfx(SFX_COMPACT_CH, sfx_compact_stream, SFX_COMPACT_STREAM_LEN);
    g_sfx_done = true;
  }
#endif

#if FC_MODE == 2 && ATM_FX_STREAM_DIAG
  if (arduboy.frameCount == FC_REPORT_FRAME) {
    fc_report();
  }
#elif FC_MODE == 3 && ATM_FX_COMPACT_DIAG
  if (arduboy.frameCount == FC_REPORT_FRAME) {
    fc_report();
  }
#elif FC_MODE == 4 && ATM_FX_COMPACT_DIAG
  if (arduboy.frameCount == FC_REPORT_FRAME) {
    fc_report();
  }
#endif
}
