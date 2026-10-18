"""Host lowering tests for additive v1 effect windows and live commands.

These tests are permanent and co-located.  They pin the layer that expands
pattern effects/commands per pattern instance into absolute-tick typed device
ops (``tools/music_authoring/lower.py``): repeat expansion, effect OFF
placement, the deterministic same-tick ordering, the canonical event digest,
the review payload spans and their JSON Pointer sources, the required-feature
list, and the byte-stability of an effect-free score against the frozen golden.
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

from music_authoring.lower import (  # noqa: E402
    build_review_payload,
    lower,
    required_features,
    serialize_review,
)
from music_authoring.score import (  # noqa: E402
    COMMAND_TYPES,
    EFFECT_TYPES,
    parse_json_bytes,
)
from music_authoring.validate import validate_document  # noqa: E402

FIXTURE_SONG = os.path.join(REPO_ROOT, "tests/music_authoring/fixtures/basic/song.json")
FIXTURE_REVIEW = os.path.join(REPO_ROOT, "tests/music_authoring/fixtures/basic/expected/review.json")
GOLDEN_SOURCE_PATH = "examples/music_authoring/basic/song.json"


def validate_obj(obj):
    raw = json.dumps(obj).encode("utf-8")
    return validate_document(obj, source_path="<memory>", raw_bytes=raw)


def score_ok(obj):
    score, diagnostics = validate_obj(obj)
    assert score is not None, diagnostics
    return score


def codes(diagnostics):
    return [d.code for d in diagnostics]


def paths(diagnostics):
    return [d.path for d in diagnostics]


def base_document(*, effects=None, commands=None, ticks=8, repeat=1, channel="pulse0"):
    pattern = {
        "ticks": ticks,
        "events": [{"at": 0, "note": "C4", "duration": min(ticks, 2), "instrument": "lead"}],
    }
    if effects is not None:
        pattern["effects"] = effects
    if commands is not None:
        pattern["commands"] = commands
    return {
        "format": "atmlib-score",
        "version": 1,
        "id": "lower_probe",
        "clock": {"tick_rate": 50, "ticks_per_beat": 25, "beats_per_bar": 4},
        "instruments": {"lead": {"voice": "pulse", "volume": 80, "duty": 127}},
        "patterns": {"p": pattern},
        "tracks": {channel: [{"pattern": "p", "repeat": repeat}]},
    }


def op_names(lowered, channel):
    return [(op.op, op.tick) for op in lowered.ops_for_channel(channel)]


class EffectExpansionTests(unittest.TestCase):
    def test_effect_windows_survive_pattern_repeat(self):
        score = score_ok(
            base_document(
                ticks=8,
                repeat=3,
                effects=[{"at": 0, "type": "lfo", "mode": "tremolo", "depth": 10, "period": 4, "until": 4}],
            )
        )
        lowered = lower(score)
        self.assertEqual(
            [(e.start_tick, e.end_tick, e.repeat_index) for e in lowered.effect_spans],
            [(0, 4, 0), (8, 12, 1), (16, 20, 2)],
        )
        self.assertEqual(
            [(name, tick) for name, tick in op_names(lowered, "pulse0") if name == "lfo_on"],
            [("lfo_on", 0), ("lfo_on", 8), ("lfo_on", 16)],
        )
        self.assertEqual(
            [(name, tick) for name, tick in op_names(lowered, "pulse0") if name == "lfo_off"],
            [("lfo_off", 4), ("lfo_off", 12), ("lfo_off", 20)],
        )

    def test_effect_off_is_the_exclusive_until_tick(self):
        score = score_ok(
            base_document(
                ticks=8,
                effects=[{"at": 2, "type": "arpeggio", "offsets": [4, 7], "period": 3, "until": 6}],
            )
        )
        lowered = lower(score)
        (effect,) = lowered.effect_spans
        self.assertEqual((effect.start_tick, effect.end_tick), (2, 6))
        ops = dict(op_names(lowered, "pulse0"))
        self.assertEqual(ops["arpeggio_on"], 2)
        self.assertEqual(ops["arpeggio_off"], 6)

    def test_untils_defaults_to_pattern_end_and_off_lands_there(self):
        score = score_ok(
            base_document(
                ticks=8,
                effects=[{"at": 0, "type": "glissando", "period": 2, "direction": "up"}],
            )
        )
        lowered = lower(score)
        (effect,) = lowered.effect_spans
        self.assertEqual(effect.end_tick, 8)
        self.assertIn(("glissando_off", 8), op_names(lowered, "pulse0"))

    def test_note_cut_shares_the_arpeggio_off_op(self):
        score = score_ok(
            base_document(
                ticks=8,
                effects=[{"at": 0, "type": "note_cut", "period": 2, "repeat": False, "until": 5}],
            )
        )
        lowered = lower(score)
        names = [name for name, _ in op_names(lowered, "pulse0")]
        self.assertIn("note_cut_on", names)
        self.assertIn("arpeggio_off", names)
        self.assertNotIn("note_cut_off", names)

    def test_noise_retrig_on_the_noise_channel(self):
        doc = base_document(
            ticks=8,
            channel="noise",
            effects=[{"at": 0, "type": "noise_retrig", "period": 2, "note": "C3"}],
        )
        doc["instruments"] = {"hat": {"voice": "noise", "volume": 30}}
        doc["patterns"]["p"]["events"] = [
            {"at": 0, "note": "C4", "duration": 2, "instrument": "hat"}
        ]
        score = score_ok(doc)
        lowered = lower(score)
        (effect,) = lowered.effect_spans
        self.assertEqual(effect.kind, "noise_retrig")
        self.assertEqual(effect.channel, 3)
        self.assertIn(("noise_retrig_on", 0), op_names(lowered, "noise"))
        self.assertIn(("noise_retrig_off", 8), op_names(lowered, "noise"))

    def test_effect_params_are_typed_and_json_serializable(self):
        score = score_ok(
            base_document(
                effects=[{"at": 0, "type": "slide", "param": "volume", "amount": -3, "every": 4}]
            )
        )
        lowered = lower(score)
        (effect,) = lowered.effect_spans
        self.assertEqual(dict(effect.params)["param"], "volume")
        self.assertEqual(dict(effect.params)["amount"], -3)
        # params survive JSON encoding (tuples become arrays, never error).
        json.dumps(effect.as_dict())
        (op,) = [op for op in lowered.ops_for_channel("pulse0") if op.op == "slide_on"]
        self.assertIn("params", op.canonical())
        self.assertEqual(op.canonical()["params"]["every"], 4)


class SameTickOrderingTests(unittest.TestCase):
    def _pulse_ops(self):
        doc = base_document(
            ticks=4,
            effects=[{"at": 0, "type": "lfo", "mode": "tremolo", "depth": 10, "period": 4}],
            commands=[{"at": 0, "type": "set_volume", "value": 200}],
        )
        return lower(score_ok(doc)).ops_for_channel("pulse0")

    def test_same_tick_order_is_documented_and_deterministic(self):
        ops = self._pulse_ops()
        self.assertEqual(
            [(op.op, op.tick) for op in ops],
            [
                ("set_tempo", 0),
                ("lfo_on", 0),
                ("set_volume", 0),
                ("set_mod", 0),
                ("note", 0),
                ("set_volume", 0),  # live command last: overrides the note attack
                ("mute", 2),
                ("lfo_off", 4),
            ],
        )
        # The note attack carries the instrument volume; the command carries params.
        self.assertEqual(ops[2].canonical()["volume"], 80)
        self.assertEqual(ops[5].canonical()["params"], {"value": 200})

    def test_effect_off_precedes_a_same_tick_note_attack(self):
        doc = base_document(
            ticks=4,
            effects=[{"at": 0, "type": "lfo", "mode": "vibrato", "depth": 5, "period": 2, "until": 1}],
        )
        doc["patterns"]["p"]["events"] = [
            {"at": 0, "note": "C4", "duration": 1, "instrument": "lead"},
            {"at": 1, "note": "D4", "duration": 1, "instrument": "lead"},
        ]
        lowered = lower(score_ok(doc))
        tick_one = [op.op for op in lowered.ops_for_channel("pulse0") if op.tick == 1]
        # lfo_off closes the window before the adjacent gate mute and the second
        # note attack at tick 1.
        self.assertEqual(tick_one, ["lfo_off", "mute", "set_volume", "set_mod", "note"])


class CommandLoweringTests(unittest.TestCase):
    def test_commands_expand_across_repeats_and_carry_global_flag(self):
        score = score_ok(
            base_document(
                ticks=8,
                repeat=2,
                commands=[
                    {"at": 1, "type": "set_tempo", "value": 60},
                    {"at": 2, "type": "cue", "value": 7},
                    {"at": 3, "type": "set_transposition", "value": -12},
                ],
            )
        )
        lowered = lower(score)
        self.assertEqual(
            [(c.kind, c.tick, c.repeat_index) for c in lowered.command_events],
            [
                ("set_tempo", 1, 0),
                ("cue", 2, 0),
                ("set_transposition", 3, 0),
                ("set_tempo", 9, 1),
                ("cue", 10, 1),
                ("set_transposition", 11, 1),
            ],
        )
        globals_ = {c.kind for c in lowered.command_events if c.is_global}
        self.assertEqual(globals_, {"set_tempo", "cue"})
        settempo = [op for op in lowered.ops_for_channel("pulse0") if op.op == "set_tempo"]
        # tick 0 is the clock tempo; the live command is a later set_tempo op.
        self.assertEqual([op.tick for op in settempo], [0, 1, 9])
        self.assertEqual(settempo[1].canonical()["tick_rate"], 60)

    def test_all_command_kinds_map_to_ops(self):
        score = score_ok(
            base_document(
                ticks=16,
                commands=[
                    {"at": 0, "type": kind, "value": 50}
                    for kind in COMMAND_TYPES
                    if kind not in ("set_tempo", "add_tempo", "set_volume")
                ]
                + [
                    {"at": 0, "type": "set_tempo", "value": 50},
                    {"at": 0, "type": "add_tempo", "value": 1},
                    {"at": 0, "type": "set_volume", "value": 120},
                ],
            )
        )
        lowered = lower(score)
        emitted = {op.op for op in lowered.ops_for_channel("pulse0")}
        for kind in COMMAND_TYPES:
            self.assertIn(kind, emitted, kind)


class SlotCollisionTests(unittest.TestCase):
    def test_same_slot_overlap_is_a_diagnostic(self):
        obj = base_document(
            effects=[
                {"at": 0, "type": "arpeggio", "offsets": [4], "period": 2, "until": 8},
                {"at": 4, "type": "arpeggio", "offsets": [5], "period": 2},
            ],
        )
        _, diagnostics = validate_obj(obj)
        self.assertIn("EFFECT_OVERLAP", codes(diagnostics))
        self.assertIn("/patterns/p/effects/1", paths(diagnostics))

    def test_arpeggio_and_note_cut_share_the_retrig_slot(self):
        obj = base_document(
            effects=[
                {"at": 0, "type": "arpeggio", "offsets": [4], "period": 2, "until": 8},
                {"at": 4, "type": "note_cut", "period": 2},
            ],
        )
        _, diagnostics = validate_obj(obj)
        self.assertIn("EFFECT_OVERLAP", codes(diagnostics))

    def test_distinct_slots_may_share_a_tick(self):
        obj = base_document(
            effects=[
                {"at": 0, "type": "lfo", "mode": "tremolo", "depth": 4, "period": 2},
                {"at": 0, "type": "glissando", "period": 2, "direction": "up"},
            ],
        )
        score = score_ok(obj)
        lowered = lower(score)
        tick_zero = [
            op.op for op in lowered.ops_for_channel("pulse0") if op.tick == 0
        ]
        # Both ON ops sit after the clock tempo and before the note attack.
        self.assertIn("lfo_on", tick_zero)
        self.assertIn("glissando_on", tick_zero)
        self.assertLess(tick_zero.index("lfo_on"), tick_zero.index("note"))


class TrackChannelFamilyTests(unittest.TestCase):
    def _doc(self, effect, channel):
        return {
            "format": "atmlib-score",
            "version": 1,
            "id": "family",
            "clock": {"tick_rate": 50, "ticks_per_beat": 25, "beats_per_bar": 4},
            "instruments": {
                "lead": {"voice": "pulse", "volume": 80, "duty": 127},
                "hat": {"voice": "noise", "volume": 30},
            },
            "patterns": {"p": {"ticks": 8, "events": [], "effects": [effect]}},
            "tracks": {channel: [{"pattern": "p", "repeat": 1}]},
        }

    def test_pulse_effect_on_noise_reuse_is_a_diagnostic(self):
        _, diagnostics = validate_obj(
            self._doc({"at": 0, "type": "lfo", "mode": "tremolo", "depth": 4, "period": 2}, "noise")
        )
        self.assertIn("EFFECT_CHANNEL_MISMATCH", codes(diagnostics))
        self.assertIn("/tracks/noise/0/pattern", paths(diagnostics))

    def test_noise_effect_on_pulse_reuse_is_a_diagnostic(self):
        _, diagnostics = validate_obj(
            self._doc({"at": 0, "type": "noise_retrig", "period": 1, "note": "C3"}, "pulse0")
        )
        self.assertIn("EFFECT_CHANNEL_MISMATCH", codes(diagnostics))
        self.assertIn("/tracks/pulse0/0/pattern", paths(diagnostics))

    def test_matching_effect_family_is_accepted(self):
        for effect, channel in (
            ({"at": 0, "type": "lfo", "mode": "tremolo", "depth": 4, "period": 2}, "pulse1"),
            ({"at": 0, "type": "noise_retrig", "period": 1, "note": "C3"}, "noise"),
        ):
            with self.subTest(effect=effect["type"], channel=channel):
                score, diagnostics = validate_obj(self._doc(effect, channel))
                self.assertEqual(diagnostics, [], codes(diagnostics))
                self.assertIsNotNone(score)


class FeatureAndPayloadTests(unittest.TestCase):
    EFFECT_FREE = [
        "notes",
        "rests",
        "finite_pattern_reuse",
        "finite_arrangement",
        "pulse_duty",
        "fixed_instrument_volume",
        "explicit_gate_mute",
    ]

    def test_effect_free_features_are_unchanged(self):
        score = score_ok(base_document())
        self.assertEqual(required_features(score, lower(score)), self.EFFECT_FREE)

    def test_effect_and_command_features_are_additive(self):
        score = score_ok(
            base_document(
                ticks=16,
                effects=[
                    {"at": 0, "type": "lfo", "mode": "tremolo", "depth": 4, "period": 2},
                    {"at": 6, "type": "glissando", "period": 2, "direction": "up"},
                ],
                commands=[
                    {"at": 1, "type": "set_tempo", "value": 60},
                    {"at": 2, "type": "cue", "value": 3},
                ],
            )
        )
        features = required_features(score, lower(score))
        self.assertEqual(features[: len(self.EFFECT_FREE)], self.EFFECT_FREE)
        self.assertEqual(
            features[len(self.EFFECT_FREE):],
            ["effect_lfo", "effect_glissando", "command_set_tempo", "command_cue"],
        )
        # Ordering follows the canonical kind tables.
        self.assertLess(list(EFFECT_TYPES).index("lfo"), list(EFFECT_TYPES).index("glissando"))

    def test_effect_free_review_payload_omits_new_keys(self):
        score = score_ok(base_document())
        payload = build_review_payload(score, lower(score))
        self.assertNotIn("effects", payload)
        self.assertNotIn("commands", payload)
        self.assertEqual(
            set(payload),
            {
                "payload",
                "payload_version",
                "tool",
                "engine",
                "source",
                "clock",
                "total_ticks",
                "channels",
                "notes",
                "pattern_instances",
                "event_digest",
                "diagnostics",
                "capabilities",
            },
        )

    def test_effect_free_review_matches_the_frozen_golden_bytes(self):
        with open(FIXTURE_SONG, "rb") as handle:
            raw = handle.read()
        parsed = parse_json_bytes(raw)
        score, diagnostics = validate_document(
            parsed.document,
            source_path=GOLDEN_SOURCE_PATH,
            raw_bytes=raw,
            parsed=parsed,
        )
        assert score is not None, diagnostics
        with open(FIXTURE_REVIEW, "rb") as handle:
            golden = handle.read()
        self.assertEqual(serialize_review(build_review_payload(score, lower(score))), golden)

    def test_payload_carries_spans_with_source_pointers(self):
        score = score_ok(
            base_document(
                ticks=16,
                effects=[
                    {"at": 0, "type": "lfo", "mode": "tremolo", "depth": 4, "period": 2, "until": 8}
                ],
                commands=[{"at": 4, "type": "cue", "value": 9}],
            )
        )
        payload = build_review_payload(score, lower(score))
        (effect,) = payload["effects"]
        self.assertEqual(effect["source"], "/patterns/p/effects/0")
        self.assertEqual(effect["kind"], "lfo")
        self.assertEqual((effect["start_tick"], effect["end_tick"]), (0, 8))
        self.assertEqual(effect["params"]["mode"], "tremolo")
        (command,) = payload["commands"]
        self.assertEqual(command["source"], "/patterns/p/commands/0")
        self.assertEqual((command["start_tick"], command["end_tick"]), (4, 4))
        self.assertEqual(command["params"], {"value": 9})

    def test_canonical_digest_is_deterministic_and_effect_sensitive(self):
        plain = score_ok(base_document())
        effect = score_ok(
            base_document(
                effects=[{"at": 0, "type": "lfo", "mode": "tremolo", "depth": 4, "period": 2}]
            )
        )
        a = lower(effect)
        b = lower(effect)
        self.assertEqual(a.event_digest, b.event_digest)
        self.assertEqual(a.canonical_bytes, b.canonical_bytes)
        self.assertNotEqual(a.event_digest["hex"], lower(plain).event_digest["hex"])
        self.assertTrue(any(event["op"] == "lfo_on" for event in a.canonical_events))


if __name__ == "__main__":
    unittest.main()
