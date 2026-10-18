# Composing and diagnosing tracks

These are decision aids, not mandatory musical styles. Let the user's brief
choose mood, density, register, meter and intentional tension. Treat listening
feedback as the result to improve; avoid defending a cue because it validates.

## Harmony and phrases on three pulse voices

Establish a tonal center, a recognizable motif, and a progression that explains
where the motif is going. A short question and answer often works better than
unrelated notes across many bars. Develop the motif through rhythm, register,
contour or accompaniment; scale membership alone does not ensure good harmony.

For a conventional tonal cue, check sustained and accented notes against the
chord sounding at that moment. Use root, third and fifth as stable landings;
resolve suspensions, sevenths and chromatic approaches intentionally. Inspect
actual overlapping gates, including the bass's fifth: a melody fitting the root
can still rub against a different sustained bass note. Minor seconds, major
sevenths and tritones are useful diagnostic leads, not automatic errors.

Keep a countervoice supportive: common tones, close inversions, contrary motion,
and answers during lead rests can clarify the phrase. Dense independent motion
on all three pulse channels can obscure it. Check bass, harmony and lead as one
arrangement instead of treating each channel as a separate tune.

A simple E-minor option is `Em – C – G – D / Em – Am – D – Em`, used in the
rewritten Marsh cue. It is an example, not a default progression. The revised
`examples/music_authoring/creature_gatherer/marsh/song.json` demonstrates an
eight-bar question and answer with held support. Use it to understand the local
format, not to copy its tune into every new composition.

## Articulation and stutter

At 50 Hz, one tick is 20 ms. Compute a gap as
`next_start - (start + duration)`, including track/pattern boundaries. At 100 Hz,
one tick is 10 ms. Gaps that look small in JSON can interrupt a phrase audibly.

Each note event restores its instrument settings, triggers a pitch, and has an
explicit mute at gate end. Two same-pitch events with a gap are two attacks. If
they were intended as a sustained tone, merge them into one event whose gate
covers the intervening time. Do not remove intentional rhythmic repetitions.
Events cannot extend beyond their pattern; reorganize the affected phrase or
patterns if a sustained note must cross that boundary.

Tideline's four accidental repeats had 80–380 ms interruptions. Joining them
and using two-tick gaps gave it a more continuous lead. A 40 ms gap is an example
for that cue, not a rule for fanfares, plucked parts or percussion. Choose gates
by role: a held melody, short accompaniment and sparse noise can coexist.

If the score already describes the intended sound, examine the original-engine
trace and matching WAV. If only browser playback fails, investigate transport,
startup offsets, stale media, and loop bounds. A source edit cannot establish
that a browser fault was repaired.

## Engine effects and automation

