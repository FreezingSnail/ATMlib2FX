"""Validation-contract tests for the v1 score format (ATMlib2FX-3ii.1).

These tests are permanent: they cover the package and assert the strict
source contract from docs/music-authoring-interface.md, including stable
diagnostic codes and exact RFC 6901 JSON Pointers.
"""

from __future__ import annotations

import copy
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
    NOTE_MAX_INDEX,
    NOTE_MIN_INDEX,
    note_index,
    note_range_problem,
    parse_json_bytes,
)
from music_authoring.validate import (  # noqa: E402
    load_and_validate,
    validate_document,
)

EXAMPLE_REL = "tests/music_authoring/fixtures/basic/song.json"


def base_score() -> dict:
    return {
        "format": "atmlib-score",
        "version": 1,
        "id": "t",
        "clock": {"tick_rate": 50, "ticks_per_beat": 25, "beats_per_bar": 4},
        "instruments": {"lead": {"voice": "pulse", "volume": 80, "duty": 127}},
        "patterns": {
            "p": {
                "ticks": 8,
                "events": [
                    {"at": 0, "note": "C4", "duration": 2, "instrument": "lead"}
                ],
            }
        },
        "tracks": {"pulse0": [{"pattern": "p", "repeat": 1}]},
    }


def validate_obj(obj: dict):
    raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    parsed = parse_json_bytes(raw)
    return validate_document(parsed.document, source_path="<mem>", raw_bytes=raw, parsed=parsed)


def validate_text(text: str):
    raw = text.encode("utf-8")
    parsed = parse_json_bytes(raw)
    return validate_document(parsed.document, source_path="<mem>", raw_bytes=raw, parsed=parsed)


def codes(diagnostics) -> set:
    return {item.code for item in diagnostics}


def paths(diagnostics) -> list:
    return [item.path for item in diagnostics]


class ValidContractTests(unittest.TestCase):
    def test_example_parses(self):
        score, diagnostics = load_and_validate(os.path.join(REPO_ROOT, EXAMPLE_REL))
        self.assertEqual(diagnostics, [])
        self.assertIsNotNone(score)
        self.assertEqual(score.id, "basic_authoring_v1")
        self.assertEqual(score.clock.tick_rate, 50)
        self.assertEqual(score.clock.effective_tick_rate, 50)
        self.assertAlmostEqual(score.clock.effective_bpm, 120.0)
        self.assertEqual(set(score.tracks), {"pulse0", "pulse1", "pulse2", "noise"})

    def test_minimal_valid_document(self):
        score, diagnostics = validate_obj(base_score())
        self.assertEqual(diagnostics, [])
        self.assertIsNotNone(score)

    def test_note_range_and_index(self):
        self.assertEqual(note_range_problem("C2"), (None, NOTE_MIN_INDEX))
        self.assertEqual(note_range_problem("D7"), (None, NOTE_MAX_INDEX))
        self.assertEqual(note_index("C4"), 25)
        self.assertEqual(note_range_problem("E7")[0], "PITCH_RANGE")
        self.assertEqual(note_range_problem("C1")[0], "PITCH_RANGE")
        self.assertEqual(note_range_problem("Db4")[0], "INVALID_NOTE")

    def test_effective_tick_rate_quantization(self):
        score = base_score()
        score["clock"]["tick_rate"] = 255
        parsed, diagnostics = validate_obj(score)
        self.assertEqual(diagnostics, [])
        # 2000 // (2000 // 255) = 2000 // 7 = 285
        self.assertEqual(parsed.clock.effective_tick_rate, 285)


