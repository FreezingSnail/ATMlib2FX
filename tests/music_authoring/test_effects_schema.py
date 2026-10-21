"""Validator contract tests for additive v1 effect windows and live commands.

These tests are permanent: they pin the pattern-level ``effects`` and
``commands`` surface added to the ``atmlib-score`` v1 source contract, the
engine operand ranges behind each field, and the stable diagnostic codes and
RFC 6901 JSON Pointers for every rejection class.

Engine semantics referenced below come from ``src/atm_cmd_constants.h``,
``src/cmd_parse.c`` and ``src/atm_synth.c``; the exact byte mapping is recorded
in ``docs/music-authoring.md``.
"""

from __future__ import annotations

import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
_TOOLS = os.path.join(REPO_ROOT, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from music_authoring.score import (  # noqa: E402
    COMMAND_TYPES,
    EFFECT_TYPES,
    GLOBAL_COMMAND_TYPES,
    HOST_LIMITS,
)
from music_authoring.validate import validate_document  # noqa: E402


def validate_obj(obj):
    raw = json.dumps(obj).encode("utf-8")
    return validate_document(obj, source_path="<memory>", raw_bytes=raw)


def codes(diagnostics):
    return [d.code for d in diagnostics]


def paths(diagnostics):
    return [d.path for d in diagnostics]


def score_with(*, effects=None, commands=None, ticks=16, voice="pulse", note="C4", duration=12):
    """Minimal valid score with an optional effects and/or commands array."""
    if voice == "pulse":
        instruments = {"lead": {"voice": "pulse", "volume": 80, "duty": 127}}
        instrument = "lead"
        track = {"pulse0": [{"pattern": "p", "repeat": 1}]}
    else:
        instruments = {"drum": {"voice": "noise", "volume": 90}}
        instrument = "drum"
        track = {"noise": [{"pattern": "p", "repeat": 1}]}

    pattern = {
        "ticks": ticks,
        "events": [{"at": 0, "note": note, "duration": duration, "instrument": instrument}],
    }
    if effects is not None:
        pattern["effects"] = effects
    if commands is not None:
        pattern["commands"] = commands

    return {
        "format": "atmlib-score",
        "version": 1,
        "id": "fxprobe",
        "clock": {"tick_rate": 50, "ticks_per_beat": 25, "beats_per_bar": 4},
        "instruments": instruments,
        "patterns": {"p": pattern},
        "tracks": track,
    }


class EffectAcceptTests(unittest.TestCase):
    """One accept case per effect kind, plus the documented defaults."""

    def _accept(self, effects, *, voice="pulse"):
        score, diagnostics = validate_obj(score_with(effects=effects, voice=voice))
        self.assertEqual(diagnostics, [], f"expected no diagnostics, got {codes(diagnostics)}")
        return score.patterns["p"].effects

    def test_arpeggio_three_step(self):
        (window,) = self._accept(
            [{"at": 0, "type": "arpeggio", "offsets": [4, 7], "period": 4}]
        )
        self.assertEqual(window.kind, "arpeggio")
        self.assertEqual(window.offsets, (4, 7))
        self.assertEqual(window.period, 4)
        self.assertIs(window.repeat, True, "arpeggio repeat defaults to true")
        self.assertEqual(window.until, 16, "until defaults to pattern ticks")
        self.assertEqual(window.slot, "retrig")

    def test_arpeggio_two_step_non_repeating(self):
        (window,) = self._accept(
            [{"at": 0, "type": "arpeggio", "offsets": [7], "period": 1, "repeat": False}]
        )
        self.assertEqual(window.offsets, (7,))
        self.assertIs(window.repeat, False)

    def test_arpeggio_offsets_are_base_relative_not_cumulative(self):
        (window,) = self._accept(
            [{"at": 0, "type": "arpeggio", "offsets": [8, 8], "period": 2}]
        )
        self.assertEqual(window.offsets, (8, 8), "both offsets are absolute from the base note")

    def test_note_cut(self):
        (window,) = self._accept(
            [{"at": 2, "type": "note_cut", "period": 5, "repeat": False, "until": 12}]
        )
        self.assertEqual(window.kind, "note_cut")
        self.assertEqual(window.period, 5)
        self.assertIs(window.repeat, False)
        self.assertEqual(window.until, 12)
        self.assertEqual(window.slot, "retrig")

    def test_lfo(self):
        (window,) = self._accept(
            [{"at": 0, "type": "lfo", "mode": "vibrato", "depth": 40, "period": 8}]
        )
        self.assertEqual(window.mode, "vibrato")
        self.assertEqual(window.depth, 40)
        self.assertEqual(window.period, 8)

    def test_slide(self):
        (window,) = self._accept(
            [{"at": 0, "type": "slide", "param": "volume", "amount": -3, "every": 4}]
        )
        self.assertEqual(window.param, "volume")
        self.assertEqual(window.amount, -3)
        self.assertEqual(window.every, 4)

    def test_glissando(self):
        (window,) = self._accept(
            [{"at": 0, "type": "glissando", "period": 6, "direction": "down"}]
        )
        self.assertEqual(window.period, 6)
        self.assertEqual(window.direction, "down")

    def test_noise_retrig(self):
        (window,) = self._accept(
            [{"at": 0, "type": "noise_retrig", "period": 2, "note": "A4"}],
            voice="noise",
        )
        self.assertEqual(window.kind, "noise_retrig")
        self.assertEqual(window.period, 2)
        self.assertEqual(window.note, "A4")
        self.assertEqual(window.note_index, 34)

    def test_all_types_are_covered(self):
        self.assertEqual(set(EFFECT_TYPES), {
            "arpeggio",
            "note_cut",
            "lfo",
            "slide",
            "glissando",
            "noise_retrig",
        })

    def test_distinct_slots_share_a_start_tick(self):
        windows = self._accept(
            [
                {"at": 0, "type": "lfo", "mode": "tremolo", "depth": 10, "period": 4},
                {"at": 0, "type": "slide", "param": "frequency", "amount": 2, "every": 1},
                {"at": 0, "type": "glissando", "period": 3, "direction": "up"},
            ]
        )
        self.assertEqual([w.kind for w in windows], ["lfo", "slide", "glissando"])

    def test_sequential_retrig_windows_are_allowed(self):
        windows = self._accept(
            [
                {"at": 0, "type": "arpeggio", "offsets": [4], "period": 2, "until": 6},
                {"at": 6, "type": "note_cut", "period": 2, "until": 10},
            ]
        )
        self.assertEqual([w.kind for w in windows], ["arpeggio", "note_cut"])

    def test_empty_arrays_are_accepted(self):
        score, diagnostics = validate_obj(score_with(effects=[], commands=[]))
        self.assertEqual(diagnostics, [])
        self.assertEqual(score.patterns["p"].effects, ())
        self.assertEqual(score.patterns["p"].commands, ())

    def test_existing_scores_have_no_effects(self):
        score, diagnostics = validate_obj(score_with())
        self.assertEqual(diagnostics, [])
        self.assertEqual(score.patterns["p"].effects, ())
        self.assertEqual(score.patterns["p"].commands, ())


class CommandAcceptTests(unittest.TestCase):
    def test_all_command_kinds_and_boundaries(self):
        commands = [
            {"at": 0, "type": "set_tempo", "value": 8},
            {"at": 1, "type": "add_tempo", "value": -128},
            {"at": 2, "type": "set_transposition", "value": -12},
            {"at": 3, "type": "add_transposition", "value": 12},
            {"at": 4, "type": "set_volume", "value": 255},
            {"at": 5, "type": "set_mod", "value": 0},
            {"at": 6, "type": "cue", "value": 7},
        ]
        score, diagnostics = validate_obj(score_with(commands=commands))
        self.assertEqual(diagnostics, [])
        kinds = [c.kind for c in score.patterns["p"].commands]
        self.assertEqual(kinds, [c["type"] for c in commands])
        self.assertEqual(
            {c.kind for c in score.patterns["p"].commands if c.is_global},
            set(GLOBAL_COMMAND_TYPES),
        )

    def test_command_start_tick_default_boundary(self):
        score, diagnostics = validate_obj(
            score_with(commands=[{"at": 15, "type": "cue", "value": 1}])
        )
        self.assertEqual(diagnostics, [])
        self.assertEqual(score.patterns["p"].commands[0].at, 15)

    def test_all_command_types_covered(self):
        self.assertEqual(set(COMMAND_TYPES), {
            "set_tempo",
            "add_tempo",
            "set_transposition",
            "add_transposition",
            "set_volume",
            "set_mod",
            "cue",
        })


class EffectRejectTests(unittest.TestCase):
    def _reject(self, effects, code, path, *, voice="pulse"):
        _, diagnostics = validate_obj(score_with(effects=effects, voice=voice))
        self.assertIn(code, codes(diagnostics), f"codes={codes(diagnostics)}")
        self.assertIn(path, paths(diagnostics), f"paths={paths(diagnostics)}")

    def test_unknown_effect_type(self):
        self._reject(
            [{"at": 0, "type": "reverb"}],
            "UNKNOWN_EFFECT_TYPE",
            "/patterns/p/effects/0/type",
        )

    def test_missing_type(self):
        self._reject(
            [{"at": 0, "period": 2}],
            "MISSING_FIELD",
            "/patterns/p/effects/0/type",
        )

    def test_effects_must_be_array(self):
        _, diagnostics = validate_obj(score_with(effects={"at": 0}))
        self.assertIn("TYPE_MISMATCH", codes(diagnostics))
        self.assertIn("/patterns/p/effects", paths(diagnostics))

    def test_effect_must_be_object(self):
        self._reject([42], "TYPE_MISMATCH", "/patterns/p/effects/0")

    def test_until_past_pattern(self):
        self._reject(
            [{"at": 0, "type": "arpeggio", "offsets": [4], "period": 2, "until": 99}],
            "EFFECT_BOUNDS",
            "/patterns/p/effects/0/until",
        )

    def test_at_at_pattern_boundary(self):
        self._reject(
            [{"at": 16, "type": "glissando", "period": 2, "direction": "up"}],
            "EFFECT_BOUNDS",
            "/patterns/p/effects/0/at",
        )

    def test_until_not_after_at(self):
        self._reject(
            [{"at": 8, "type": "lfo", "mode": "tremolo", "depth": 1, "period": 4, "until": 8}],
            "EFFECT_BOUNDS",
            "/patterns/p/effects/0/until",
        )

    def test_same_slot_overlap(self):
        self._reject(
            [
                {"at": 0, "type": "arpeggio", "offsets": [4], "period": 2, "until": 8},
                {"at": 4, "type": "arpeggio", "offsets": [5], "period": 2},
            ],
            "EFFECT_OVERLAP",
            "/patterns/p/effects/1",
        )

    def test_arpeggio_and_note_cut_share_the_retrig_slot(self):
        self._reject(
            [
                {"at": 0, "type": "arpeggio", "offsets": [4], "period": 2, "until": 8},
                {"at": 4, "type": "note_cut", "period": 2},
            ],
            "EFFECT_OVERLAP",
            "/patterns/p/effects/1",
        )

    def test_effects_must_be_sorted(self):
        self._reject(
            [
                {"at": 4, "type": "lfo", "mode": "tremolo", "depth": 1, "period": 4},
                {"at": 2, "type": "glissando", "period": 2, "direction": "up"},
            ],
            "EFFECT_ORDER",
            "/patterns/p/effects/1/at",
        )

    def test_noise_effect_on_pulse_pattern(self):
        self._reject(
            [{"at": 0, "type": "noise_retrig", "period": 1, "note": "C4"}],
            "EFFECT_CHANNEL_MISMATCH",
            "/patterns/p/effects/0/type",
        )

    def test_pulse_effect_on_noise_pattern(self):
        self._reject(
            [{"at": 0, "type": "arpeggio", "offsets": [4], "period": 2}],
            "EFFECT_CHANNEL_MISMATCH",
            "/patterns/p/effects/0/type",
            voice="noise",
        )

    def test_arpeggio_offset_out_of_range(self):
        self._reject(
            [{"at": 0, "type": "arpeggio", "offsets": [15], "period": 2}],
            "VALUE_RANGE",
            "/patterns/p/effects/0/offsets/0",
        )

    def test_arpeggio_too_many_offsets(self):
        self._reject(
            [{"at": 0, "type": "arpeggio", "offsets": [1, 2, 3], "period": 2}],
            "VALUE_RANGE",
            "/patterns/p/effects/0/offsets",
        )

    def test_arpeggio_period_out_of_range(self):
        self._reject(
            [{"at": 0, "type": "arpeggio", "offsets": [4], "period": 33}],
            "VALUE_RANGE",
            "/patterns/p/effects/0/period",
        )

    def test_lfo_mode_invalid(self):
        self._reject(
            [{"at": 0, "type": "lfo", "mode": "wobble", "depth": 1, "period": 4}],
            "VALUE_RANGE",
            "/patterns/p/effects/0/mode",
        )

    def test_lfo_period_odd(self):
        self._reject(
            [{"at": 0, "type": "lfo", "mode": "tremolo", "depth": 1, "period": 7}],
            "VALUE_RANGE",
            "/patterns/p/effects/0/period",
        )

    def test_lfo_depth_out_of_range(self):
        self._reject(
            [{"at": 0, "type": "lfo", "mode": "tremolo", "depth": 256, "period": 4}],
            "VALUE_RANGE",
            "/patterns/p/effects/0/depth",
        )

    def test_slide_param_invalid(self):
        self._reject(
            [{"at": 0, "type": "slide", "param": "pan", "amount": 1, "every": 1}],
            "VALUE_RANGE",
            "/patterns/p/effects/0/param",
        )

    def test_slide_every_out_of_range(self):
        self._reject(
            [{"at": 0, "type": "slide", "param": "volume", "amount": 1, "every": 65}],
            "VALUE_RANGE",
            "/patterns/p/effects/0/every",
        )

    def test_slide_amount_out_of_range(self):
        self._reject(
            [{"at": 0, "type": "slide", "param": "volume", "amount": 128, "every": 1}],
            "VALUE_RANGE",
            "/patterns/p/effects/0/amount",
        )

    def test_glissando_direction_invalid(self):
        self._reject(
            [{"at": 0, "type": "glissando", "period": 2, "direction": "sideways"}],
            "VALUE_RANGE",
            "/patterns/p/effects/0/direction",
        )

    def test_glissando_period_out_of_range(self):
        self._reject(
            [{"at": 0, "type": "glissando", "period": 129, "direction": "up"}],
            "VALUE_RANGE",
            "/patterns/p/effects/0/period",
        )

    def test_noise_retrig_period_out_of_range(self):
        self._reject(
            [{"at": 0, "type": "noise_retrig", "period": 4, "note": "C4"}],
            "VALUE_RANGE",
            "/patterns/p/effects/0/period",
            voice="noise",
        )

    def test_noise_retrig_note_invalid(self):
        self._reject(
            [{"at": 0, "type": "noise_retrig", "period": 1, "note": "H2"}],
            "INVALID_NOTE",
            "/patterns/p/effects/0/note",
            voice="noise",
        )

    def test_noise_retrig_note_out_of_range(self):
        self._reject(
            [{"at": 0, "type": "noise_retrig", "period": 1, "note": "E7"}],
            "PITCH_RANGE",
            "/patterns/p/effects/0/note",
            voice="noise",
        )

    def test_unknown_effect_field(self):
        self._reject(
            [{"at": 0, "type": "glissando", "period": 2, "direction": "up", "repeat": True}],
            "UNKNOWN_FIELD",
            "/patterns/p/effects/0/repeat",
        )

    def test_missing_required_effect_field(self):
        self._reject(
            [{"at": 0, "type": "slide", "param": "volume", "amount": 1}],
            "MISSING_FIELD",
            "/patterns/p/effects/0/every",
        )


class CommandRejectTests(unittest.TestCase):
    def _reject(self, commands, code, path):
        _, diagnostics = validate_obj(score_with(commands=commands))
        self.assertIn(code, codes(diagnostics), f"codes={codes(diagnostics)}")
        self.assertIn(path, paths(diagnostics), f"paths={paths(diagnostics)}")

    def test_unknown_command_type(self):
        self._reject(
            [{"at": 0, "type": "set_pan", "value": 1}],
            "UNKNOWN_COMMAND_TYPE",
            "/patterns/p/commands/0/type",
        )

    def test_missing_type(self):
        self._reject(
            [{"at": 0, "value": 1}],
            "MISSING_FIELD",
            "/patterns/p/commands/0/type",
        )

    def test_commands_must_be_array(self):
        _, diagnostics = validate_obj(score_with(commands={}))
        self.assertIn("TYPE_MISMATCH", codes(diagnostics))
        self.assertIn("/patterns/p/commands", paths(diagnostics))

    def test_command_must_be_object(self):
        self._reject([[]], "TYPE_MISMATCH", "/patterns/p/commands/0")

    def test_set_tempo_below_minimum(self):
        self._reject(
            [{"at": 0, "type": "set_tempo", "value": 4}],
            "VALUE_RANGE",
            "/patterns/p/commands/0/value",
        )

    def test_set_volume_above_maximum(self):
        self._reject(
            [{"at": 0, "type": "set_volume", "value": 256}],
            "VALUE_RANGE",
            "/patterns/p/commands/0/value",
        )

    def test_add_tempo_int8_range(self):
        self._reject(
            [{"at": 0, "type": "add_tempo", "value": 200}],
            "VALUE_RANGE",
            "/patterns/p/commands/0/value",
        )

    def test_command_at_pattern_boundary(self):
        self._reject(
            [{"at": 16, "type": "cue", "value": 1}],
            "COMMAND_BOUNDS",
            "/patterns/p/commands/0/at",
        )

    def test_duplicate_command(self):
        self._reject(
            [
                {"at": 0, "type": "set_tempo", "value": 50},
                {"at": 0, "type": "set_tempo", "value": 60},
            ],
            "COMMAND_DUPLICATE",
            "/patterns/p/commands/1/at",
        )

    def test_command_order(self):
        self._reject(
            [
                {"at": 4, "type": "cue", "value": 1},
                {"at": 2, "type": "set_mod", "value": 5},
            ],
            "COMMAND_ORDER",
            "/patterns/p/commands/1/at",
        )

    def test_unknown_command_field(self):
        self._reject(
            [{"at": 0, "type": "cue", "value": 1, "channel": "pulse0"}],
            "UNKNOWN_FIELD",
            "/patterns/p/commands/0/channel",
        )

    def test_invalid_command_blocks_pattern_registration(self):
        _, diagnostics = validate_obj(
            score_with(commands=[{"at": 0, "type": "set_tempo", "value": 4}])
        )
        self.assertIn("UNKNOWN_PATTERN", codes(diagnostics))


class EffectLimitTests(unittest.TestCase):
    def test_effect_window_limit(self):
        over = [{"at": 0, "type": "note_cut", "period": 1}] * (
            HOST_LIMITS["source_effects"] + 1
        )
        _, diagnostics = validate_obj(score_with(effects=over))
        self.assertIn("LIMIT_EXCEEDED", codes(diagnostics))
        self.assertIn("/patterns/p/effects", paths(diagnostics))

    def test_command_limit(self):
        over = [{"at": 0, "type": "cue", "value": 1}] * (
            HOST_LIMITS["source_commands"] + 1
        )
        _, diagnostics = validate_obj(score_with(commands=over))
        self.assertIn("LIMIT_EXCEEDED", codes(diagnostics))
        self.assertIn("/patterns/p/commands", paths(diagnostics))


if __name__ == "__main__":
    unittest.main()
