/*
 * jukebox_fx - browse every catalog song streamed from the FX chip
 * (ATMlib2FX-hlh.14).
 *
 * The PROGMEM jukebox (examples/arduino/jukebox) cannot fit all twenty-one
 * catalog scores in one flash image (33,594 bytes of PROGMEM asset data alone
 * vs a 29,696-byte flash cap), so it ships two build-time sets. This sketch
 * keeps the same controls and display but stores **no** score bytes in
 * PROGMEM: every score lives in one FX data image and is streamed from the FX
 * section by the compact decoder, per the pinned integration contract
 * (docs/fx/integration.md):
 *
 *   - the caller owns FX::begin(FX_DATA_PAGE); the page and the per-song
 *     data-section-relative offset/length come from the generated index header;
 *   - atm_fx_compact_fetch reads data-section-relative offsets with
 *     FX::readDataBytes; the page is added exactly once by the FX library;
 *   - atm_fx_compact_service() runs in the main loop after FX::display(), with
 *     sample interrupts enabled.
 *
 * The generated header (examples/arduino/jukebox_fx/jukebox_fx_songs.h) is
 * committed and regenerated with tools/music_authoring/fx_jukebox.py. It holds
 * the per-song stream offset/length plus the display name/folder table.
 *
 * Controls:
 *   UP / DOWN  previous / next song (wraps, plays immediately)
 *   A          restart the selected song
 *   B          pause / resume playback
 */

#include <Arduino.h>
#include <string.h>
#include <Arduboy2.h>
#include <ArduboyFX.h>

extern "C" {
#include <atm_synth.h>
#include <atm_fx_compact.h>
}

#include "jukebox_fx_songs.h"

#define COLS 21
#define LINE_HEIGHT 8

#ifndef FX_REPORT_FRAME
#define FX_REPORT_FRAME 520
#endif

/* Device-validation hook: start on a chosen catalog index so absim evidence can
 * cover any song without injected button input. Defaults to the first song. */
#ifndef JUKEBOX_FX_START_SONG
#define JUKEBOX_FX_START_SONG 0
#endif

Arduboy2 arduboy;

uint8_t selected_song = JUKEBOX_FX_START_SONG;
bool playback_started = false;
/* The framebuffer only changes when selection or playback status changes.
 * Redraw on demand instead of re-rendering all eight text lines every frame. */
static bool ui_dirty = true;

/* Platform byte source for the compact decoder: data-section-relative offsets
 * are handed to the FX library, which adds the data page exactly once. Called
 * only from the foreground service, never from the timer. */
extern "C" void atm_fx_compact_fetch(uint32_t offset, uint8_t *dst, uint8_t n)
{
	FX::readDataBytes((uint24_t)offset, dst, n);
}

/* PROGMEM index/display accessors (the table is page-major PROGMEM data). */
static uint32_t song_offset(uint8_t i)
{
	return pgm_read_dword(&jukebox_fx_songs[i].offset);
}
static uint32_t song_length(uint8_t i)
{
	return pgm_read_dword(&jukebox_fx_songs[i].length);
}
static uint16_t song_loop_tenths(uint8_t i)
{
	return pgm_read_word(&jukebox_fx_songs[i].loop_tenths);
}
static uint8_t song_loops(uint8_t i)
{
	return pgm_read_byte(&jukebox_fx_songs[i].loop);
}
static uint8_t song_stream_loops(uint8_t i)
{
	return pgm_read_byte(&jukebox_fx_songs[i].stream_loop);
}
static const char *song_name(uint8_t i)
{
	return (const char *)pgm_read_ptr(&jukebox_fx_songs[i].name);
}
static const char *song_folder(uint8_t i)
{
	return (const char *)pgm_read_ptr(&jukebox_fx_songs[i].folder);
}

/* Copy a PROGMEM string into a NUL-terminated RAM buffer (tail truncated). */
static void copy_progmem(char *dest, const char *src, uint8_t max_len)
{
	uint8_t i = 0;
	while (i < max_len) {
		char c = (char)pgm_read_byte(src + i);
		if (c == '\0')
			break;
		dest[i] = c;
		i++;
	}
	dest[i] = '\0';
}

/* Greedy word wrap into at most two COLS-wide lines (tail truncation). */
static void wrap_text(const char *src, char *line1, char *line2)
{
	uint8_t len = strlen(src);
	if (len <= COLS) {
		strcpy(line1, src);
		line2[0] = '\0';
		return;
	}
	uint8_t split = 0;
	for (uint8_t i = 0; i < COLS && i < len; i++) {
		if (src[i] == ' ')
			split = i;
	}
	if (split == 0) {
		strncpy(line1, src, COLS);
		line1[COLS] = '\0';
		strncpy(line2, src + COLS, COLS);
		line2[COLS] = '\0';
	} else {
		strncpy(line1, src, split);
		line1[split] = '\0';
		strncpy(line2, src + split + 1, COLS);
		line2[COLS] = '\0';
	}
}