Optional per-pattern `effects` and `commands` keys drive the engine's own effect
state and live commands. Both are additive: omitting them leaves an older score
unchanged. Read the exact accepted fields, byte mapping and diagnostics in
[the authoring interface](../../../music-authoring-interface.md#effect-windows-and-live-commands),
and validate every score before trusting a render. Effects and commands are
emitted by the PROGMEM backend; the finite-v1 FX adapter rejects any score that
declares them, so a cue that uses them is PROGMEM-only.

Tick math first. Effect timing is counted in ticks, so convert from the clock
before choosing a `period`. At 100 Hz one tick is 10 ms, so `period: 3` is a
30 ms step and `period: 10` is 100 ms; at 50 Hz (20 ms/tick) the same periods
are twice that. A window's `period` is what the engine advances between steps,
so raising the tempo shortens every step in real time and lowering it stretches
them — author the period against the intended pace, not only the tick count.

- **arpeggio** — `offsets` (1–2 absolute semitone intervals from the base note,
  values 0–14), `period` ticks per step, optional `repeat` (default true).
  `offsets: [4, 7]` is a major triad, base → third → fifth; `offsets: [3]` is a
  two-step minor-third stab. `offsets: [a, b]` walks base → base+a → base+b, so
  both intervals are measured from the base, not chained. Because the nibbles
  are absolute from the base, moving the base note transposes the whole figure.
  `repeat: true` re-triggers the base each cycle; `repeat: false` disables that
  automatic base re-trigger. Use a short period (1–4 ticks) on a held note for a
  chip pulse, a longer period (8–16) for a slow broken chord.
- **note_cut** — `period` ticks, optional `repeat`. A staccato/choke tool:
  silences the channel `period` ticks after each attack. With `repeat: true`
  (default) the base re-attacks every `2*period` ticks; `repeat: false` cuts
  once and stays off. Use it for a choked chip stab or a hard tremolo-like gate
  without writing alternating rests. It shares the arpeggio slot, so the two
  cannot run together.
- **lfo** — `mode` `tremolo` (volume), `vibrato` (pitch) or `modulation`
  (duty), `depth` (0–255), even `period` ticks (2–64, the full cycle). Use a
  shallow `tremolo` on a sustained pad for movement and a light `vibrato` on a
  held lead; `modulation` colours duty. Prefer an LFO over hand-written per-tick
  events when the movement is periodic and touches one parameter.
- **slide** — `param` `volume`/`frequency`/`modulation`, `amount` (−128..127),
  `every` ticks between applications. The swell/decay tool:
  `{"param":"volume","amount":-4,"every":1}` fades a held note every tick;
  `every: 4` steps in 4-tick increments and uses the advanced engine form.
  `frequency` is a pitch bend, `modulation` a duty sweep. All three params share
  one slide slot, so only one slide runs per channel at a time.
- **glissando** — `period` ticks per semitone, `direction` `up`/`down`. Written
  portamento without authoring each note; `period: 2` at 100 Hz is a 20 ms
  semitone step. Steps clamp to the C2–D7 range.
- **noise_retrig** — `period` (0–3), `note` (noise channel only). Retriggers the
  noise LFSR every `period + 1` ticks at the note's seed; use it for rolls,
  rattles and rolling thunder. It is a noise-channel effect.

Combination is constrained by the engine's shared, per-channel slots:

- `arpeggio` and `note_cut` share the retrigger slot; `slide`, `lfo`,
  `glissando` and `noise_retrig` are one slot each. Windows in the same slot
  must be ordered and non-overlapping, and the whole `effects` array is sorted
  by `at`. Closing one window before opening another in the same slot is how a
  channel changes effect mid-phrase.
- `noise_retrig` belongs only to a pattern whose events are noise instruments;
  the other five only to pulse patterns. A mismatch is a diagnostic, not silence.

Live `commands` are instantaneous, at most one per `(type, at)` with `at` in
`[0, ticks)`: tempo, transposition, volume, duty and cue. `set_tempo`,
`add_tempo` and `cue` write shared score state, so every channel that plays the
pattern re-executes them; `set_transposition`, `add_transposition`, `set_volume`
and `set_mod` write the playing channel. Prefer `set_*` over `add_*` for a
pattern shared by more than one channel.

When **not** to reach for effects:

- Dense, independently moving lines can obscure the phrase and compete for the
  same slot. Resolve the arrangement and note placement first; add an effect
  only where the movement is genuinely periodic and limited to one parameter.
- Effect state persists on the channel, so a window that runs past its phrase
  can leak into the next one. Give every window an explicit `until` that closes
  at the phrase boundary rather than defaulting to the pattern end.
- If two parameters must move independently on one channel, or the movement must
  be exactly grid-aligned, write the notes or use separate channels instead of
  stacking windows in a slot.
- `commands` change state, not notes; a `set_volume` command overrides the
  instrument volume set by a same-tick attack, so order writes deliberately.

## Tone, balance and rhythm

Pulse duty changes harmonic color, not note pitch. Thin duty cycles and high
registers can become piercing; consider register, duty, accompaniment density
and volume together. Lower a passage coherently to preserve its contour rather
than dropping isolated notes arbitrarily. Preserve unusual timbres when the
brief calls for them.

Give the lead room above supporting voices. Noise can dominate despite a short
gate; use clear rhythmic purpose and appropriate volume. Low rumble and rapid
high ticks are options, not an obligation for marshes, forests or coasts. Start
with a clear pulse and introduce syncopation where it strengthens a phrase.

Avoid "enhancing" an unclear melody by adding effects everywhere. Resolve the
arrangement first. Different cues can vary real tempo, note density, rhythmic
subdivision, phrase length, accompaniment and register; BPM metadata alone does
not create a different pace.

## Loop as part of the composition

Judge the final harmony and pickup against the opening downbeat. A dominant,
common tone or clear tonic return can work; a loop does not require one cadence.
Avoid a terminal fade or long end rest unless the user wants that behavior.
An introductory lead rest repeats on every whole-song loop, so consider whether
that interruption belongs in the cue.

Compare Raw emulator and Piezo (approx.) when playback is available. The latter
is uncalibrated; neither automated interval counts nor waveform statistics prove
that a listener likes the result or that the real speaker will sound identical.
