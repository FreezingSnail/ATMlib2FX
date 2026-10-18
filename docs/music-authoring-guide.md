# Composing ATMlib music with `atm-music` — a model authoring guide

Status: implemented and exercised. Scope: this guide (`docs/music-authoring-guide.md`),
`examples/music_authoring/guide/`, and the authoring link in `README.md`. The
frontend design lives in [`docs/music-authoring-interface.md`](music-authoring-interface.md).

Everything below was re-run to produce the recorded numbers on this machine:
`atm-music` 1.0.0, engine ATMlib 1.2.4, Python 3.14.7 (stdlib only), `arduino-cli`
1.2.0. Re-run the commands to reproduce; the tool reports its own version in every
JSON payload.

This is a short, standalone guide for an LLM (or a person) composing library
music with the local host tools. It walks one real score
(`examples/music_authoring/showcase/song.json`) from capabilities → validate →
viewer → faithful WAV → explicit PROGMEM build → revise → re-view/re-render, and
records every command and artifact path. Run everything **from the repository
root**. Authoring runs on the host only; it adds nothing to `src/`.

The JSON score is the canonical input. You never hand-edit generated headers,
byte arrays or WAVs; you edit the score and re-run the tool. Everything this
guide writes goes under the git-ignored `build/music-authoring/guide/`, so your
own runs are safe and reproducible.