static void play_selected()
{
	atm_fx_compact_play(song_offset(selected_song), song_length(selected_song));
	playback_started = true;
}

#if ATM_FX_COMPACT_DIAG
/* One-shot device report (build with -DATM_FX_COMPACT_DIAG=1). */
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
	Serial.println(arduboy.frameCount);
}
#endif

static void draw_ui()
{
	char full[48];
	char line1[COLS + 1];
	char line2[COLS + 1];
	char folder_line[COLS + 1];
	char info[COLS + 1];
	char header[COLS + 1];

	copy_progmem(full, song_name(selected_song), sizeof(full) - 1);
	wrap_text(full, line1, line2);
	copy_progmem(folder_line, song_folder(selected_song), COLS);

	snprintf(header, sizeof(header), "JUKEBOX   %u/%u",
	         (unsigned)(selected_song + 1), (unsigned)JUKEBOX_FX_SONG_COUNT);

	uint16_t loop_tenths = song_loop_tenths(selected_song);
	snprintf(info, sizeof(info), "  %u.%us %uB",
	         (unsigned)(loop_tenths / 10), (unsigned)(loop_tenths % 10),
	         (unsigned)song_length(selected_song));

	const char *status;
	if (!playback_started) {
		status = "READY";
	} else if (atm_fx_compact_is_paused()) {
		status = "PAUSED";
	} else {
		status = "PLAYING";
	}

	arduboy.clear();
	arduboy.setCursor(0, 0 * LINE_HEIGHT);
	arduboy.print(header);
	arduboy.setCursor(0, 1 * LINE_HEIGHT);
	arduboy.print(line1);
	arduboy.setCursor(0, 2 * LINE_HEIGHT);
	arduboy.print(line2);
	arduboy.setCursor(0, 3 * LINE_HEIGHT);
	arduboy.print(folder_line);
	arduboy.setCursor(0, 4 * LINE_HEIGHT);
	arduboy.print(info);
	arduboy.setCursor(0, 5 * LINE_HEIGHT);
	arduboy.print(status);
	arduboy.setCursor(0, 6 * LINE_HEIGHT);
	arduboy.print("UP/DOWN SONG");
	arduboy.setCursor(0, 7 * LINE_HEIGHT);
	arduboy.print("A PLAY  B PAUSE");
}

void setup()
{
	arduboy.begin();
	/* Same frame pacing as the PROGMEM jukebox; the compact service runs once
	 * per frame, comfortably inside the pinned refill deadline. */
	arduboy.setFrameRate(60);
	arduboy.audio.on();

	FX::begin(JUKEBOX_FX_DATA_PAGE); /* caller owns the data page lifecycle */

	atm_synth_setup();
	play_selected();
}

void loop()
{
	if (!arduboy.nextFrame())
		return;
	arduboy.pollButtons();

	if (arduboy.justPressed(UP_BUTTON)) {
		selected_song = selected_song == 0 ? JUKEBOX_FX_SONG_COUNT - 1
		                                   : selected_song - 1;
		play_selected();
		ui_dirty = true;
	}
	if (arduboy.justPressed(DOWN_BUTTON)) {
		selected_song = (selected_song + 1) % JUKEBOX_FX_SONG_COUNT;
		play_selected();
		ui_dirty = true;
	}
	if (arduboy.justPressed(A_BUTTON)) {
		play_selected();
		ui_dirty = true;
	}
	if (arduboy.justPressed(B_BUTTON)) {
		if (atm_fx_compact_is_active()) {
			if (atm_fx_compact_is_paused()) {
				atm_fx_compact_resume();
			} else {
				atm_fx_compact_pause();
			}
		}
		ui_dirty = true;
	}

	/* A catalog song loops. When its whole loop region does not fit the FX
	 * ring the adapter exports the finite arrangement once, so re-arm it at
	 * the natural end; internally-looping 0xC1 streams never stop here. */
	if (playback_started && song_loops(selected_song) &&
	    !song_stream_loops(selected_song) && !atm_fx_compact_is_active()) {
		play_selected();
		ui_dirty = true;
	}

	if (ui_dirty) {
		draw_ui();
		ui_dirty = false;
	}

	/* Finish the OLED/SPI transaction, then refill the music ring. */
	FX::display();
	atm_fx_compact_service();

#if ATM_FX_COMPACT_DIAG
	if (arduboy.frameCount == FX_REPORT_FRAME) {
		fx_report();
	}
#endif
}
