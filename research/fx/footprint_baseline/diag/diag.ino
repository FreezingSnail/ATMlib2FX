/*
 * Diagnostic-only emulator fixture for ATMlib2FX-hlh.1.
 *
 * This is NOT a production-size build. It exists to obtain device/emulator
 * evidence that the footprint build lane cannot produce:
 *
 *   - real stack high-water for the music+SFX shell, measured by painting free
 *     SRAM before the audio timer is armed and scanning it after a fixed number
 *     of frames, and
 *   - a small live oscillator/tempo/active-channel snapshot read from the
 *     library's exposed globals.
 *
 * It is run under Ardens headless serial capture:
 *   Ardens --captureserial=<ms> build/fx-port/diag/footprint_diag.ino.hex
 *
 * The reporting code and Serial use are diagnostic; the painted-stack numbers
 * are taken before any reporting runs, but the build will not match the
 * production image byte-for-byte and must not be used for flash/SRAM size.
 */

#include <Arduino.h>
#include <Arduboy2.h>
#include <ATMlib.h>
#include "song.h"
#include "bitmaps.h"

extern "C" uint8_t __bss_end;

Arduboy2Base arduboy;
Sprites sprites;
struct atm_sfx_state sfx_state;

#ifndef DIAG_FRAMES
#define DIAG_FRAMES 220
#endif

static uint8_t *g_stack_lo;
static uint16_t g_stack_hi;
static uint32_t g_frame;
static bool g_sfx_started;

static uint16_t get_sp(void)
{
  uint16_t v;
  asm volatile("in %A0, __SP_L__\n\tin %B0, __SP_H__" : "=r"(v));
  return v;
}

/* Paint free SRAM from the end of .bss up to the current stack pointer. Must
   run while the audio timer interrupt is still disarmed. */
static void paint_stack(void)
{
  g_stack_lo = &__bss_end;
  g_stack_hi = get_sp();
  for (uint8_t *p = g_stack_lo; p < (uint8_t *)g_stack_hi; p++) {
    *p = 0x5A;
  }
}

static void report_and_halt(void)
{
  atm_synth_stop_score();

  uint8_t *p = g_stack_lo;
  while (p < (uint8_t *)g_stack_hi && *p == 0x5A) {
    p++;
  }

  Serial.println(F("----- ATMlib2FX diag -----"));
  Serial.print(F("frames=")); Serial.println(g_frame);
  Serial.print(F("bss_end=0x")); Serial.println((uint16_t)g_stack_lo, HEX);
  Serial.print(F("sp_hi=0x")); Serial.println(g_stack_hi, HEX);
  Serial.print(F("deepest_sp=0x")); Serial.println((uint16_t)p, HEX);
  Serial.print(F("headroom_bytes="));
  Serial.println((uint16_t)((uint16_t)p - (uint16_t)g_stack_lo), DEC);
  Serial.print(F("static_sram_used_bytes="));
  Serial.println((uint16_t)((uint16_t)g_stack_lo - 0x0100), DEC);
  Serial.print(F("tempo=")); Serial.println((unsigned)atmlib_state.tick_rate, DEC);
  Serial.print(F("active_mute=0x")); Serial.println((unsigned)atmlib_state.channel_active_mute, HEX);
  for (uint8_t c = 0; c < OSC_CH_COUNT; c++) {
    Serial.print(F("osc")); Serial.print(c);
    Serial.print(F(" inc=0x")); Serial.print((unsigned)osc_params_array[c].phase_increment, HEX);
    Serial.print(F(" mod=")); Serial.print((unsigned)osc_params_array[c].mod, DEC);
    Serial.print(F(" vol=")); Serial.println((unsigned)osc_params_array[c].vol, DEC);
  }
  Serial.println(F("----- DONE -----"));
  Serial.flush();
  while (1) {}
}

void setup() {
  arduboy.begin();
  Serial.begin(115200);
  Serial.print(F("BOOT\n"));
  arduboy.setFrameRate(15);
  arduboy.audio.on();
#ifndef DIAG_NO_AUDIO
  atm_synth_setup();
#endif
#ifndef DIAG_NO_PAINT
  paint_stack();
#endif
#ifndef DIAG_NO_AUDIO
  atm_synth_play_score((const uint8_t*)&score);
#endif
}

void loop() {
  if (!(arduboy.nextFrame()))
    return;

  arduboy.pollButtons();
  arduboy.clear();
  sprites.drawSelfMasked(34, 4, T_arg, 0);
  arduboy.display();

  if (!g_sfx_started && g_frame == 30) {
    atm_synth_play_sfx_track(OSC_CH_TWO, (const uint8_t*)&sfx1, &sfx_state);
    g_sfx_started = true;
  }

  g_frame++;
  if (g_frame >= DIAG_FRAMES) {
    report_and_halt();
  }
}