For a ready-to-open example, download or open the repository's
[standalone showcase viewer](../examples/music_authoring/showcase/review.html)
locally. It includes the matching WAV and Raw emulator / Piezo (approx.) sound
options; it does not depend on `build/` or a server. Its
[canonical review JSON](../examples/music_authoring/showcase/review.json) and
[regeneration instructions](../examples/music_authoring/showcase/README.md#open-in-the-offline-html-track-viewer)
live beside the song source.

To review and listen to **every** example song on one page, open
[`examples/music_authoring/player.html`](../examples/music_authoring/player.html):
a single offline library player with a song selector, Previous/Next, explicit game
context labels and the full per-song viewer (piano-roll/tracker, seek/restart,
Raw/Piezo) plus each song's embedded matching audio. It is generated from
[`examples/music_authoring/catalog.json`](../examples/music_authoring/catalog.json)
by [`tools/music_authoring/library_player.py`](../tools/music_authoring/library_player.py):

```
python3 tools/music_authoring/library_player.py \
    --catalog examples/music_authoring/catalog.json \
    --out examples/music_authoring/player.html --json
```

Each song's matching `preview.json` + `preview.wav` is maintained in its own
`examples/music_authoring/**/preview/` directory, beside `song.json`.

## 0. One-screen workflow

```
tools/atm-music capabilities --json
tools/atm-music validate SONG.json --backend progmem --json
tools/atm-music inspect  SONG.json --out OUT/review.html --json          # before export
tools/atm-music render   SONG.json --backend progmem --seconds 12 --out OUT/preview --json
tools/atm-music inspect  SONG.json --audio-preview OUT/preview --out OUT/review/review.html --json
tools/atm-music build    SONG.json --backend progmem --out OUT/build --json   # the only export
```

`inspect` and `render` never pack, write or flash FX data; `render` compiles an
instrumented AVR image only to capture audio, and `build` writes the persistent
PROGMEM asset. Editing the JSON and repeating validate → inspect → render is the
whole loop; `build` is the deliberate export you run when the review looks right.

## 1. Read capabilities first; mind the pinned report

`tools/atm-music capabilities --json` (stdout is always one JSON document; logs
go to stderr) reports features, channels, pitch range, host limits, backend
availability and tool/engine identity. Read it at the start of a session.

**Capability report matches real command support.** `capabilities --json`
advertises `inspect`, `render` and `wav_preview` as available, matching the
working commands, and advertises both backends: `progmem` and the compact FX
adapter for `build` (effects, commands, loops and streaming loops; SFX false). The ATMlib2FX-3ii.1 `expected/review.json` golden keeps a
byte-stable *embedded* capabilities block inside `review.json` for canonical-
event digest stability; the `inspect` and `render` subcommands report their own
truthful availability in their own payloads:

```
render  JSON: "capabilities": { "render": { "available": true }, "wav_preview": { "available": true }, ... }
inspect JSON: "capabilities": { "inspect": { "available": true }, "canonical_payload_capabilities_pinned": true, ... }
```

Rule for models: **do not** conclude a command is unavailable from a stale
embedded block. Run the command and read its own response. (`validate` and
`render` are `progmem`-only; `--backend fx` there exits `2` with
`BACKEND_UNAVAILABLE`.)

Relevant `capabilities --json` facts:

| Field | Value |
| --- | --- |
| `engine` | `ATMlib` 1.2.4, channels `pulse0`,`pulse1`,`pulse2`,`noise`, tick base 2000 Hz |
| `pitch_range` | `C2`..`D7` (note indices 1..63) |
| `backends` | `progmem` available; `fx` available for `build` with `loops` (`ATM_FX_COMPACT_LOOP=1`), `streaming_loops` (`--streaming-loops`, max 65535 B), `effects` and `commands` true, `sfx` false |
| host limits | 64 instruments, 256 patterns, 4096 source events, 4096 source effects, 4096 source commands, 65536 expanded notes, 1048576 ticks |
| `canonicalization` | `atmlib-canonical-events-v1` |

Exit codes everywhere: `0` success, `2` invalid score / unsupported capability,
`3` tool/build/render failure.

## 2. The instrument you are writing for

- **Four channels, fixed names and order:** `pulse0`, `pulse1`, `pulse2` (three
  square/pulse voices with programmable duty) and `noise` (one noise voice).
  Do not promise triangle, saw, samples or pitched percussion.
- **Each physical channel is monophonic.** One note sounds per channel at a time;
  v1 rejects overlapping gates even within a pattern. Polyphony means writing
  more channels, not stacked notes on one lane.
- **Pitches** are natural notes and sharps only (`C4`, `F#3`, `D7`), range
  **C2–D7**. No flats, MIDI numbers, chords, microtones or frequencies. An
  out-of-range pitch is rejected, never transposed or masked.
- **Noise pitch tokens are not melody.** On `noise`, the same pitch token selects
  the engine's noise frequency/seed control; `C3` and `C5` are two noise colors,
  not two pitched notes.
- **Instruments are host-side presets** (voice + volume + duty), not extra
  hardware voices. Pulse instruments need `voice`,`volume`,`duty`; noise
  instruments need `voice`,`volume` and reject `duty`.
- **Gates and rests.** An event `duration` is the audible gate length in ticks.
  Time not covered by an event is silent: empty regions of a pattern and the
  ticks after a gate are rests. Gaps never overlap. End-of-song mutes all
  channels explicitly.
- **Pattern reuse and song loops.** Tracks are arrays of `{pattern, repeat}`;
  pattern repetition is bounded (1–256) and expanded on the host. Add root
  `"loop": true` to repeat the entire song on the original PROGMEM engine.
  Shorter tracks wait silently for the longest track before restarting together.
  Omit it or use false for a finite cue. Tempo changes and live engine effects
  are available through the additive per-pattern `effects` and `commands` keys
  described in section 3.

The offline review's **Loop** checkbox repeats one complete musical cycle and
defaults on for looping scores. Playback removes measured AVR startup and the
capture tail, so neither repeats. Turn Loop off to stop at the cycle end. Pause,
Restart, seek and both sound profiles work on the same cycle. Incomplete
captures or captures without measured callback timing cannot enable Loop.

To change the actual pace, scale pattern lengths, event onsets and gate ends
along with `ticks_per_beat`. Changing that metadata alone only relabels the beat
grid; it does not move notes in time. The revised demo library uses exact 50 Hz
or 100 Hz clocks, with cue tempos ranging from about 68 to 188 BPM.

### Ticks vs effective BPM

`clock.tick_rate` is a **timer request in Hz**, not a stored tempo. The engine
quantizes it: `effective_tick_rate = 2000 / floor(2000 / tick_rate)`. Reported
tempo is derived, not stored: `effective_bpm = effective_tick_rate * 60 /
ticks_per_beat`. For `tick_rate=50, ticks_per_beat=25` the effective rate is
exactly 50 Hz and the reported tempo is `50*60/25 = 120.0` BPM. Requested rates
below 8 are unsupported; request 255 and you get exactly ≈285.714 Hz. Fine
musical timing is always counted in ticks.

Song length derives from the integer divider, not the rounded rate:
`seconds = total_ticks * floor(2000 / tick_rate) / 2000`. At `tick_rate=255`
(divider 7) 2000 ticks span exactly 7 s; the host never rounds the quotient.

## 3. Writing the score (the v1 JSON subset)

Allowed shape (reject anything else; unknown keys, duplicate keys, floats-in-integer
slots and bad versions all fail):

```json
{
  "format": "atmlib-score", "version": 1, "id": "my_song_v1",
  "clock": {"tick_rate": 50, "ticks_per_beat": 25, "beats_per_bar": 4},
  "instruments": {"lead": {"voice": "pulse", "volume": 80, "duty": 127}},
  "patterns": {"phrase": {"ticks": 50, "events": [
    {"at": 0, "note": "C4", "duration": 10, "instrument": "lead"}]}},
  "tracks": {"pulse0": [{"pattern": "phrase", "repeat": 2}]}
}
```

Rules that matter in practice: pattern `ticks` is a positive integer; an event's
`at` is within `[0, ticks)` and `at + duration <= ticks`; only one note per
timestamp in a pattern; at least one track; missing channels are silent. IDs and
references are case sensitive.

### Live effects and commands (additive v1)

Two **optional** pattern keys add engine effects and instantaneous commands.
They are absent from every earlier score, so old files validate and serialize
unchanged. A pattern is monophonic, so its effects act on that pattern's single
voice.

```json
{
  "patterns": {
    "arp_lead": {
      "ticks": 32,
      "events": [{"at": 0, "note": "C4", "duration": 16, "instrument": "lead"}],
      "effects": [
        {"at": 0, "type": "arpeggio", "offsets": [4, 7], "period": 2},
        {"at": 16, "type": "lfo", "mode": "tremolo", "depth": 24, "period": 8}
      ],
      "commands": [{"at": 0, "type": "set_tempo", "value": 50}]
    }
  }
}
```

Each effect window has `at` (start tick), `type`, an optional exclusive `until`
(default the pattern end; it must not cross the boundary), and the type's
operands. Kinds and the exact engine byte mapping are in
[`music-authoring-interface.md`](music-authoring-interface.md#effect-windows-and-live-commands);
in brief:

| Type | Operands | Effect |
| --- | --- | --- |
| `arpeggio` | `offsets` (1–2 values 0–14, absolute semitone intervals from the base note), `period` 1–32 ticks, optional `repeat` (default true) | cycles base → base+offsets[0] → base+offsets[1] every `period` ticks |
| `note_cut` | `period` 1–32 ticks, optional `repeat` | cuts the note after `period` ticks; `repeat` re-attacks it |
| `lfo` | `mode` `tremolo`/`vibrato`/`modulation`, `depth` 0–255, `period` even 2–64 | volume / `freq` / `mod` modulation |
| `slide` | `param` `volume`/`frequency`/`modulation`, `amount` -128..127, `every` 1–64 ticks | steps the parameter every `every` ticks |
| `glissando` | `period` 1–128, `direction` `up`/`down` | steps the note ±1 semitone every `period` ticks |
| `noise_retrig` | `period` 0–3, `note` (noise channel only) | retriggers noise every `period+1` ticks |

The engine has one slot each for arpeggio/note-cut (they share state), slide,
LFO, glissando and noise retrigger; windows in a slot must be ordered and
non-overlapping and the whole `effects` array sorted by `at`. `noise_retrig`
belongs only to a pattern whose events are noise; the other kinds only to pulse
patterns. `commands` are instantaneous and at most one per `(type, at)` with
`at` in `[0, ticks)`: `set_tempo`/`add_tempo`, `set_transposition`/
`add_transposition`, `set_volume`, `set_mod`, `cue`. Rejections use stable codes
and JSON Pointers: `UNKNOWN_EFFECT_TYPE`, `EFFECT_BOUNDS`, `EFFECT_ORDER`,
`EFFECT_OVERLAP`, `EFFECT_CHANNEL_MISMATCH`, `UNKNOWN_COMMAND_TYPE`,
`COMMAND_BOUNDS`, `COMMAND_ORDER`, `COMMAND_DUPLICATE`.

> These keys are validated by the CLI and emitted by the PROGMEM backend as
> engine effect/command bytes; `capabilities`, the canonical review payload and
> the viewer report and draw them. The compact FX adapter encodes the **same**
> command bytecode (`progmem_backend.encode_op`), so effect/command passages
> build on either backend; only FX SFX is out of scope.

### From a natural-language brief to concrete fields

A brief is a composition goal, not engine syntax. Map it like this:

| Brief phrase | Concrete field(s) |
| --- | --- |
| "120 BPM, 4/4" | `clock.tick_rate=50`, `ticks_per_beat=25`, `beats_per_bar=4` |
| "8 seconds long" | `total_ticks = seconds * effective_tick_rate` = `8*50 = 400` ticks |
| "melody on channel A" | `tracks.pulse0` and a `pulse` instrument (`lead`) |
| "root bass on beats 1 & 3" | a `bass` pattern with events `at` 0 and 50 (`ticks_per_beat*2`) |
| "restrained percussion" | a `noise` instrument with low `volume`, short gates |
| "repeat the 2nd bar, then a fill" | `{"pattern":"bar2","repeat":2}` then `{"pattern":"fill","repeat":1}` |
| "ends on the tonic with a short pause" | final event on the tonic; leave the last few ticks empty |

### Applying other ATMlib documentation to this port

The [T-arg ATMlib README](https://github.com/T-arg/ATMlib) describes related
tracker concepts, including note retriggering, arpeggios, slides, modulation and
note cuts. Translate these concepts using the local engine and authoring
contract. Its older byte-format tables are incompatible with ATMlib2FX's block
encoding; the local source remains authoritative.

| Musical technique | What works here |
| --- | --- |
| Sustained melody instead of stuttering | Set longer `duration` gates. Join an accidental same-pitch repetition into one event spanning the combined time. Every source event otherwise explicitly mutes at its gate end. |
| Arpeggiated harmony | Write sequential chord tones on a pulse track, or a hardware arpeggio via the pattern `effects` key: `{"at":0,"type":"arpeggio","offsets":[4,7],"period":2}` cycles the base through `+4` (third) then `+7` (fifth). Offsets are absolute semitone intervals from the base note. |
| Gentle articulation and balance | Keep the lead stronger than its supporting voices; use restrained noise and intentional rests. Pulse `duty` changes the tone, not the pitch. These are composition decisions, checked with the matching render. |
| Slides, vibrato and tremolo | Available as pattern `effects`: `slide` (volume/frequency/modulation, plain or stepped), `lfo` (`tremolo`/`vibrato`/`modulation`), and `glissando`. One slot each, so they cannot be freely combined on one channel; do not insert foreign opcode bytes into JSON. |
| Whole-song looping | Use root `"loop": true`. The compiler emits local `SET_LOOP_PATTERN` commands and synchronizes channel restart. |
| Tempo | Count event times in ticks using the local timer rate; old default/range recommendations are not the host clock contract. In-song changes use the `set_tempo`/`add_tempo` commands. |

For exact behavior, see `src/atm_cmd_constants.h`, `src/cmd_parse.c` and
`src/atm_synth.c`. For example, the local arpeggio processor adds each stored
nibble to the base note rather than chaining them, so the lowering stores the
second offset directly in the low nibble. The emitted engine stream is
`[ATM_CMD_P_ARPEGGIO_ON, arpTiming, notes]` — the public
`ATM_CMD_M_ARPEGGIO_ON(p1, p2)` macro expands `(p2), (p1)`, so the macro-
argument order `(notes, timing)` is the reverse of the stream order (see
[`music-authoring-interface.md`](music-authoring-interface.md#effect-windows-and-live-commands)).
Local pitch indices start at C2; importing old numeric
note values would change the music. Old combined-volume limits also require
checking against this port's mixer; they are not a replacement for local renders.

The Marsh/Tideline revision (ATMlib2FX-cfp) applies these ideas through the
existing JSON subset: a clear eight-bar E-minor phrase and quieter sustained
support for Marsh; joined repeated pitches and consistent 40 ms lead gaps for
Tideline. Both remain original compositions with matching AVR/absim previews.

### A complete finite example

`examples/music_authoring/guide/song.json` is a small, self-contained four-channel
piece (one 4/4 bar, 100 ticks; a 50-tick `melody` reused on `pulse0` and `pulse1`,
plus a `bassline` and a `kick`). Validate and build it:

```
tools/atm-music validate examples/music_authoring/guide/song.json --backend progmem --json
tools/atm-music build    examples/music_authoring/guide/song.json --backend progmem \
    --out build/music-authoring/guide/guide-build --json
```

Observed: `ok:true`, `total_ticks:100`, effective `120.0` BPM, `pattern_instances:8`,
`expanded_note_events:12`; `score.bin` = **127 bytes**,
`sha256 b1477094fb103a3523bb8d32b312aa0bc2b4bd4e9afff4c128bd886adc9a1d76`.

## 4. Validate and repair using JSON Pointer + stable code

`validate` is the gatekeeper. An invalid score exits `2` with machine-readable
`diagnostics`, each carrying a **stable `code`** and a **JSON Pointer** into your
source. Example — `examples/music_authoring/guide/invalid_pitch.json` (one note
of the `melody` pattern raised to `E7`, above D7):

```
tools/atm-music validate examples/music_authoring/guide/invalid_pitch.json --backend progmem --json
# exit 2
```

Observed diagnostics (exact):

```json
{"ok": false, "diagnostics": [
  {"code": "PITCH_RANGE", "severity": "error",
   "path": "/patterns/melody/events/0/note",
   "message": "E7 is outside the engine pitch range C2..D7.",
   "suggestion": "Choose a pitch between C2 and D7."},
  {"code": "UNKNOWN_PATTERN", "severity": "error",
   "path": "/tracks/pulse0/0/pattern",
   "message": "Unknown pattern 'melody'.",
   "suggestion": "Add the pattern to /patterns or fix the reference."}],
 "artifacts": {}}
```

The second diagnostic cascades from the first: a pattern that fails admission is
not registered, so the track reference then looks unknown. **Repair the root
cause at the reported pointer** — change `/patterns/melody/events/0/note` from
`"E7"` to `"C4"` (that repaired file is
`examples/music_authoring/guide/invalid_pitch_fixed.json`) — and both clear:

```
tools/atm-music validate examples/music_authoring/guide/invalid_pitch_fixed.json --backend progmem --json
# ok:true, exit 0, expanded_note_events:1, event_digest 407913e5d9dc55b929dd2c4a10473832ad6f939519076deb3938ac200978d66b
```

Other stable codes you will meet: `EVENT_OVERLAP`, `EVENT_OUTSIDE_PATTERN`,
`UNKNOWN_INSTRUMENT`, `VOICE_CHANNEL_MISMATCH`, `LIMIT_EXCEEDED`,
`BACKEND_UNAVAILABLE`, `DUE_GROUP_TOO_LARGE`. The tool never silently quantizes
time, transposes, drops voices or truncates.

> The `basic` example's README quotes a placeholder pointer
> `/patterns/p/events/0/note` for its invalid-pitch case. That `p` is illustrative
> prose, not a real pattern name; use the guide fixtures above when you need an
> exact, copy-pasteable pointer.

## 5. Look at the music before you export it

The offline HTML/JS review is a **required** step, not an optional extra. It reads
the canonical review payload, embeds it plus local CSS/JS, and (with
`--audio-preview`) embeds the matching WAV. It needs no server, account, network
or installed app — it opens from `file://`.

**5a. Inspect first (no audio yet).** This validates the source and writes a
standalone viewer plus a deterministic adjacent JSON:

```
tools/atm-music inspect examples/music_authoring/showcase/song.json \
    --out build/music-authoring/guide/review-before/review.html --json
```

- Viewer: `build/music-authoring/guide/review-before/review.html`
- Adjacent payload: `build/music-authoring/guide/review-before/review.json`

The adjacent JSON is **byte-for-byte** what `build --backend progmem` writes as
`review.json` (`sha256 db74d2fe8811d97c529da30da475dab54a81bdd6ad9fa7f756217b79f64be41a`).
Open the HTML locally (`open build/music-authoring/guide/review-before/review.html`
on macOS) to see all four lanes on one tick timeline with a piano-roll and a
tracker table; selecting a note shows channel, pitch, start tick, duration,
instrument, pattern instance and its source JSON Pointer. With no audio it says
audio is unavailable.

**5b. Render a faithful WAV.** `render` executes an *actual* AVR image (the
unmodified library + the generated score) under the local absim emulator and
captures the emulator's real PCM. No sine/MIDI/hand-written substitute is used.

```
tools/atm-music render examples/music_authoring/showcase/song.json \
    --backend progmem --seconds 12 --out build/music-authoring/guide/preview --json
```

- WAV: `build/music-authoring/guide/preview/preview.wav`
- Report: `build/music-authoring/guide/preview/preview.json`
- Tick trace: `build/music-authoring/guide/preview/tick_trace.csv`

The render window is `min(--seconds, song + 0.5 s tail)`; `--seconds` above 300 is
rejected and a short window sets `render.truncated`. Observed for showcase: WAV
**849 834 bytes**, `sha256 68768532bd638a8537c8e513f126f471f46a6da7636d8b3b2032e2594cbc78f6`,
`pcm-s16le-mono` 50 000 Hz, 424 895 samples = **8.4979 s**, 400/400 ticks,
`truncated:false`, first music callback sample **1045** (0.0209 s, measured).

**5c. Inspect again *with* the matching WAV.** This embeds the rendered audio and
its provenance after checking the source and event digests match the score:

```
tools/atm-music inspect examples/music_authoring/showcase/song.json \
    --audio-preview build/music-authoring/guide/preview \
    --out build/music-authoring/guide/review/review.html --json
```

- Viewer with audio: `build/music-authoring/guide/review/review.html`
  (1 187 226 bytes, `sha256 55c3fe47a86c9da03f3b1e96a6eb8dda6838afbec46a16e894bde0a5e60ac1cb`)
- Adjacent payload: `build/music-authoring/guide/review/review.json`

The viewer plays the WAV with a synchronized playhead and will **reject** a stale
preview (warning, no embedded audio) rather than let an old revision play under a
new score. A single WAV is the mono speaker mix; lane checkboxes are **visibility
only** and never change the audio.

> **Reviewer-walkthrough honesty.** The `basic` sample passed a real Chrome 155
> `file://` walkthrough (`build/music-authoring/inspect-tests/walkthrough-basic.json`,
> `external_requests: []`). For the showcase a separate attempt to launch Chrome
> for this composition **failed at DevTools startup**; the showcase review HTML
> *generation* itself succeeded and its source/event/audio digests match
> (above). This guide does not claim the showcase was browser-walked through.

## 6. Export: build the PROGMEM score

Building is explicit and separate from viewing; do it after you have reviewed the
score.

```
tools/atm-music build examples/music_authoring/showcase/song.json \
    --backend progmem --out build/music-authoring/guide/build --json
```

Artifacts:

| Artifact | Path | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| PROGMEM score | `build/music-authoring/guide/build/score.bin` | 395 | `5a89dbde291ab9f1182a3d8cb0737737b1680edc654d36704b5f63b9e9935981` |
| Generated header | `build/music-authoring/guide/build/score.h` | 2953 | `46f0897eb4cf9a9e47b81bb56aa5071ef030233f0b3558592caad1ec25958709` |
| Digest report | `build/music-authoring/guide/build/report.json` | 2306 | `4421628704d83ac5697f709b6a6a05be494be5e6e59cb8f8e102afdb6cd2b4fd` |
| Review payload | `build/music-authoring/guide/build/review.json` | 18494 | `db74d2fe8811d97c529da30da475dab54a81bdd6ad9fa7f756217b79f64be41a` |

`report.json` carries the source path/sha, the canonical event digest, the clock,
`total_ticks`, `pattern_instances`, `expanded_note_events`, `required_features`,
the per-channel `program_bytes` (`[147,81,81,71]`) and the score hash.

**Bytes are asset bytes, not engine or game cost.** `score.bin` = 395 bytes is the
PROGMEM *song asset only*. It is **not** engine code, not static SRAM and not a
whole-game measurement. The engine's own static SRAM and flash cost is tracked
separately in [`research/fx/fx-footprint-results.md`](../research/fx/fx-footprint-results.md); the
measured engine + score deltas there are hundreds to thousands of bytes. Never
infer engine or game fit from a score byte count. `build` does not invoke
`arduino-cli`, so it reports no AVR image measurement (`avr_measurements.measured
= false`).

### PROGMEM vs FX — effects and loops on both, SFX on neither

- `progmem` is the default backend: the song lives in program flash beside the
  library, played by the original engine. It emits the full v1 surface,
  including pattern `effects` and `commands`.
- `--backend fx` is offered for `build`. It writes a compact FX stream
  (`stream.bin`/`stream.h`) rather than a PROGMEM score, and it advertises
  `loops`/`effects`/`commands` as supported and `sfx` as unsupported.
- Effects and commands are **supported**, never silently dropped: the adapter
  encodes the same command bytes as PROGMEM. A `"loop": true` score becomes a
  `0xC1` loop; a loop region larger than the ring needs `--streaming-loops`
  (`--ring N` sets the ring), otherwise the adapter exports the finite `0xC0`
  arrangement once and reports `LOOP_NOT_EXPORTED` (a warning).
- `validate` and `render` stay `--backend progmem`; `--backend fx` there exits
  `2` with `BACKEND_UNAVAILABLE`.

```json
{"code": "DUE_GROUP_TOO_LARGE",
 "message": "largest pass record is 34 bytes, larger than the 32-byte ring.",
 "suggestion": "Split the event or build with a larger ring."}
```

FX packaging (offloading the song to the FX chip, with its own stream framing,
due-group and service-gap admission checks) remains a separate program-storage
and runtime decision selected by `ATMlib2FX-hlh.6`. Do not present a PROGMEM
asset as an FX artifact, and do not expect FX output for a score with effects or
commands. The JSON score source is unaffected by the backend choice.

## 7. Revise one field, then re-validate/view/render

`examples/music_authoring/showcase/song.json` and the fixtures are shared; do not
edit them in place. Revise a **copy** of your own source. For this guide the
revision subject is a copy under the git-ignored output tree — same procedure you
would apply to your own `SONG.json`:

```
mkdir -p build/music-authoring/guide/revised
sed 's|{"at": 175, "note": "A4", "duration": 20, "instrument": "lead"}|{"at": 175, "note": "A5", "duration": 20, "instrument": "lead"}|' \
    examples/music_authoring/showcase/song.json > build/music-authoring/guide/revised/song.json
```

The visible source change is one authored field (the final lead cadence note,
`A4` → `A5`, still inside C2–D7) on a single line:

```
55c55
<         {"at": 175, "note": "A4", "duration": 20, "instrument": "lead"}
---
>         {"at": 175, "note": "A5", "duration": 20, "instrument": "lead"}
```

Now repeat the loop on the revised source:

```
tools/atm-music validate build/music-authoring/guide/revised/song.json --backend progmem --json
tools/atm-music inspect  build/music-authoring/guide/revised/song.json \
    --out build/music-authoring/guide/revised/review/review.html --json
tools/atm-music render   build/music-authoring/guide/revised/song.json \
    --backend progmem --seconds 12 --out build/music-authoring/guide/revised/preview --json
tools/atm-music inspect  build/music-authoring/guide/revised/song.json \
    --audio-preview build/music-authoring/guide/revised/preview \
    --out build/music-authoring/guide/revised/review-audio/review.html --json
```

### Revision delta (measured)

| Quantity | Base showcase | Revised (A4→A5) |
| --- | --- | --- |
| source `sha256` | `636cd3b0f0e458e2a4357144b58b7a09056c96d3bbe0dd190b9c2772c5ba7936` | `abf6d01037d51f8557f6cdb80c44cb818509e6547ad1da08654395f3be49b5ed` |
| event digest | `e4b1a95aee458c78f80118400754e9eca1b9ba6832368c16a2e61ce03d53c90e` | `f4fc129f03bef0dd82b263a15de7209d194d579ff8cf63ed35ce40f83683207a` |
| effective BPM / total ticks | 120.0 / 400 | 120.0 / 400 |
| WAV | 849 834 B, `sha256 68768532bd638a8537c8e513f126f471f46a6da7636d8b3b2032e2594cbc78f6` | 849 834 B, `sha256 a8b444e5e1f23a05d9f8c85b679a7c7c0f528ad4a0fd2731a92ab4548a5e238c` |
| review HTML | 1 187 226 B, `55c3fe47…` | 1 187 228 B, `9c6fe1fe…` |

The digest and audio both change while timing stays put; the review payload digest
(`review.json`) shifts too (`db74d2fe…` → `ddd4ae16b…`). That is the intended
signal: a different source produces a different canonical event stream, a
different WAV, and a different review, all traceable back to the one edited field.

## 8. Command + path reference

| Purpose | Command |
| --- | --- |
| capabilities | `tools/atm-music capabilities --json` |
| validate | `tools/atm-music validate SONG.json --backend progmem --json` |
| viewer (no audio) | `tools/atm-music inspect SONG.json --out OUT/review.html --json` |
| faithful WAV | `tools/atm-music render SONG.json --backend progmem --seconds N --out OUT/preview --json` |
| viewer + audio | `tools/atm-music inspect SONG.json --audio-preview OUT/preview --out OUT/review/review.html --json` |
| PROGMEM build | `tools/atm-music build SONG.json --backend progmem --out OUT/build --json` |
| FX build | `tools/atm-music build SONG.json --backend fx --out OUT/build --json` (compact stream; add `--ring N` / `--streaming-loops` for large loop regions) |

Outputs written by this guide (all under the git-ignored
`build/music-authoring/guide/`): `preview/preview.wav`,
`review/review.html` + `review/review.json` (adjacent payload), `build/score.bin`
+ `build/score.h` + `build/report.json` (digest report), and the revised copies
under `revised/`. Give a human listener the **WAV path** and the **review HTML
path** together; a model without audio input can inspect the WAV bytes but should
not claim to have judged musical quality.

## 9. Scope and honest limitations

- **Sound review is the listener's job.** Rendered WAVs and traces are
  correctness evidence (gates, silence, timing, determinism); they are not a
  numeric substitute for taste, and this guide does not claim a model heard them.
- **Both backends are effect-capable.** The PROGMEM backend and the compact FX
  adapter encode the same effect/command bytecode; the FX adapter adds loops
  (`0xC1`, streaming with `--streaming-loops`). A score byte count says nothing
  about whole-game fit, and the FX stream's own size is not a device
  measurement.
- **Mono capture.** The WAV is the emulated mono speaker mix; per-channel
  isolation is not possible from one file. After the score ends the stopped PWM
  leaves a constant DC rail (≈ −2000, zero AC) that is acoustically silent, not
  neutral 0. Lane visibility toggles never change audio.
- **Timer-quantized tempo.** The tool reports the actual effective tick rate
  (`2000 / floor(2000 / tick_rate)`, fractional for nondivisor requests); BPM is
  derived, never stored, and the device divider is unchanged.
- Regenerate the viewer and WAV after every revision; export is a deliberate
  `build` of the reviewed score. Do not treat a review as an export.
