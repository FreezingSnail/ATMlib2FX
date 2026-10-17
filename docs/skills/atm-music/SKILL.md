---
name: atm-music
description: Compose, review, or revise ATMlib2FX tracks with the local JSON authoring tools and matching AVR previews. Use for harmony, arrangement, timbre, tempo, stutter, or musical loop changes; engine development and FX backend implementation are separate tasks.
---

# ATMlib2FX music

Produce an original, playable composition or a focused revision, with a matching
preview the user can judge. Preserve the requested mood and scope. A technical
pass proves timing and playback; it does not establish musical quality.

Run commands from the repository root, identified by `tools/atm-music` and
`src/atm_synth.c`. Repository paths below are relative to that root, regardless
of where this skill is installed. Follow the repository's Beads workflow.

## Read what the task needs

- For composition, harmony, articulation, or a sour/stuttering passage, read
  [composition guidance](references/composition.md).
- For timing, rendering, loops, promotion, or export, read
  [port and preview workflow](references/workflow.md).
- Check the precise source contract in `tools/music_authoring/validate.py` and
  `docs/music-authoring-interface.md` when changing the score shape. Consult
  `docs/music-authoring-guide.md` for further command examples; historical
  measurements and old example descriptions may predate current sources.

## Port boundaries

- Author `atmlib-score` version 1 JSON. The fixed voices are `pulse0`, `pulse1`,
  `pulse2`, and `noise`; each is monophonic. Use natural/sharp note strings
  C2–D7. Noise tokens select noise behavior, not pitched samples.
- Instruments are fixed volume/duty presets. JSON supports notes, gates, rests,
  finite pattern reuse, and whole-song loops. Slides, vibrato, tremolo and engine
  arpeggio effects are not exposed by this JSON subset. Sequential chord notes
  can supply authored arpeggios without adding an engine feature.
- Source changes belong in `examples/music_authoring/`; intermediate outputs
  belong in `build/`. Keep each promoted WAV/report pair and standalone review
  beside its score. Edit source, then regenerate derived files.
- Current library demos loop. Preserve `"loop": true` when revising them unless
  the user's brief changes that requirement. Other compositions may be finite.
- Use the current PROGMEM backend. Do not label a candidate as exported FX music
  or modify the engine to fulfill an ordinary composition request. Preserve the
  project's SRAM/flash priorities; report score bytes as asset cost only.

## Work from the musical problem

Inspect the actual score and expanded `review.json` before changing notes.
Locate the passage by bar, pattern, channel, or time where possible. If the user
has not identified it, proceed with identifiable problems and state assumptions.

Make notes serve a phrase and its harmony, rather than independently replacing
all dissonant intervals. For stutter, distinguish repeated attacks and gate gaps
from engine timing or browser playback faults. Change the layer supported by
observed evidence. Recheck the final phrase into the first phrase for a loop.

After editing, validate and render the affected tracks. Rebuild matching reviews
and, for a library change, refresh the catalog context and library player. For
an actual export request, build the PROGMEM asset in the requested scope; review
and render work do not authorize deployment, device flashing, or FX integration.

Report concrete musical changes, the ready-to-open review/player path, checks
performed, and material limits. Do not claim listening, browser playback, or
physical-device sound verification unless those actions were actually possible.

## Guidance and provenance

This skill is written for the local ATMlib2FX implementation. Tracker concepts
were discussed using the [T-arg ATMlib README](https://github.com/T-arg/ATMlib),
credited to its contributors including TEAM a.r.g./JO3RI and Davey Taylor/STG.
The retrievable repository README used an older command encoding; the direct
file/raw views were unavailable during that comparison. It is not a verified
copy of a newer songwriting manual or skill. Use local code for exact semantics.

Keep melodies and implementation original. Do not clone, fetch, download,
vendor, or copy external implementations. Reading documentation explicitly
requested by the user does not authorize importing its code or music.
