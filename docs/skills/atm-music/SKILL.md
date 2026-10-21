---
name: atm-music
description: Compose or revise ATMlib2FX songs as JSON and export a compact FX stream. Use for harmony, arrangement, timbre, tempo, effects, loops, or FX stream changes; engine implementation is a separate task.
---

# ATMlib2FX music

Write an original `atmlib-score` v1 JSON file and export the compact FX stream.
The technical pass proves validation, timing and stream shape; it does not prove
musical taste or physical-device sound.

Run commands from the repository root, identified by `tools/atm-music` and
`src/atm_synth.c`. Follow the repository's Beads workflow.

## Read what the task needs

- For harmony, articulation and musical recipes, read
  [composition guidance](references/composition.md).
- For the exact source contract, read `tools/music_authoring/validate.py` and
  [the authoring guide](../../music-authoring.md).
- For playback integration, read [FX integration](../../fx/integration.md).

## Port boundaries

- Author version 1 JSON. Fixed voices are `pulse0`, `pulse1`, `pulse2`, `noise`;
  each is monophonic. Use natural/sharp notes C2-D7. Noise tokens select noise
  behavior, not pitched samples.
- Instruments are fixed voice/volume/duty presets. Patterns support notes, rests,
  gates, finite repeats and whole-song loops.
- Optional per-pattern `effects` are `arpeggio`, `note_cut`, `lfo`, `slide`,
  `glissando`, `noise_retrig`. Optional `commands` are `set_tempo`/`add_tempo`,
  `set_transposition`/`add_transposition`, `set_volume`, `set_mod`, `cue`.
  `arpeggio`/`note_cut` share the retrigger slot; `slide`, `lfo`, `glissando`
  and `noise_retrig` are one slot each. Windows in a slot must be ordered and
  non-overlapping. `noise_retrig` is noise-channel only.
- Export with `tools/atm-music build SONG.json --backend fx --out OUT --json`.
  Global loops export as `0xC1`; a region larger than the ring needs
  `--streaming-loops`, otherwise it falls back to finite `0xC0` with
  `LOOP_NOT_EXPORTED`. SFX is not offered.
- Source changes belong in `examples/music_authoring/`; intermediate outputs
  belong in `build/`. Edit JSON only; never hand-edit generated streams.
- Preserve `"loop": true` when revising a looping cue unless the brief changes
  that requirement.

## Work from the musical problem

Inspect the score and expanded event model before changing notes. Locate the
passage by bar, pattern, channel or tick. Make notes serve a phrase and its
harmony rather than replacing every dissonant interval. For stutter, distinguish
repeated attacks and gate gaps from engine timing faults. Recheck the final
phrase into the first phrase for a loop.

Validate the edited score, then build the FX stream. Report diagnostics, source
and event digests, stream bytes, loop framing and any warnings. Do not claim
listening, browser playback or physical-device verification unless performed.

## Guidance and provenance

This skill is written for the local ATMlib2FX implementation. Tracker concepts
were discussed using the [T-arg ATMlib README](https://github.com/T-arg/ATMlib),
credited to its contributors including TEAM a.r.g./JO3RI and Davey Taylor/STG.
Use local code for exact semantics. Keep melodies and implementation original.
Do not clone, fetch or vendor external implementations or music.
