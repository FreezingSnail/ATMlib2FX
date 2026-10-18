/* Arduboy jukebox: browse and play the authored example songs (ATMlib2FX-dch).
 *
 * One Arduboy FX image cannot hold all twenty catalog scores (30,396 bytes of
 * PROGMEM asset data alone vs a 29,696-byte flash cap), so the sketch is built
 * against one generated set at a time and selected with JUKEBOX_SET:
 *
 *   1 (default) -> "songs_gatherer.h"  (Creature Gatherer + Authoring Examples)
 *   2           -> "songs_frontiers.h" (Creature Frontiers)
 *
 * Regenerate the committed headers with:
 *   python3 tools/music_authoring/jukebox.py --set gatherer \
 *       --out examples/arduino/jukebox/songs_gatherer.h
 *   python3 tools/music_authoring/jukebox.py --set frontiers \
 *       --out examples/arduino/jukebox/songs_frontiers.h
 *
 * Controls:
 *   UP / DOWN  previous / next song (wraps, plays immediately)
 *   A          restart the selected song
 *   B          pause / resume playback
 */

#include <Arduino.h>
#include <string.h>
#include <Arduboy2.h>
#include <ATMlib.h>

#ifndef JUKEBOX_SET
#define JUKEBOX_SET 1
#endif

#if JUKEBOX_SET == 1
#include "songs_gatherer.h"
#elif JUKEBOX_SET == 2
#include "songs_frontiers.h"
#else
#error "JUKEBOX_SET must be 1 (gatherer) or 2 (frontiers)"
#endif

#define COLS 21
#define LINE_HEIGHT 8

Arduboy2 arduboy;
ATMsynth ATM;

uint8_t selected_song = 0;
bool playback_started = false;

/* Copy a PROGMEM string into a NUL-terminated RAM buffer (tail truncated). */
static void copy_progmem(char *dest, const char *src, uint8_t max_len) {
  uint8_t i = 0;
  while (i < max_len) {
    char c = (char)pgm_read_byte(src + i);
    if (c == '\0') break;
    dest[i] = c;
    i++;
  }
  dest[i] = '\0';
}

/* Greedy word wrap into at most two COLS-wide lines (tail truncation). */
static void wrap_text(const char *src, char *line1, char *line2) {
  uint8_t len = strlen(src);
  if (len <= COLS) {
    strcpy(line1, src);
    line2[0] = '\0';
    return;
  }
  uint8_t split = 0;
  for (uint8_t i = 0; i < COLS && i < len; i++) {
    if (src[i] == ' ') split = i;
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

static void play_selected() {
  const uint8_t *score =
      (const uint8_t *)pgm_read_ptr(&jukebox_songs[selected_song].score);
  ATM.play(score);
  playback_started = true;
}

static void draw_ui() {
  const char *name =
      (const char *)pgm_read_ptr(&jukebox_songs[selected_song].name);
  const char *folder =
      (const char *)pgm_read_ptr(&jukebox_songs[selected_song].folder);
  uint16_t bytes = pgm_read_word(&jukebox_songs[selected_song].bytes);
  uint16_t loop_tenths = pgm_read_word(&jukebox_songs[selected_song].loop_tenths);

  char full[48];
  char line1[COLS + 1];
  char line2[COLS + 1];
  char folder_line[COLS + 1];
  char info[COLS + 1];
  char header[COLS + 1];

  copy_progmem(full, name, sizeof(full) - 1);
  wrap_text(full, line1, line2);
  copy_progmem(folder_line, folder, COLS);

  snprintf(header, sizeof(header), "JUKEBOX   %u/%u",
           (unsigned)(selected_song + 1), (unsigned)JUKEBOX_SONG_COUNT);
  snprintf(info, sizeof(info), "  %u.%us %uB", (unsigned)(loop_tenths / 10),
           (unsigned)(loop_tenths % 10), (unsigned)bytes);

  const char *status;
  if (!playback_started) {
    status = "READY";
  } else if (atm_synth_get_score_paused()) {
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
  arduboy.display();
}

void setup() {
  arduboy.begin();
  // set the framerate of the game at 60 fps
  arduboy.setFrameRate(60);
  // let's make sure the sound was not muted in a previous sketch
  arduboy.audio.on();
  // select song 0 and start playback
  play_selected();
}

void loop() {
  if (!(arduboy.nextFrame())) return;
  arduboy.pollButtons();

  if (arduboy.justPressed(UP_BUTTON)) {
    selected_song = selected_song == 0 ? JUKEBOX_SONG_COUNT - 1 : selected_song - 1;
    play_selected();
  }
  if (arduboy.justPressed(DOWN_BUTTON)) {
    selected_song = (selected_song + 1) % JUKEBOX_SONG_COUNT;
    play_selected();
  }
  if (arduboy.justPressed(A_BUTTON)) {
    play_selected();
  }
  if (arduboy.justPressed(B_BUTTON)) {
    ATM.playPause();
  }

  draw_ui();
}