class StructuralRejectionTests(unittest.TestCase):
    def test_duplicate_key(self):
        _, diagnostics = validate_text('{"format":"atmlib-score","format":"x"}')
        self.assertIn("DUPLICATE_KEY", codes(diagnostics))
        self.assertIn("/format", paths(diagnostics))

    def test_unknown_field(self):
        obj = base_score()
        obj["tempo_bpm"] = 120
        _, diagnostics = validate_obj(obj)
        self.assertIn("UNKNOWN_FIELD", codes(diagnostics))
        self.assertIn("/tempo_bpm", paths(diagnostics))

    def test_wrong_type(self):
        obj = base_score()
        obj["version"] = "1"
        _, diagnostics = validate_obj(obj)
        self.assertIn("TYPE_MISMATCH", codes(diagnostics))
        self.assertIn("/version", paths(diagnostics))

    def test_float_where_integer(self):
        obj = base_score()
        obj["clock"]["tick_rate"] = 50.0
        _, diagnostics = validate_obj(obj)
        self.assertIn("TYPE_MISMATCH", codes(diagnostics))
        self.assertIn("/clock/tick_rate", paths(diagnostics))

    def test_missing_required_clock(self):
        obj = base_score()
        del obj["clock"]
        _, diagnostics = validate_obj(obj)
        self.assertIn("MISSING_FIELD", codes(diagnostics))
        self.assertIn("/clock", paths(diagnostics))

    def test_bad_identifier(self):
        obj = base_score()
        obj["id"] = "1bad"
        _, diagnostics = validate_obj(obj)
        self.assertIn("INVALID_IDENTIFIER", codes(diagnostics))
        self.assertIn("/id", paths(diagnostics))

    def test_unsupported_version(self):
        obj = base_score()
        obj["version"] = 2
        _, diagnostics = validate_obj(obj)
        self.assertIn("UNSUPPORTED_VERSION", codes(diagnostics))
        self.assertIn("/version", paths(diagnostics))

    def test_clock_out_of_range(self):
        obj = base_score()
        obj["clock"]["tick_rate"] = 4
        _, diagnostics = validate_obj(obj)
        self.assertIn("VALUE_RANGE", codes(diagnostics))
        self.assertIn("/clock/tick_rate", paths(diagnostics))

    def test_non_finite_rejected(self):
        text = (
            '{"format":"atmlib-score","version":1,"id":"t",'
            '"clock":{"tick_rate":NaN,"ticks_per_beat":25,"beats_per_bar":4},'
            '"instruments":{"lead":{"voice":"pulse","volume":80,"duty":127}},'
            '"patterns":{"p":{"ticks":8,"events":[]}},'
            '"tracks":{"pulse0":[{"pattern":"p","repeat":1}]}}'
        )
        _, diagnostics = validate_text(text)
        self.assertIn("TYPE_MISMATCH", codes(diagnostics))


