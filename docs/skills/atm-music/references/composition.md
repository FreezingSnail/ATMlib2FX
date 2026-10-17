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
