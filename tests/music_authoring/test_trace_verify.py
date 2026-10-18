"""Effect-aware tick-trace prediction tests (ATMlib2FX-3ii.14.7).

Permanent, co-located unit tests for ``tools/music_authoring/trace_verify.py``:
the per-tick engine-state predictor for scores that use pattern effects and live
commands, and the comparator shared with ``verify_suite.py``.  Cover arpeggio
stepping, note-cut silence windows, effect-off bounds, ``repeat=false``
termination, loop-boundary state carry-over, an effect-free golden trace, and
mismatch reporting.  No files are written to temp directories.
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

from music_authoring.lower import lower  # noqa: E402
from music_authoring.score import parse_json_bytes  # noqa: E402
from music_authoring.trace_verify import (  # noqa: E402
    compare_rows,
    expected_from_notes,
    expected_row_count,
    build_expected,
    note_index_to_phase_inc,
    verify_trace,
)
from music_authoring.validate import validate_document  # noqa: E402

BASIC_SONG = os.path.join(REPO_ROOT, "tests/music_authoring/fixtures/basic/song.json")
BASIC_TRACE = os.path.join(
    REPO_ROOT, "tests/music_authoring/fixtures/basic/trace/expected_trace.csv"
)
EFFECT_PROBE = os.path.join(
    REPO_ROOT, "tests/music_authoring/fixtures/effects/effect_probe.json"
)

C4 = 25  # note index for C4
INC = note_index_to_phase_inc


def load_score(path):
    with open(path, "rb") as handle:
        raw = handle.read()
    parsed = parse_json_bytes(raw)
    score, diagnostics = validate_document(
        parsed.document, source_path=path, raw_bytes=raw, parsed=parsed
    )
    assert score is not None, diagnostics
    return score


def score_ok(obj):
    raw = json.dumps(obj).encode("utf-8")
    score, diagnostics = validate_document(obj, source_path="<memory>", raw_bytes=raw)
    assert score is not None, diagnostics
    return score


def base_document(
    *,
    ticks=8,
    note_at=0,
    note_duration=None,
    effects=None,
    commands=None,
    repeat=1,
    loop=False,
    channel="pulse0",
):
    if note_duration is None:
        note_duration = ticks
    pattern = {
        "ticks": ticks,
        "events": [
            {"at": note_at, "note": "C4", "duration": note_duration, "instrument": "lead"}
        ],
    }
    if effects is not None:
        pattern["effects"] = effects
    if commands is not None:
        pattern["commands"] = commands
    doc = {
        "format": "atmlib-score",
        "version": 1,
        "id": "trace_probe",
        "clock": {"tick_rate": 50, "ticks_per_beat": 25, "beats_per_bar": 4},
        "instruments": {"lead": {"voice": "pulse", "volume": 90, "duty": 64}},
        "patterns": {"p": pattern},
        "tracks": {channel: [{"pattern": "p", "repeat": repeat}]},
    }
    if loop:
        doc["loop"] = True
    return doc


def row_at(expected, tick, channel, field):
    return expected["rows"][tick][channel][field]


def synthesize_rows(expected):
    """Render an expected grid as trace rows (inverse of the predictor)."""
    rows = []
    for tick, cell_row in enumerate(expected["rows"]):
        for channel, cell in enumerate(cell_row):
            rows.append(
                {
                    "tick": str(tick + 1),
                    "channel": str(channel),
                    "tempo": str(cell["tempo"]),
                    "inc": "0x%04x" % cell["inc"],
                    "vol": str(cell["vol"]),
                    "note": str(cell["note"]),
                    "delay": "0x0000",
                    "cvol": str(cell["cvol"]),
                    "cmod": str(cell["cmod"]),
                    "active": "0xf0",
                }
            )
    return rows


class ArpeggioTests(unittest.TestCase):
    """Arpeggio retriggers step through base, base+off0, base+off1."""

    def test_period_three_stepping(self):
        score = score_ok(
            base_document(
                ticks=12,
                note_duration=12,
                effects=[
                    {"at": 0, "type": "arpeggio", "offsets": [4, 7], "period": 3, "until": 12}
                ],
            )
        )
        expected = build_expected(score, lower(score))
        self.assertEqual(expected["mode"], "linear")
        self.assertEqual(len(expected["rows"]), 13)
        incs = [row_at(expected, tick, 0, "inc") for tick in range(13)]
        self.assertEqual(
            incs,
            [INC(C4)] * 3 + [INC(C4 + 4)] * 3 + [INC(C4 + 7)] * 3 + [INC(C4)] * 3 + [INC(C4 + 4)],
        )
        # The note column stays at the base note; arpeggio only moves the phase
        # increment.  The gate mute at tick 12 zeroes the oscillator volume.
        self.assertEqual([row_at(expected, t, 0, "note") for t in range(13)], [C4] * 13)
        self.assertEqual([row_at(expected, t, 0, "vol") for t in range(12)], [90] * 12)
        self.assertEqual(row_at(expected, 12, 0, "vol"), 0)
        self.assertEqual([row_at(expected, t, 0, "cvol") for t in range(12)], [90] * 12)
        self.assertEqual(row_at(expected, 12, 0, "cvol"), 0)

    def test_single_offset_is_a_two_step_cycle(self):
        score = score_ok(
            base_document(
                ticks=8,
                note_duration=8,
                effects=[
                    {"at": 0, "type": "arpeggio", "offsets": [4], "period": 2, "until": 8}
                ],
            )
        )
        expected = build_expected(score, lower(score))
        incs = [row_at(expected, tick, 0, "inc") for tick in range(9)]
        # Two-step: base, base+4, base, base+4, ...
        self.assertEqual(incs, [INC(C4), INC(C4), INC(C4 + 4), INC(C4 + 4)] * 2 + [INC(C4)])


class NoteCutTests(unittest.TestCase):
    """Note cut silences the oscillator but leaves the channel volume."""

    def test_silence_windows_preserve_cvol(self):
        score = score_ok(
            base_document(
                ticks=16,
                note_duration=16,
                effects=[{"at": 0, "type": "note_cut", "period": 4, "until": 16}],
            )
        )
        expected = build_expected(score, lower(score))
        base = INC(C4)
        incs = [row_at(expected, t, 0, "inc") for t in range(17)]
        self.assertEqual(incs, [base] * 4 + [0] * 4 + [base] * 4 + [0] * 4 + [base])
        vols = [row_at(expected, t, 0, "vol") for t in range(17)]
        self.assertEqual(vols, [90] * 4 + [0] * 4 + [90] * 4 + [0] * 4 + [0])
        # cvol (channels[c].vol) is untouched by the note-cut silence.
        cvols = [row_at(expected, t, 0, "cvol") for t in range(17)]
        self.assertEqual(cvols, [90] * 16 + [0])


class EffectOffTests(unittest.TestCase):
    """The OFF op is the exclusive ``until`` tick and freezes the effect."""

    def test_off_is_exclusive_and_freezes_without_cross_window_step(self):
        score = score_ok(
            base_document(
                ticks=16,
                note_duration=16,
                effects=[
                    {"at": 0, "type": "arpeggio", "offsets": [4, 7], "period": 3, "until": 8}
                ],
            )
        )
        lowered = lower(score)
        ops = [
            (op.op, op.tick)
            for op in lowered.ops_for_channel("pulse0")
            if op.op in ("arpeggio_on", "arpeggio_off")
        ]
        self.assertEqual(ops, [("arpeggio_on", 0), ("arpeggio_off", 8)])
        expected = build_expected(score, lowered)
        incs = [row_at(expected, t, 0, "inc") for t in range(17)]
        self.assertEqual(incs[:3], [INC(C4)] * 3)
        self.assertEqual(incs[3:6], [INC(C4 + 4)] * 3)
        # Steps stop at the window end: the last reached note holds to the end.
        self.assertEqual(incs[6:], [INC(C4 + 7)] * 11)

    def test_start_at_nonzero_tick_delays_the_first_step(self):
        score = score_ok(
            base_document(
                ticks=12,
                note_duration=12,
                effects=[
                    {"at": 2, "type": "arpeggio", "offsets": [4, 7], "period": 3, "until": 12}
                ],
            )
        )
        expected = build_expected(score, lower(score))
        incs = [row_at(expected, t, 0, "inc") for t in range(13)]
        # Effect on at tick 2: the first step is at tick 5 (= at + period),
        # then tick 8, then tick 11.
        self.assertEqual(incs[0:5], [INC(C4)] * 5)
        self.assertEqual(incs[5:8], [INC(C4 + 4)] * 3)
        self.assertEqual(incs[8:11], [INC(C4 + 7)] * 3)
        self.assertEqual(incs[11:], [INC(C4)] * 2)


class RepeatFalseTests(unittest.TestCase):
    """``repeat=false`` disables the automatic base re-trigger."""

    def test_repeat_false_ends_with_silence(self):
        score = score_ok(
            base_document(
                ticks=8,
                note_duration=8,
                effects=[
                    {
                        "at": 0,
                        "type": "arpeggio",
                        "offsets": [4, 7],
                        "period": 2,
                        "repeat": False,
                        "until": 8,
                    }
                ],
            )
        )
        expected = build_expected(score, lower(score))
        incs = [row_at(expected, t, 0, "inc") for t in range(9)]
        self.assertEqual(
            incs,
            [INC(C4), INC(C4), INC(C4 + 4), INC(C4 + 4), INC(C4 + 7), INC(C4 + 7), 0, 0, 0],
        )
        vols = [row_at(expected, t, 0, "vol") for t in range(9)]
        self.assertEqual(vols, [90, 90, 90, 90, 90, 90, 0, 0, 0])
        cvols = [row_at(expected, t, 0, "cvol") for t in range(9)]
        self.assertEqual(cvols, [90, 90, 90, 90, 90, 90, 90, 90, 0])

    def test_repeat_true_re_attacks_the_base(self):
        score = score_ok(
            base_document(
                ticks=8,
                note_duration=8,
                effects=[
                    {
                        "at": 0,
                        "type": "arpeggio",
                        "offsets": [4, 7],
                        "period": 2,
                        "repeat": True,
                        "until": 8,
                    }
                ],
            )
        )
        expected = build_expected(score, lower(score))
        incs = [row_at(expected, t, 0, "inc") for t in range(9)]
        self.assertEqual(
            incs,
            [INC(C4), INC(C4), INC(C4 + 4), INC(C4 + 4), INC(C4 + 7), INC(C4 + 7), INC(C4), INC(C4), INC(C4 + 4)],
        )

    def test_repeat_false_note_attack_resets_the_cycle(self):
        # Two notes each with the same repeat=false window: the second attack
        # restarts the arpeggio counter (arpTiming bit 5 resets arpCount).
        doc = base_document(ticks=8, note_duration=2, effects=None)
        doc["patterns"]["p"]["events"] = [
            {"at": 0, "note": "C4", "duration": 2, "instrument": "lead"},
            {"at": 4, "note": "C4", "duration": 2, "instrument": "lead"},
        ]
        doc["patterns"]["p"]["effects"] = [
            {"at": 0, "type": "arpeggio", "offsets": [7], "period": 2, "repeat": False, "until": 8}
        ]
        score = score_ok(doc)
        expected = build_expected(score, lower(score))
        incs = [row_at(expected, t, 0, "inc") for t in range(9)]
        # First note: base (0,1), +7 (2,3); second note re-attacks base at 4.
        self.assertEqual(incs[0:4], [INC(C4), INC(C4), INC(C4 + 7), INC(C4 + 7)])
        self.assertEqual(incs[4], INC(C4))


class LoopBoundaryTests(unittest.TestCase):
    """Looping keeps channel state across the boundary (no reset)."""

    def test_state_carries_when_tick_zero_does_not_re_attack(self):
        score = score_ok(base_document(ticks=4, note_at=1, note_duration=1, loop=True))
        expected = build_expected(score, lower(score))
        self.assertEqual(expected["mode"], "loop")
        self.assertEqual(expected["wrap"], False)
        # 2 cycles + the opening tick of cycle 3.
        self.assertEqual(len(expected["rows"]), 9)
        # Cycle 1 tick 0 has no attack yet.
        self.assertEqual(row_at(expected, 0, 0, "note"), 0)
        self.assertEqual(row_at(expected, 0, 0, "inc"), 0)
        # The note at tick 1; the gate mute at tick 2 zeroes volume but not note.
        self.assertEqual(row_at(expected, 1, 0, "note"), C4)
        self.assertEqual(row_at(expected, 2, 0, "cvol"), 0)
        # Cycle 2 tick 0 carries the previous note/inc because nothing re-attacks.
        self.assertEqual(row_at(expected, 4, 0, "note"), C4)
        self.assertEqual(row_at(expected, 4, 0, "inc"), INC(C4))
        # PATTERN_END zeroed the oscillator volume at the boundary.
        self.assertEqual(row_at(expected, 4, 0, "vol"), 0)
        # The opening tick of cycle 3 carries the same state.
        self.assertEqual(row_at(expected, 8, 0, "note"), C4)


class EffectProbeTests(unittest.TestCase):
    """The shared arpeggio + transposition probe against its documented trace."""

    def test_predicted_inc_sequence_matches_documented_trace(self):
        score = load_score(EFFECT_PROBE)
        lowered = lower(score)
        expected = build_expected(score, lowered)
        self.assertEqual(expected["mode"], "linear")
        self.assertEqual(len(expected["rows"]), 33)
        base = INC(25)
        transposed_base = INC(25 - 12)
        step4 = INC(29 - 12)
        step7 = INC(32 - 12)
        incs = [row_at(expected, t, 0, "inc") for t in range(33)]
        self.assertEqual(
            incs,
            [base] * 3
            + [step4] * 3
            + [step7] * 10
            + [transposed_base] * 3
            + [step4] * 3
            + [step7] * 10
            + [step7],
        )
        # The oscillator volume zeroes at the exclusive arpeggio window (tick 8
        # of each 16-tick repetition) and re-attacks on the repeat.
        self.assertEqual(row_at(expected, 8, 0, "vol"), 0)
        self.assertEqual(row_at(expected, 16, 0, "vol"), 90)
        self.assertEqual(lowered.effect_spans[0].kind, "arpeggio")
        self.assertEqual(
            [event.kind for event in lowered.command_events],
            ["set_transposition", "set_transposition"],
        )

    def test_predictor_round_trips_through_the_comparator(self):
        score = load_score(EFFECT_PROBE)
        expected = build_expected(score, lower(score))
        rows = synthesize_rows(expected)
        self.assertEqual(compare_rows(rows, expected), [])
        self.assertEqual(expected_row_count(expected), len(rows))


class ComparatorTests(unittest.TestCase):
    """The comparator reports per-tick mismatches with expectations."""

    def test_mismatch_reports_field_and_expectation(self):
        score = score_ok(
            base_document(
                ticks=4,
                note_duration=4,
                effects=[
                    {"at": 0, "type": "arpeggio", "offsets": [4, 7], "period": 2, "until": 4}
                ],
            )
        )
        expected = build_expected(score, lower(score))
        rows = synthesize_rows(expected)
        # Corrupt exactly one row's inc (channel 0, song tick 2).
        target = next(r for r in rows if r["tick"] == "3" and r["channel"] == "0")
        target["inc"] = "0x0000"
        mismatches = compare_rows(rows, expected)
        self.assertEqual(len(mismatches), 1)
        mismatch = mismatches[0]
        self.assertEqual(mismatch["tick"], 3)
        self.assertEqual(mismatch["song_tick"], 2)
        self.assertEqual(mismatch["channel"], 0)
        self.assertEqual(mismatch["field"], "inc")
        self.assertEqual(mismatch["actual"], 0)
        self.assertNotEqual(mismatch["expected"], 0)

    def test_field_subset_skips_other_columns(self):
        score = score_ok(base_document(ticks=4, note_duration=4))
        expected = build_expected(score, lower(score))
        rows = synthesize_rows(expected)
        rows[0]["inc"] = "0x0000"  # would be a mismatch for inc...
        self.assertEqual(compare_rows(rows, expected, fields=("cvol", "tempo")), [])
        self.assertEqual(len(compare_rows(rows, expected, fields=("inc",))), 1)

    def test_hex_and_decimal_columns_parse(self):
        score = score_ok(base_document(ticks=2, note_duration=2))
        expected = build_expected(score, lower(score))
        rows = synthesize_rows(expected)
        # Decimal tempo, hex inc, decimal note/cvol/cmod all parse.
        self.assertEqual(compare_rows(rows, expected, fields=("inc", "tempo", "note")), [])


class ExpectedFromNotesTests(unittest.TestCase):
    """The effect-free comparator input shared with verify_suite."""

    def test_grid_matches_effect_free_semantics(self):
        notes = [
            {"channel": 0, "start_tick": 0, "gate_end_tick": 2, "note_index": 25, "volume": 80, "duty": 127},
            {"channel": 3, "start_tick": 1, "gate_end_tick": 3, "note_index": 10, "volume": 90, "duty": None},
        ]
        expected = expected_from_notes(notes, 4, tempo=100)
        self.assertTrue(expected["wrap"])
        self.assertEqual(expected_row_count(expected), (2 * 4 + 1) * 4)
        self.assertEqual(
            expected["rows"][0][0], {"cvol": 80, "tempo": 100, "note": 25, "cmod": 127}
        )
        # Outside the gate: cvol 0, no note/duty keys (skipped by the comparator).
        self.assertEqual(expected["rows"][2][0], {"cvol": 0, "tempo": 100})
        # Noise channel: cmod is never written.
        self.assertNotIn("cmod", expected["rows"][1][3])
        self.assertEqual(expected["rows"][1][3]["note"], 10)

    def test_wrapped_comparator_passes_matching_rows_and_catches_cvol(self):
        notes = [
            {"channel": 0, "start_tick": 0, "gate_end_tick": 2, "note_index": 25, "volume": 80, "duty": 127}
        ]
        expected = expected_from_notes(notes, 4, tempo=100)
        rows = []
        for cycle in range(2):
            for tick in range(4):
                for channel in range(4):
                    cell = expected["rows"][tick % 4][channel]
                    rows.append(
                        {
                            "tick": str(cycle * 4 + tick + 1),
                            "channel": str(channel),
                            "tempo": str(cell["tempo"]),
                            "cvol": str(cell["cvol"]),
                            "note": str(cell.get("note", 0)),
                            "cmod": str(cell.get("cmod", 127)),
                            "inc": "0x0000",
                            "vol": "0",
                            "delay": "0x0000",
                            "active": "0xf0",
                        }
                    )
        fields = ("cvol", "note", "cmod", "tempo")
        self.assertEqual(compare_rows(rows, expected, fields=fields), [])
        rows[0]["cvol"] = "0"  # wrong: the attack sets 80
        mismatches = compare_rows(rows, expected, fields=fields)
        self.assertEqual(len(mismatches), 1)
        self.assertEqual(mismatches[0]["field"], "cvol")
        self.assertEqual(mismatches[0]["expected"], 80)


class GoldenTraceTests(unittest.TestCase):
    """The effect-free fixture still verifies against its frozen trace."""

    def test_basic_fixture_verifies_all_fields(self):
        score = load_score(BASIC_SONG)
        summary = verify_trace(score, lower(score), BASIC_TRACE)
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["mismatch_count"], 0)
        self.assertEqual(summary["mode"], "linear")
        self.assertEqual(summary["actual_rows"], 132)
        self.assertEqual(summary["effect_families"], [])
        self.assertIn("inc", summary["checked_fields"])

    def test_golden_mismatch_demo_catches_a_perturbed_row(self):
        # Reprograms the checker's own prediction: force a wrong expectation
        # and prove the mismatch report names the field and the tick.
        import csv

        with open(BASIC_TRACE, newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        score = load_score(BASIC_SONG)
        expected = build_expected(score, lower(score))
        rows[0]["cvol"] = str(int(rows[0]["cvol"]) + 1)
        rows[0]["note"] = str(int(rows[0]["note"]) + 1)
        mismatches = compare_rows(rows, expected)
        fields = {item["field"] for item in mismatches}
        self.assertEqual(fields, {"cvol", "note"})
        self.assertTrue(all(item["tick"] == 1 for item in mismatches))


if __name__ == "__main__":
    unittest.main()