class SemanticRejectionTests(unittest.TestCase):
    def test_pitch_out_of_range_pointer(self):
        obj = base_score()
        obj["patterns"]["p"]["events"] = [
            {"at": 0, "note": "E7", "duration": 2, "instrument": "lead"}
        ]
        _, diagnostics = validate_obj(obj)
        self.assertIn("PITCH_RANGE", codes(diagnostics))
        self.assertIn("/patterns/p/events/0/note", paths(diagnostics))

    def test_invalid_note(self):
        obj = base_score()
        obj["patterns"]["p"]["events"] = [
            {"at": 0, "note": "H4", "duration": 2, "instrument": "lead"}
        ]
        _, diagnostics = validate_obj(obj)
        self.assertIn("INVALID_NOTE", codes(diagnostics))
        self.assertIn("/patterns/p/events/0/note", paths(diagnostics))

    def test_event_overlap(self):
        obj = base_score()
        obj["patterns"]["p"]["events"] = [
            {"at": 0, "note": "C4", "duration": 4, "instrument": "lead"},
            {"at": 2, "note": "D4", "duration": 2, "instrument": "lead"},
        ]
        _, diagnostics = validate_obj(obj)
        self.assertIn("EVENT_OVERLAP", codes(diagnostics))

    def test_event_outside_pattern(self):
        obj = base_score()
        obj["patterns"]["p"]["events"] = [
            {"at": 6, "note": "C4", "duration": 4, "instrument": "lead"}
        ]
        _, diagnostics = validate_obj(obj)
        self.assertIn("EVENT_OUTSIDE_PATTERN", codes(diagnostics))
        self.assertIn("/patterns/p/events/0/duration", paths(diagnostics))

    def test_event_order(self):
        obj = base_score()
        obj["patterns"]["p"]["events"] = [
            {"at": 4, "note": "C4", "duration": 2, "instrument": "lead"},
            {"at": 2, "note": "D4", "duration": 2, "instrument": "lead"},
        ]
        _, diagnostics = validate_obj(obj)
        self.assertIn("EVENT_ORDER", codes(diagnostics))

    def test_unknown_instrument(self):
        obj = base_score()
        obj["patterns"]["p"]["events"][0]["instrument"] = "nope"
        _, diagnostics = validate_obj(obj)
        self.assertIn("UNKNOWN_INSTRUMENT", codes(diagnostics))
        self.assertIn("/patterns/p/events/0/instrument", paths(diagnostics))

    def test_unknown_pattern(self):
        obj = base_score()
        obj["tracks"]["pulse0"] = [{"pattern": "nope", "repeat": 1}]
        _, diagnostics = validate_obj(obj)
        self.assertIn("UNKNOWN_PATTERN", codes(diagnostics))
        self.assertIn("/tracks/pulse0/0/pattern", paths(diagnostics))

    def test_unknown_track(self):
        obj = base_score()
        obj["tracks"]["triangle"] = [{"pattern": "p", "repeat": 1}]
        _, diagnostics = validate_obj(obj)
        self.assertIn("UNKNOWN_TRACK", codes(diagnostics))

    def test_voice_channel_mismatch(self):
        obj = base_score()
        obj["instruments"]["drum"] = {"voice": "noise", "volume": 90}
        obj["patterns"]["p"]["events"] = [
            {"at": 0, "note": "A2", "duration": 2, "instrument": "drum"}
        ]
        obj["tracks"] = {"pulse0": [{"pattern": "p", "repeat": 1}]}
        _, diagnostics = validate_obj(obj)
        self.assertIn("VOICE_CHANNEL_MISMATCH", codes(diagnostics))
        self.assertIn("/tracks/pulse0/0/pattern", paths(diagnostics))

    def test_pattern_mixing_voices_rejected(self):
        obj = base_score()
        obj["instruments"]["drum"] = {"voice": "noise", "volume": 90}
        obj["patterns"]["p"]["events"] = [
            {"at": 0, "note": "C4", "duration": 2, "instrument": "lead"},
            {"at": 2, "note": "A2", "duration": 2, "instrument": "drum"},
        ]
        _, diagnostics = validate_obj(obj)
        self.assertIn("VOICE_CHANNEL_MISMATCH", codes(diagnostics))

    def test_instrument_limit(self):
        obj = base_score()
        obj["instruments"] = {
            f"i{n:02d}": {"voice": "pulse", "volume": 80, "duty": 100}
            for n in range(65)
        }
        _, diagnostics = validate_obj(obj)
        self.assertIn("LIMIT_EXCEEDED", codes(diagnostics))
        self.assertIn("/instruments", paths(diagnostics))

    def test_noise_instrument_rejects_duty(self):
        obj = base_score()
        obj["instruments"]["drum"] = {"voice": "noise", "volume": 90, "duty": 10}
        _, diagnostics = validate_obj(obj)
        self.assertIn("UNKNOWN_FIELD", codes(diagnostics))

    def test_missing_track(self):
        obj = base_score()
        obj["tracks"] = {}
        _, diagnostics = validate_obj(obj)
        self.assertIn("EMPTY_TRACK", codes(diagnostics))


if __name__ == "__main__":
    unittest.main()
