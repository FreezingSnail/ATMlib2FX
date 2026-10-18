/*
 * music_graphics - FX music + graphics service + refill example
 * (ATMlib2FX-hlh.10).
 *
 * Demonstrates the pinned finite-v1 integration contract
 * (research/fx/fx-architecture-decision.md, "hlh.6 review"):
 *
 *   - the caller owns FX::begin(page) and the data page. The page and the
 *     data-section-relative stream offset/length come from the fx_image packer
 *     as compile-time constants;
 *   - the library service runs in the main loop AFTER FX::display(), between
 *     complete SPI transactions, with sample interrupts enabled;
 *   - the refill deadline is at least one complete record per frame
 *     (52 fps is ~19.23 ms);
 *   - finite songs only. Global loops are NOT available yet (owned by
 *     ATMlib2FX-hlh.8); this sketch never loops the stream.
 *
 * Build inputs (see README.md): convert the score with tools/fx_pack, pack it
 * with tools/fx_image, then build with -DFX_IMAGE_USE_HEADER and
 * -I<lane> so the generated fxdata_config.h supplies:
 *
 *   FX_DATA_PAGE FX_BITMAP_OFFSET FX_BITMAP_WIDTH FX_BITMAP_HEIGHT
 *   FX_STREAM_OFFSET FX_STREAM_LEN
 *
 * The library backend must be enabled with -DATM_HAS_FX_COMPACT=1; the optional
 * -DATM_FX_COMPACT_DIAG=1 adds the one-shot serial report used by the device
 * check. The default PROGMEM library build is untouched by any of this.
 */
#include <Arduino.h>
#include <Arduboy2.h>
#include <ArduboyFX.h>

extern "C" {
#include <atm_synth.h>
#include <atm_fx_compact.h>
}

#ifdef FX_IMAGE_USE_HEADER
#include "fxdata_config.h"
#endif

#ifndef FX_DATA_PAGE
#error "FX_DATA_PAGE must be defined (build with -DFX_IMAGE_USE_HEADER -I<lane>)"
#endif
#ifndef FX_BITMAP_OFFSET
#error "FX_BITMAP_OFFSET must be defined"
#endif
#ifndef FX_STREAM_LEN
#error "FX_STREAM_LEN must be defined"
#endif
#ifndef FX_STREAM_OFFSET
#define FX_STREAM_OFFSET 0
#endif
#ifndef FX_BITMAP_WIDTH
#define FX_BITMAP_WIDTH 32
#endif
#ifndef FX_BITMAP_HEIGHT
#define FX_BITMAP_HEIGHT 16
#endif

#ifndef FX_FRAMERATE
#define FX_FRAMERATE 52
#endif
#ifndef FX_REPORT_FRAME
#define FX_REPORT_FRAME 520
#endif

static const uint24_t kBitmapOffset = FX_BITMAP_OFFSET;
static const int16_t kBitmapX = (int16_t)((WIDTH - FX_BITMAP_WIDTH) / 2);
static const int16_t kBitmapY = (int16_t)((HEIGHT - FX_BITMAP_HEIGHT) / 2);

Arduboy2Base arduboy;

/* Platform byte source for the compact decoder: data-section-relative offsets
 * are handed to the FX library, which adds the data page exactly once. The
 * library calls this only from the foreground service, never from the timer. */
extern "C" void atm_fx_compact_fetch(uint32_t offset, uint8_t *dst, uint8_t n)
{
	FX::readDataBytes(offset, dst, n);
}

void setup()
{
	arduboy.begin();
	arduboy.setFrameRate(FX_FRAMERATE);
	arduboy.audio.on();          /* sample interrupts stay enabled during service */

	FX::begin(FX_DATA_PAGE);     /* caller owns the data page lifecycle */

	atm_synth_setup();
	atm_fx_compact_play(FX_STREAM_OFFSET, FX_STREAM_LEN);
}

#if ATM_FX_COMPACT_DIAG
static void fx_report()
{
	Serial.print(F("FXDIAG ticks="));
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
#endif

void loop()
{
	if (!arduboy.nextFrame())
		return;

	/* Frame work: FX bitmap graphics. The service must come after display so
	 * no SPI transaction overlaps the OLED update. */
	FX::drawBitmap(kBitmapX, kBitmapY, kBitmapOffset, 0, dbmNormal);
	FX::display(CLEAR_BUFFER);

	/* Refill: read at least one complete record per frame while the stream
	 * lasts. Safe (and required) with sample interrupts enabled. */
	atm_fx_compact_service();

#if ATM_FX_COMPACT_DIAG
	if (arduboy.frameCount == FX_REPORT_FRAME) {
		fx_report();
	}
#endif
}
