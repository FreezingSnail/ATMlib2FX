# Songwriting guide (adapted)

Practical songwriting techniques for the **ATMlib2FX** playroutine, adapted from
the [T-arg ATMlib](https://github.com/T-arg/ATMlib) README songwriting manual
(sections 0-13). Every example here is rewritten in this port's
`ATM_CMD_M_*` / `ATM_CMD_I_*` macros and every engine claim was checked against
`src/` (see [Verification checklist](#11-verification-checklist) and
[Provenance](#12-attribution-provenance-and-limitations)). This file documents
**macro/C-level** writing; for the JSON composer workflow see the
[model authoring guide](music-authoring-guide.md) and the
[authoring interface](music-authoring-interface.md), and for the raw command
encodings see the [library reference](library-reference.md).

Status: documentation only. It does not add engine behavior and does not
describe anything the current `src/` does not do.

## 0. How to read this

- This port is **not** the T-arg engine. Waveforms, arpeggio parameter
  semantics, the loop mechanism, call depth and tempo handling all differ.
  Section [1](#1-what-differs-from-the-t-arg-engine) lists the differences that
  matter to a composer; each is marked in place with **⚠ differs**.
- The first version (v1) JSON score format exposes only notes, gates, rests,
  finite pattern reuse, whole-song loops, tempo and volume/duty presets. The
  macro recipes below that use slides, LFOs, arpeggio, glissando or note cut are
  **engine capabilities that JSON v1 does not emit**; use them only when hand-
  writing a C header against `src/atm_cmd_constants.h`.
- Write commands with the macros only. The byte values are an implementation
  detail owned by `src/atm_cmd_constants.h`.

## 1. What differs from the T-arg engine

| Concept | T-arg manual | ATMlib2FX | Source |
| --- | --- | --- | --- |
| Voices | 4 channels, waveforms chosen at compile time (pulse, square, saw, noise) | 3 pulse oscillators with programmable duty + 1 noise; no saw | `src/osc.c`, `src/osc.h` |
| Pitch | note names are *not* concert pitch (≈ +1 octave, ≈ 80¢ flat) | note indices 1-63 are **concert-pitch** C2-D7 | `src/atm_cmd_constants.h`, `src/atm_synth.c` `noteTable` |
| Note off | `0x00` silences | `ATM_CMD_I_NOTE_OFF` (= 0) restores the channel volume; it is **not** a mute | `src/cmd_parse.c` `trigger_note` |
| Looping | per-track self-`GOTO(track)` | per-channel `SET_LOOP_PATTERN`; a `CALL` to the current pattern is ignored | `src/cmd_parse.c`, `src/atm_synth.c` |
| Loop seam | self-loop needed to remove a 1-tick hop | `130c9ca` restarts every looping channel in the **same callback**: no extra silent tick once all channels stop together | `src/atm_synth.c` `atm_synth_score_tick_handler` |
| Repeat count | `REPEAT(n,t)` runs `n+1` times | `ATM_CMD_M_CALL_REPEAT(t,n)` runs `n` times total | `src/atm_cmd_constants.h` macro, `src/cmd_parse.c` |
| Call depth | 7 | 3 | `src/atm_synth.h` `ATM_PATTERN_STACK_DEPTH` |
| Arpeggio intervals | 2nd = base+A, 3rd = 2nd+B (chained) | 2nd = base+high-nibble, 3rd = **base**+low-nibble (both from the base) | `src/atm_synth.c` `process_fx`, `src/cmd_parse.c` |
| Arpeggio + transposition | doubles the transposition (bug) | applied once | `src/atm_synth.c` `process_fx`, `trigger_note` |
| Tempo rule | "double the tempo value" (hardware ≈ value ticks/s) | no doubling: the requested tick rate is the effective rate (timer-quantized) | `src/osc.c` `osc_set_tick_rate` |
| Cues | `ATM_CUE` / `ATM.check()` | not part of the documented v1 authoring surface; SFX/cue work is out of scope here | `docs/music-authoring-interface.md` |

Two structural facts also differ and are used throughout:

- The PROGMEM score header is **`7 + 2 × patterns` bytes** in this port
  (`ATM_SCORE_FMT_FULL`: format byte, pattern count, 2-byte offsets, channel
  count, 4 entry bytes). See `tools/music_authoring/progmem_backend.py`.
- The host JSON compiler (not a human) writes the header, deduplicates identical
  whole-channel programs, pads short tracks and emits the loop targets. The
  sharing/transposition advice in sections 7-8 applies to hand-written macro
  scores.

## 2. Hop-free looping: `SET_LOOP_PATTERN`

The T-arg method loops each channel by calling its own track with `GOTO(itself)`
so the channel never stops. In this port a `CALL` to the **current** pattern is
ignored (`if (new_track != pattern_index(ch))` in `cmd_parse.c`), so the
equivalent is the engine's own loop command:

```
ATM_CMD_M_SET_LOOP_PATTERN(pattern_index)
```

It stores a per-channel loop target (2 bytes). When every channel has reached
`ATM_CMD_I_PATTERN_END` (STOP), the tick handler jumps every channel that has a
loop target back to it **inside the same callback** and re-runs the channel
loop. Commit `130c9ca` ("Fix 1 tick gap when looping score") added that
`goto start_loop`, which removes the extra silent tick the old stop/restart
method left at the seam. See `src/atm_synth.c`
`atm_synth_score_tick_handler`.

**The method (hand-written score):**

1. Let the cycle be `L` ticks. Put `ATM_CMD_M_SET_LOOP_PATTERN(<entry>)` at the
   **top** of every participating channel's program.
2. Every participating channel must contain **exactly `L` ticks of delay** and
   end with `ATM_CMD_I_PATTERN_END`. A channel that is one tick short or long
   goes silent early or drifts against the others.
3. The handler only restarts once **all** channels have stopped. Because they
   all reach STOP on the same tick (point 2), no channel is muted early and the
   restart adds no silent tick.
4. An unused channel points at a 1-byte `ATM_CMD_I_PATTERN_END` program; it is
   silent from tick 0. The host loop compiler keeps pattern 0 as a silent STOP
   when `pulse0` is among the tracks; else `SET_TEMPO` + `STOP` (3-byte program,
   5 bytes with its slot). Participants loop to their own entry, not pattern 0.
5. **State persists across the loop** (volume, slide, arpeggio, transposition).
   Re-assert what each pass depends on — typically `ATM_CMD_M_SET_VOLUME`,
   `ATM_CMD_M_SET_TEMPO`, `ATM_CMD_I_TRANSPOSITION_OFF`, the arpeggio — at the
   top of the program.

Do not try to loop with `ATM_CMD_I_PATTERN_END` plus a self-call: the self-call
is a no-op, and stopping without a loop target ends playback.

**One-shot scores** simply omit `SET_LOOP_PATTERN`; every channel ends with
`ATM_CMD_I_PATTERN_END` and may end at different times. The score stops when the
last channel stops (`atm_synth_is_score_stopped`).

## 3. Tempo and timing

`ATM_CMD_M_SET_TEMPO(rate)` / `ATM_CMD_M_ADD_TEMPO(delta)` set a **timer request
in Hz**, not a stored BPM (`src/cmd_parse.c` `process_1p_cmd` →
`score_state->tick_rate`). The timer quantizes it
(`src/osc.c` `osc_set_tick_rate`):

```
effective_tick_rate = 2000 / floor(2000 / requested_rate)
seconds             = total_ticks * floor(2000 / requested_rate) / 2000
effective_bpm       = effective_tick_rate * 60 / ticks_per_beat
```

- Default tick rate with no command is **25** (`atm_player_init_state`).
- Supported requests are **8-255**. Requested 255 yields exactly
  `2000/7 ≈ 285.714 Hz`.
- **⚠ differs:** there is no "double the tempo" rule. The requested rate is the
  effective rate; a score rendered at `tick_rate=50` plays 400 ticks in 8.000 s
  (measured in the authoring guide).
- Put tempo changes on one channel only; they are global
  (`score_state->tick_rate`). A tempo command re-executed on every loop pass is
  harmless when it sets the same value.
- All other timing is counted in ticks. `ATM_CMD_M_DELAY_TICKS`, `_1`, `_2`
  cover 1-32, 1-256 and 1-65534 ticks (see section 7). `_2` does not accept
  65535 — it becomes the stopped-channel sentinel (`0xFFFF`) and the channel stalls.

## 4. Pitch, register and note tokens

- Note tokens `ATM_CMD_I_NOTE_C2` … `ATM_CMD_I_NOTE_D7` are indices 1-63 over
  C2-D7 (`src/atm_cmd_constants.h`); index 0 is `ATM_CMD_I_NOTE_OFF`.
- **⚠ differs:** these are **concert pitch** in this port. The phase table
  (`src/atm_synth.c` `noteTable`) is clocked at `16000 / 65536` per unit
  (`src/osc.c` `OSC_SAMPLERATE` and the 16-bit accumulator), so index 1 ≈ 65.4 Hz
  (C2) and index 34 ≈ 440.0 Hz (A4). Do not apply the T-arg "octave up / 80¢
  flat" assumption.
- Sharps use a trailing underscore: `ATM_CMD_I_NOTE_F2_` is F#2. There is no
  `F#` spelling, no flat form, and no dedicated mute macro (index 0 is
  `ATM_CMD_I_NOTE_OFF`, which does not mute — see below).
- **⚠ differs:** a raw `ATM_CMD_I_NOTE_OFF` (or index 0) runs the note-zero
  branch of `trigger_note`, which sets the oscillator volume to 0 and then falls
  through to `trigger_both`, restoring the channel volume. It is **not** a
  reliable mute. Use `ATM_CMD_M_SET_VOLUME(0)` for silence. See the same caveat
  in `docs/music-authoring-interface.md`.
- On the noise channel (index 3) the token is the **LFSR seed**, not a pitch
  (`src/osc.c` uses the channel's phase word directly as the noise shift
  register). Different tokens give different noise colors; index 0 gives an
  all-zero register (silence). Noise has no melody.
- Registers that worked in adapted cues: lead C4-D6, chord arpeggios G3-E4, bass
  A2-A3 (or a lower root transposed up), drums on the noise channel.

## 5. Chords, inversions and arpeggio

### 5.1 Arpeggio encoding in this port

```
ATM_CMD_M_ARPEGGIO_ON(notes, timing)   // 3 bytes;  ATM_CMD_I_ARPEGGIO_OFF (1 byte)
```

- `notes` (`p1`) is `high_nibble = semitones base→2nd`, `low_nibble = semitones
  base→3rd`. **⚠ differs:** the low nibble is measured **from the base note**,
  not from the 2nd note, so T-arg's `0x43`/`0x34` values do not transfer.
  Nibble values 0-14 are valid; `0x0F` means "no note".
- `timing` (`p2`) is `b-edttttt`: low 5 bits = ticks per step minus one
  (`0x20` = 1 tick), bit 5 (`0x20`) = restart on note-on, bit 6 (`0x40`) = only
  two notes (skip the 3rd). `0x20` = fast stabs, `0x23` = slow 4-tick steps.
- A new note starts the rotation; the arpeggio and note cut share the same
  channel state, so keep one per channel.

### 5.2 Chord and inversion table (this port's encoding)

Intervals are semitones from the arpeggio's base note.

| Chord | Base→2nd | Base→3rd | `notes` (`p1`) |
| --- | ---: | ---: | --- |
| major, root position | 4 | 7 | `0x47` |
| minor, root position | 3 | 7 | `0x37` |
| major, 1st inversion (3rd in bass) | 3 | 8 | `0x38` |
| major, 2nd inversion (5th in bass) | 5 | 9 | `0x59` |
| minor, 1st inversion | 4 | 9 | `0x49` |
| minor, 2nd inversion | 5 | 8 | `0x58` |
| maj7 colour (no 5th) | 4 | 11 | `0x4B` |
| m7 colour (no 5th) | 3 | 10 | `0x3A` |
| dominant 7 colour (no 5th) | 4 | 10 | `0x4A` |

Inversions keep stabs in one register. Because the transposition is added once
(not doubled), a transposed arpeggio is safe in this port; the base note and
transposition together must still land in 1-63.

Two cheap patterns for chords, per adapted recipe:

```
// stabs: one arp + one short note per beat
ATM_CMD_M_SLIDE_VOL_ON((uint8_t)-3),
ATM_CMD_M_SET_VOLUME(24),
ATM_CMD_M_ARPEGGIO_ON(0x37, 0x20),      // minor stab
ATM_CMD_I_NOTE_A3, ATM_CMD_M_DELAY_TICKS(8),

// held chord: arp set once, one long note per bar
ATM_CMD_M_SET_VOLUME(30),
ATM_CMD_M_SLIDE_VOL_ON((uint8_t)-1),
ATM_CMD_M_ARPEGGIO_ON(0x37, 0x23),      // slow dreamy arp
ATM_CMD_I_NOTE_D4, ATM_CMD_M_DELAY_TICKS(64),
```

### 5.3 Anti-patterns (adapted)

- **Invented bytes.** Use `ATM_CMD_M_*` from `src/atm_cmd_constants.h`; do not
  hand-assemble opcode values.
- **Assuming T-arg arpeggio values.** Recompute the nibbles from the table above.
- **Looping with a self-call or with `STOP` and no loop target.** Use
  `SET_LOOP_PATTERN` and equal-length channels (section 2).
- **Off-by-one loops.** Every participating channel sums to exactly `L` ticks.
- **Mixing repeat conventions.** `CALL_REPEAT(t,n)` runs `n` times total (T-arg
  ran `n+1`).
- **Deep call nesting.** Depth is 3, not 7.
- **Doubling the tempo.** Not applicable here; the requested rate is effective.
- **Invalid note spelling.** `F#5`, flats, MIDI numbers, or a negative macro
  argument without a cast. Use `ATM_CMD_I_NOTE_F5_`,
  `ATM_CMD_M_SLIDE_VOL_ON((uint8_t)-2)`.
- **Raw note-off as a mute.** Use `ATM_CMD_M_SET_VOLUME(0)` (section 4).
- **Relying on note cut / raw note 0 to silence.** The note-zero path restores
  volume, so a hardware "silent" step is not guaranteed. Lower the volume
  explicitly.
- **Stacking a slide and an LFO of the same kind.** Slides share one slot per
  channel and LFOs share another (`src/cmd_parse.c` `process_np_cmd`); starting
  one replaces the other.
- **Trimming the loop's last delay.** Keep full delays; do not subtract a tick.

## 6. Noise drum recipes

Drums on the noise channel (index 3) are volume + slide + delay; a note token
only reseeds the noise. Volume is a `SET_VOLUME` command (2 bytes); the slide is
`SLIDE_VOL_ON` (3 bytes) and decays until it is changed or reset.

Volume values are documented as 0-127 with bit 7 reserved
([library reference](library-reference.md) "Set Volume"); the JSON validator
accepts 0-255, but stay within 0-127 for predictable mixing.

| Sound | Macros (16-tick beat) |
| --- | --- |
| kick click | `ATM_CMD_M_SET_VOLUME(48), ATM_CMD_M_SLIDE_VOL_ON((uint8_t)-12), ATM_CMD_M_DELAY_TICKS(4)` |
| closed hat | `ATM_CMD_M_SET_VOLUME(14), ATM_CMD_M_SLIDE_VOL_ON((uint8_t)-7), ATM_CMD_M_DELAY_TICKS(4)` |
| open hat | `ATM_CMD_M_SET_VOLUME(26), ATM_CMD_M_SLIDE_VOL_ON((uint8_t)-3), ATM_CMD_M_DELAY_TICKS(8)` |
| snare / clap | `ATM_CMD_M_SET_VOLUME(44), ATM_CMD_M_SLIDE_VOL_ON((uint8_t)-5), ATM_CMD_M_DELAY_TICKS(8)` |
| snare roll | step `ATM_CMD_M_SET_VOLUME(22…50)` by 4 with `ATM_CMD_M_SLIDE_VOL_ON((uint8_t)-9), ATM_CMD_M_DELAY_TICKS(2)` |

Beat A (beats 1 and 3) = kick(4) + closed hat(4) + open hat(8) = 16 ticks.
Beat B (beats 2 and 4) = snare(8) + open hat(8). Replace beat 4 of the last bar
with the roll. A 16-tick beat reused four times gives `L = 64`:

```
// "beat" pattern (called)
ATM_CMD_M_SET_VOLUME(48), ATM_CMD_M_SLIDE_VOL_ON((uint8_t)-12), ATM_CMD_M_DELAY_TICKS(4),
ATM_CMD_M_SET_VOLUME(14), ATM_CMD_M_SLIDE_VOL_ON((uint8_t)-7),  ATM_CMD_M_DELAY_TICKS(4),
ATM_CMD_M_SET_VOLUME(26), ATM_CMD_M_SLIDE_VOL_ON((uint8_t)-3),  ATM_CMD_M_DELAY_TICKS(8),
ATM_CMD_I_PATTERN_END,

// noise entry (L = 64, self-looping)
ATM_CMD_M_SET_LOOP_PATTERN(<beat entry>),
ATM_CMD_M_CALL_REPEAT(<beat>, 4),
ATM_CMD_I_PATTERN_END,
```

For a low rumble/thunder texture, sample the noise color with note tokens and,
if the score is hand-written, retrigger the LFSR with
`ATM_CMD_M_NOISE_RETRIG_ON(cfg)` (2 bytes; `ATM_CMD_I_NOISE_RETRIG_OFF` is
1 byte). This is an engine macro not exposed by JSON v1.

A tonal kick (when a pulse channel is free of arpeggio), adapted from the
manual:

```
ATM_CMD_I_ARPEGGIO_OFF,
ATM_CMD_M_SLIDE_FREQ_ON((uint8_t)-127),
ATM_CMD_M_SET_VOLUME(30),
ATM_CMD_I_NOTE_D3_,
ATM_CMD_M_DELAY_TICKS(4),
ATM_CMD_M_SET_VOLUME(0),
ATM_CMD_M_DELAY_TICKS(4),
```

## 7. Byte costs for this port's encoding

Verified against `src/atm_cmd_constants.h` and
`tools/music_authoring/progmem_backend.py`. "JSON v1" marks what the current
score compiler emits.

| Macro | Bytes | Emitted by JSON v1 |
| --- | ---: | --- |
| `ATM_CMD_M_NOTE(n)` / `ATM_CMD_I_NOTE_*` (index 1-63) | 1 | yes (note) |
| `ATM_CMD_I_NOTE_OFF` (index 0) | 1 | no |
| `ATM_CMD_M_DELAY_TICKS(d)`, d = 1-32 | 1 | yes |
| `ATM_CMD_M_DELAY_TICKS_1(d)`, d = 33-256 | 2 | yes |
| `ATM_CMD_M_DELAY_TICKS_2(d)`, d = 257-65534 | 3 | yes |
| `ATM_CMD_I_PATTERN_END` (STOP; alias of `_RETURN`) | 1 | yes |
| `ATM_CMD_I_TRANSPOSITION_OFF` | 1 | no |
| `ATM_CMD_I_GLISSANDO_OFF` | 1 | no |
| `ATM_CMD_I_ARPEGGIO_OFF` | 1 | no |
| `ATM_CMD_I_NOISE_RETRIG_OFF` | 1 | no |
| `ATM_CMD_M_SET_VOLUME` | 2 | yes (also used for mute = 0) |
| `ATM_CMD_M_SET_MOD` (duty) | 2 | yes |
| `ATM_CMD_M_SET_TEMPO` / `ATM_CMD_M_ADD_TEMPO` | 2 | set only |
| `ATM_CMD_M_SET_TRANSPOSITION` / `ATM_CMD_M_ADD_TRANSPOSITION` | 2 | no |
| `ATM_CMD_M_NOISE_RETRIG_ON` | 2 | no |
| `ATM_CMD_M_SET_LOOP_PATTERN` | 2 | yes (when `"loop": true`) |
| `ATM_CMD_M_CALL` | 2 | no |
| `ATM_CMD_M_CALL_REPEAT` | 3 | no (repeats are expanded) |
| `ATM_CMD_M_GLISSANDO_ON` | 2 | no |
| `ATM_CMD_M_NOTECUT_ON` | 2 | no |
| `ATM_CMD_M_SLIDE_{VOL,FREQ,MOD}_ON` | 3 | no |
| `ATM_CMD_M_SLIDE_{VOL,FREQ,MOD}_OFF` | 2 | no |
| `ATM_CMD_M_SLIDE_{VOL,FREQ,MOD}_ADV_ON` | 4 | no |
| `ATM_CMD_M_ARPEGGIO_ON` | 3 | no |
| `ATM_CMD_M_{TREMOLO,VIBRATO,MOD_LFO}_ON` | 4 | no |
| `ATM_CMD_M_{TREMOLO,VIBRATO,MOD_LFO}_OFF` | 2 | no |

Header (full format, `ATM_SCORE_FMT_FULL`):

```
header_bytes = 7 + 2 * patterns
             = 1 format + 1 pattern count + 2*N offsets + 1 channel count + 4 entries
```

Every program ends with one `_PATTERN_END` byte, counted above. Enabling
`"loop": true` in a JSON score adds 2 bytes (`SET_LOOP_PATTERN`) per
participating channel program plus a 1-byte silent pattern 0 (3 bytes including
its table slot) when `pulse0` is among the tracks; with no `pulse0` it is
`SET_TEMPO` + `STOP` instead (3-byte program, 5 bytes including its table slot).

## 8. Byte-budget checklist

Costs and sharing maths adapted from the manual, using this port's `CALL`
(2 bytes), table slot (2 bytes) and `_PATTERN_END` (1 byte):

1. **Budget the whole array**, header included: `7 + 2*patterns` plus the sum of
   every program's bytes.
2. **Transposition instead of copies.** Write one riff/bar in a base key, then
   move it with `ATM_CMD_M_SET_TRANSPOSITION` / `ATM_CMD_M_ADD_TRANSPOSITION`
   (2 bytes each).
3. **`CALL_REPEAT` identical bars.** 3 bytes for any number of repeats.
4. **Share a run only when it pays.** A run of `L` bytes used `u` times, put in
   its own pattern and called, costs `L + 1 + 2 + 2u` against `u*L` inline; it
   wins when `(u-1)*L > 2u + 3` (two uses need `L >= 8`, three uses `L >= 5`).
5. **Inline tracks used once.** A single-use track costs 5 bytes of overhead
   (2 table + 1 end + 2 call) for nothing.
6. **Drop dead commands.** Slides, volume, arpeggio and transposition are
   persistent state; a repeated command with the same value is dead weight.
   Remove it only when a render/compare proves the output is unchanged.
7. **Validate, do not count.** The host `atm-music` tool already deduplicates
   identical whole-channel programs for a JSON score; the manual sharing advice
   above is for hand-written headers.

## 9. In-game volume rule (~60 %)

Adapted from the manual's "keep the music quieter than the effects": when a
game plays sound effects that share the music channels, write in-game music at
about **60 % of the title/menu volume**, so effects at full volume stay audible.

- **Scale at compile time, not at runtime.** Change the authored numbers; a
  runtime volume control is not needed and costs bytes.
- **Scale the volume and the slide amounts together.** Scaling only the volume
  makes every note start lower but still fade at the old rate, so it dies
  sooner and sounds clipped.
- **Zero byte cost.** Changing a value never changes the command count.

For a JSON v1 score (only `volume` exists; slides are not exposed), set each
instrument's `volume` to roughly 60 % of its title value:

```json
"instruments": { "lead": {"voice": "pulse", "volume": 48, "duty": 127} }
```

For a hand-written C header, scale the macro arguments:

```c
#define MUSIC_VOL_PCT 60                       /* 100 = title/menu volume */

/* volume value, e.g. MV(80) -> 48 */
#define MV(v) ((v) * MUSIC_VOL_PCT / 100)

/* signed slide step, never rounded to 0 (0 would stop the fade) */
#define MS(n) (-((((n) * MUSIC_VOL_PCT + 50) / 100) < 1 ? \
                 1 : (((n) * MUSIC_VOL_PCT + 50) / 100)))

ATM_CMD_M_SET_VOLUME(MV(80)),
ATM_CMD_M_SLIDE_VOL_ON(MS(3)),                 /* instead of SLIDE_VOL_ON(-3) */
```

A fade step of 1 cannot be made smaller, so a very slow `SLIDE_VOL_ON(-1)`
still ends a little earlier at 60 %.

Scope note: v1 JSON has **no SFX**, and the finite FX backend does not carry SFX
or loops (see the [authoring interface](music-authoring-interface.md)
"Finite-v1 FX export" section). Applying this rule today means lowering authored
music volume; SFX authoring is a separate, not-yet-advertised capability.

## 10. Worked example patterns

A complete hand-written program body for a 64-tick self-looping three-voice
cycle. (The host compiler writes the header and, for JSON, the same structure.)

```
// pattern 1 - lead (pulse0), L = 64, self-looping
ATM_CMD_M_SET_LOOP_PATTERN(1),
ATM_CMD_M_SET_VOLUME(38),
ATM_CMD_M_SLIDE_VOL_ON((uint8_t)-2),
ATM_CMD_I_NOTE_A4, ATM_CMD_M_DELAY_TICKS(16),
ATM_CMD_I_NOTE_C5, ATM_CMD_M_DELAY_TICKS(16),
ATM_CMD_I_NOTE_E5, ATM_CMD_M_DELAY_TICKS(16),
ATM_CMD_I_NOTE_D5, ATM_CMD_M_DELAY_TICKS(16),
ATM_CMD_I_PATTERN_END,

// pattern 2 - bass (pulse2), L = 64, self-looping
ATM_CMD_M_SET_LOOP_PATTERN(2),
ATM_CMD_M_SET_VOLUME(48),
ATM_CMD_I_NOTE_A2, ATM_CMD_M_DELAY_TICKS(32),
ATM_CMD_I_NOTE_E2, ATM_CMD_M_DELAY_TICKS(32),
ATM_CMD_I_PATTERN_END,

// pattern 3 - noise entry (L = 64, self-looping)
ATM_CMD_M_SET_LOOP_PATTERN(3),
ATM_CMD_M_CALL_REPEAT(4, 4),                 /* 4 x 16-tick beat = 64 ticks */
ATM_CMD_I_PATTERN_END,

// pattern 4 - 16-tick noise beat (called by pattern 3)
ATM_CMD_M_SET_VOLUME(48), ATM_CMD_M_SLIDE_VOL_ON((uint8_t)-12), ATM_CMD_M_DELAY_TICKS(4),
ATM_CMD_M_SET_VOLUME(14), ATM_CMD_M_SLIDE_VOL_ON((uint8_t)-7),  ATM_CMD_M_DELAY_TICKS(4),
ATM_CMD_M_SET_VOLUME(26), ATM_CMD_M_SLIDE_VOL_ON((uint8_t)-3),  ATM_CMD_M_DELAY_TICKS(8),
ATM_CMD_I_PATTERN_END,

// pattern 0 - silent STOP for an unused channel
ATM_CMD_I_PATTERN_END,
```

A gentle "soft decay" cue needs no drums, only a decay slide `SET_VOLUME(30),
SLIDE_VOL_ON(-1)` per note. A one-riff-many-chords cue writes one riff once and
moves it with `ADD_TRANSPOSITION`. A slow arpeggio pad is one `ARPEGGIO_ON`
setup plus one long note per bar.

## 11. Verification checklist

- [ ] Every example compiles against `src/atm_cmd_constants.h` (macros, not raw
      bytes).
- [ ] Every participating loop channel sums to exactly `L` ticks and ends with
      `_PATTERN_END`.
- [ ] Each loop channel has `SET_LOOP_PATTERN` at the top of its program; no
      self-call loop.
- [ ] Unused channels point at a 1-byte `_PATTERN_END` (or JSON pattern 0).
- [ ] Call depth ≤ 3 (`ATM_PATTERN_STACK_DEPTH`).
- [ ] Every `note + transposition` is within 1-63.
- [ ] No raw note-off used as a mute (use `SET_VOLUME(0)`).
- [ ] Byte budget: `7 + 2*patterns` header plus all program bytes ≤ budget.
- [ ] In-game cues using SFX: music volume scaled ~60 % with slides scaled too.
- [ ] Validated and rendered with `tools/atm-music` (see the
      [authoring guide](music-authoring-guide.md)); a byte count is an asset
      count, never an engine or whole-game measurement.

## 12. Attribution, provenance and limitations

This guide adapts the songwriting section (sections 0-13) of the
[T-arg/ATMlib](https://github.com/T-arg/ATMlib) README, licensed
**BSD-3-Clause**, credited there to **TEAM a.r.g. / Joeri Gantois (JO3RI)** and
**Davey Taylor (STG)**. The port's own `LICENSE` is BSD-3-Clause, Copyright (c)
2016, TEAM a.r.g. Only concepts and structure were adapted; **no implementation
code or music was copied**, and every example was rewritten for this port's
macros.

All engine claims in this file were verified read-only against the current
`src/`:

- `src/atm_cmd_constants.h` — command values, parameter counts and public macros.
- `src/cmd_parse.c` — command parsing, loop target, call/repeat, arpeggio
  interval source, note-zero branch.
- `src/atm_synth.c` — note table, tick handler, loop restart (`130c9ca`), state.
- `src/atm_synth.h` — `ATM_PATTERN_STACK_DEPTH` (3).
- `src/osc.c` / `src/osc.h` — oscillators, tick-rate quantization, samplerate.
- `tools/music_authoring/progmem_backend.py` — PROGMEM header size, delay and
  loop emission.

Statements that differ from the T-arg manual are marked **⚠ differs**. Nothing
here claims a loop, effect, SFX or FX capability beyond what these sources
implement today; loops are PROGMEM-only, and the finite FX backend carries no
loops, effects or SFX.

See also: [library reference](library-reference.md) ·
[model authoring guide](music-authoring-guide.md) ·
[authoring interface](music-authoring-interface.md) ·
[ATMlib2FX music skill](skills/atm-music/SKILL.md).
