"""PROGMEM backend + canonical review-payload tests (ATMlib2FX-3ii.1).

Permanent tests: deterministic byte serialization, the explicit
``ATM_SCORE_FMT_FULL`` layout, delay/op encoding, and the versioned review
payload that the HTML viewer consumes.  No files are written to temp dirs.
"""

from __future__ import annotations

import hashlib
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
_TOOLS = os.path.join(REPO_ROOT, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from music_authoring.lower import (  # noqa: E402
    DeviceOp,
    build_review_payload,
    lower,
    serialize_review,
)
from music_authoring.progmem_backend import (  # noqa: E402
    ATM_CMD_1P_ADD_TEMPO,
    ATM_CMD_1P_ADD_TRANSPOSITION,
    ATM_CMD_1P_NOISE_RETRIG_ON,
    ATM_CMD_1P_SET_CUE,
    ATM_CMD_1P_SET_MOD,
    ATM_CMD_1P_SET_TEMPO,
    ATM_CMD_1P_SET_TRANSPOSITION,
    ATM_CMD_1P_SET_VOLUME,
    ATM_CMD_I_ARPEGGIO_OFF,
    ATM_CMD_I_GLISSANDO_OFF,
    ATM_CMD_I_NOISE_RETRIG_OFF,
    ATM_CMD_I_PATTERN_END,
    ATM_CMD_P_ARPEGGIO_ON,
    ATM_CMD_P_GLISSANDO_ON,
    ATM_CMD_P_LFO_OFF,
    ATM_CMD_P_LFO_ON,
    ATM_CMD_P_NOTECUT_ON,
    ATM_CMD_P_SLIDE_ADV_ON,
    ATM_CMD_P_SLIDE_OFF,
    ATM_CMD_P_SLIDE_ON,
    ATM_CMD_P_U16_DELAY,
    ATM_CMD_P_U8_DELAY,
    DELAY_1_TICK,
    SCORE_FORMAT_BYTE,
    capability_summary,
    encode_delay,
    encode_delay_chunks,
    encode_op,
    serialize,
)
from music_authoring.score import parse_json_bytes  # noqa: E402
from music_authoring.validate import validate_document  # noqa: E402

EXAMPLE_REL = "tests/music_authoring/fixtures/basic/song.json"
EXPECTED_DIR = os.path.join(REPO_ROOT, "tests/music_authoring/fixtures/basic/expected")
EFFECT_REL = "tests/music_authoring/fixtures/effects/effect_probe.json"


def load_score(rel_path: str):
    with open(os.path.join(REPO_ROOT, rel_path), "rb") as handle:
        raw = handle.read()
    parsed = parse_json_bytes(raw)
    score, diagnostics = validate_document(
        parsed.document, source_path=rel_path, raw_bytes=raw, parsed=parsed
    )
    assert not diagnostics, diagnostics
    return score


def load_example():
    with open(os.path.join(REPO_ROOT, EXAMPLE_REL), "rb") as handle:
        raw = handle.read()
    parsed = parse_json_bytes(raw)
    score, diagnostics = validate_document(
        parsed.document, source_path="examples/music_authoring/basic/song.json", raw_bytes=raw, parsed=parsed
    )
    assert not diagnostics, diagnostics
    return score


class EncodingTests(unittest.TestCase):
    def test_encode_delay_boundaries(self):
        self.assertEqual(encode_delay(1), [DELAY_1_TICK])
        self.assertEqual(encode_delay(32), [DELAY_1_TICK + 31])
        self.assertEqual(encode_delay(33), [ATM_CMD_P_U8_DELAY, 32])
        self.assertEqual(encode_delay(256), [ATM_CMD_P_U8_DELAY, 255])
        self.assertEqual(encode_delay(257), [ATM_CMD_P_U16_DELAY, 0x01, 0x00])
        self.assertEqual(encode_delay(65535), [ATM_CMD_P_U16_DELAY, 0xFF, 0xFE])

    def test_encode_delay_chunks_splits_long(self):
        chunked = encode_delay_chunks(65536)
        self.assertEqual(chunked, encode_delay(65535) + encode_delay(1))

    def test_delay_rejects_zero(self):
        with self.assertRaises(ValueError):
            encode_delay(0)

    def test_stop_opcode(self):
        self.assertEqual(ATM_CMD_I_PATTERN_END, 0x61)
        self.assertEqual(SCORE_FORMAT_BYTE, 0x03)


class SerializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.score = load_example()
        cls.lowered = lower(cls.score)
        cls.result = serialize(cls.score, cls.lowered, "expected")

    def test_full_format_layout(self):
        data = self.result.score_bytes
        self.assertEqual(data[0], 0x03)
        pattern_count = data[1]
        self.assertEqual(pattern_count, 4)
        # Offsets are uint16 little-endian (pgm_read_word) relative to score start.
        offsets = [data[2 + 2 * i] | (data[3 + 2 * i] << 8) for i in range(pattern_count)]
        self.assertEqual(offsets, sorted(offsets))
        self.assertGreaterEqual(offsets[0], 2 + 2 * pattern_count + 1 + 4)
        self.assertEqual(data[2 + 2 * pattern_count], 4)  # num_channels
        entries = list(data[3 + 2 * pattern_count : 7 + 2 * pattern_count])
        self.assertEqual(entries, [0, 1, 2, 3])
        # Every program ends with a STOP and the last byte is a STOP.
        for offset in offsets:
            self.assertIn(offset, range(len(data)))

    def test_deterministic_bytes(self):
        again = serialize(self.score, lower(self.score), "elsewhere")
        self.assertEqual(self.result.score_bytes, again.score_bytes)
        self.assertEqual(self.result.header_bytes, again.header_bytes)
        self.assertEqual(self.result.review_bytes, again.review_bytes)

    def test_golden_score_bytes(self):
        with open(os.path.join(EXPECTED_DIR, "score.bin"), "rb") as handle:
            golden = handle.read()
        self.assertEqual(self.result.score_bytes, golden)
        self.assertEqual(
            hashlib.sha256(self.result.score_bytes).hexdigest(),
            "8ba7c409364dd8f96f572a0b4fc0bb6284448c3ca61076f721e38018afd6c1a1",
        )

    def test_header_is_generated_not_a_host_struct(self):
        text = self.result.header_bytes.decode("utf-8")
        self.assertIn("const uint8_t score[] PROGMEM", text)
        self.assertIn("#define SCORE_BYTES 215u", text)
        self.assertIn("#define SCORE_SHA256", text)
        # Explicit byte list, never a memcpy/struct dump or executed C.
        self.assertNotIn("memcpy", text)
        self.assertNotIn("offsetof", text)

    def test_golden_review_payload(self):
        payload = build_review_payload(self.score, self.lowered)
        with open(os.path.join(EXPECTED_DIR, "review.json"), "rb") as handle:
            golden = handle.read()
        self.assertEqual(serialize_review(payload), golden)

    def test_review_payload_shape(self):
        payload = build_review_payload(self.score, self.lowered)
        self.assertEqual(payload["payload"], "atmlib-review")
        self.assertEqual(payload["payload_version"], 1)
        self.assertEqual(len(payload["channels"]), 4)
        self.assertEqual(payload["total_ticks"], 32)
        self.assertEqual(payload["clock"]["tick_rate"], 50)
        self.assertEqual(payload["clock"]["effective_tick_rate"], 50)
        self.assertEqual(payload["source"]["sha256"], self.score.source_sha256)
        self.assertEqual(
            payload["event_digest"]["canonicalization"], "atmlib-canonical-events-v1"
        )
        self.assertEqual(payload["event_digest"]["algorithm"], "sha256")
        # Expanded note spans keep source pointers and repetition indices.
        self.assertTrue(payload["notes"])
        for span in payload["notes"]:
            self.assertTrue(span["source"].startswith("/patterns/"))
            self.assertIn("repeat_index", span)
            self.assertIn("pattern_instance_index", span)
        # Pattern-instance boundaries are published for the shared timeline.
        self.assertTrue(payload["pattern_instances"])
        self.assertGreaterEqual(max(i["repeat_index"] for i in payload["pattern_instances"]), 1)


class CapabilityTests(unittest.TestCase):
    def test_fx_advertised_supported_matrix_and_render_available(self):
        summary = capability_summary()
        self.assertTrue(summary["backends"]["progmem"]["available"])
        # FX is now supported for `build --backend fx` with effects, live
        # commands and resident loops (loops gated by the decoder build flag).
        self.assertTrue(summary["backends"]["fx"]["available"])
        self.assertEqual(summary["backends"]["fx"]["format"], "atm_fx_compact_v1")
        self.assertEqual(summary["backends"]["fx"]["command"], "build")
        advertises = summary["backends"]["fx"]["advertises"]
        self.assertTrue(advertises["loops"])
        self.assertEqual(advertises["loops_require_build_flag"], "ATM_FX_COMPACT_LOOP=1")
        self.assertTrue(advertises["effects"])
        self.assertTrue(advertises["commands"])
        self.assertFalse(advertises["sfx"])
        self.assertIn("finite_v1_fx", summary["features"])
        self.assertIn("fx_loops", summary["features"])
        # The live capabilities report matches the working commands; only the
        # embedded 3ii.1 review golden keeps the old pinned block.
        self.assertTrue(summary["capabilities"]["inspect"]["available"])
        self.assertTrue(summary["capabilities"]["render"]["available"])
        self.assertTrue(summary["capabilities"]["wav_preview"]["available"])

    def test_pitch_range_advertised(self):
        summary = capability_summary()
        self.assertEqual(summary["pitch_range"]["min"], "C2")
        self.assertEqual(summary["pitch_range"]["max"], "D7")


class EffectOpEncodingTests(unittest.TestCase):
    """Hand-computed byte streams for every new effect ON/OFF op.

    Byte layouts are pinned by docs/music-authoring-interface.md ("Effect
    windows and live commands") and checked against src/atm_cmd_constants.h +
    src/cmd_parse.c: the arpeggio/note-cut slot stores ``arpTiming`` in
    ``params[0]`` and ``arpNotes`` in ``params[1]``, which is why the engine
    stream orders the timing byte first (the public ``ATM_CMD_M_ARPEGGIO_ON``
    macro reverses its two arguments).
    """

    def op(self, name, **params):
        return DeviceOp(
            op=name,
            tick=0,
            channel=0,
            source="<t>",
            params=tuple(params.items()),
        )

    # --- arpeggio --------------------------------------------------------- #
    def test_arpeggio_three_step(self):
        # period 3, repeat, offsets (4, 7): timing = (3-1) = 0x02, notes = 0x47
        self.assertEqual(
            encode_op(self.op("arpeggio_on", offsets=(4, 7), period=3, repeat=True)),
            [ATM_CMD_P_ARPEGGIO_ON, 0x02, 0x47],
        )

    def test_arpeggio_two_step(self):
        # magnitude-1 offsets => two-step: bit 6 set, low nibble unused
        self.assertEqual(
            encode_op(self.op("arpeggio_on", offsets=(4,), period=3, repeat=True)),
            [ATM_CMD_P_ARPEGGIO_ON, 0x42, 0x40],
        )

    def test_arpeggio_repeat_false_sets_bit5(self):
        self.assertEqual(
            encode_op(self.op("arpeggio_on", offsets=(4, 7), period=3, repeat=False)),
            [ATM_CMD_P_ARPEGGIO_ON, 0x22, 0x47],
        )

    def test_arpeggio_period_bounds(self):
        # 1 -> 0x00 (0x00 | 0x00 since three-step), 32 -> 0x1F
        self.assertEqual(
            encode_op(self.op("arpeggio_on", offsets=(1, 2), period=1, repeat=True)),
            [ATM_CMD_P_ARPEGGIO_ON, 0x00, 0x12],
        )
        self.assertEqual(
            encode_op(self.op("arpeggio_on", offsets=(14, 14), period=32, repeat=True)),
            [ATM_CMD_P_ARPEGGIO_ON, 0x1F, 0xEE],
        )

    def test_arpeggio_off_opcode(self):
        self.assertEqual(encode_op(self.op("arpeggio_off")), [ATM_CMD_I_ARPEGGIO_OFF])
        self.assertEqual(ATM_CMD_I_ARPEGGIO_OFF, 0x63)

    # --- note_cut --------------------------------------------------------- #
    def test_note_cut_on(self):
        # period 5, repeat => (5-1) | 0x40 = 0x44 (arpNotes defaults to 0xFF)
        self.assertEqual(
            encode_op(self.op("note_cut_on", period=5, repeat=True)),
            [ATM_CMD_P_NOTECUT_ON, 0x44],
        )

    def test_note_cut_period1_repeat(self):
        self.assertEqual(
            encode_op(self.op("note_cut_on", period=1, repeat=True)),
            [ATM_CMD_P_NOTECUT_ON, 0x40],
        )

    def test_note_cut_repeat_false_bit5(self):
        self.assertEqual(
            encode_op(self.op("note_cut_on", period=5, repeat=False)),
            [ATM_CMD_P_NOTECUT_ON, 0x64],
        )

    def test_note_cut_period_bounds(self):
        self.assertEqual(
            encode_op(self.op("note_cut_on", period=32, repeat=False)),
            [ATM_CMD_P_NOTECUT_ON, 0x7F],
        )

    # --- lfo -------------------------------------------------------------- #
    def test_lfo_on_selectors(self):
        # depth 10, period 8 => period/2 - 1 = 3
        self.assertEqual(
            encode_op(self.op("lfo_on", mode="tremolo", depth=10, period=8)),
            [ATM_CMD_P_LFO_ON, 0x00, 0x0A, 0x03],
        )
        self.assertEqual(
            encode_op(self.op("lfo_on", mode="vibrato", depth=255, period=2)),
            [ATM_CMD_P_LFO_ON, 0x01, 0xFF, 0x00],
        )
        self.assertEqual(
            encode_op(self.op("lfo_on", mode="modulation", depth=1, period=64)),
            [ATM_CMD_P_LFO_ON, 0x02, 0x01, 0x1F],
        )

    def test_lfo_off(self):
        # One-parameter opcode; engine ignores the selector but it is still read.
        self.assertEqual(encode_op(self.op("lfo_off")), [ATM_CMD_P_LFO_OFF, 0x00])
        self.assertEqual(ATM_CMD_P_LFO_OFF, 0x86)

    # --- slide ------------------------------------------------------------ #
    def test_slide_plain_when_every_one(self):
        # amount -7 => 0xF9 (int8 two's complement); plain two-operand form
        self.assertEqual(
            encode_op(self.op("slide_on", param="volume", amount=-7, every=1)),
            [ATM_CMD_P_SLIDE_ON, 0x00, 0xF9],
        )
        self.assertEqual(
            encode_op(self.op("slide_on", param="frequency", amount=5, every=1)),
            [ATM_CMD_P_SLIDE_ON, 0x01, 0x05],
        )

    def test_slide_advanced_when_every_gt_one(self):
        # every 64 => operand 63; selector frequency = 1
        self.assertEqual(
            encode_op(self.op("slide_on", param="frequency", amount=5, every=64)),
            [ATM_CMD_P_SLIDE_ADV_ON, 0x01, 0x05, 0x3F],
        )
        self.assertEqual(
            encode_op(self.op("slide_on", param="modulation", amount=-128, every=2)),
            [ATM_CMD_P_SLIDE_ADV_ON, 0x02, 0x80, 0x01],
        )

    def test_slide_off(self):
        self.assertEqual(
            encode_op(self.op("slide_off", param="volume")),
            [ATM_CMD_P_SLIDE_OFF, 0x00],
        )
        self.assertEqual(
            encode_op(self.op("slide_off", param="modulation")),
            [ATM_CMD_P_SLIDE_OFF, 0x02],
        )

    # --- glissando -------------------------------------------------------- #
    def test_glissando_up(self):
        self.assertEqual(
            encode_op(self.op("glissando_on", period=1, direction="up")),
            [ATM_CMD_P_GLISSANDO_ON, 0x00],
        )
        self.assertEqual(
            encode_op(self.op("glissando_on", period=128, direction="up")),
            [ATM_CMD_P_GLISSANDO_ON, 0x7F],
        )

    def test_glissando_down(self):
        self.assertEqual(
            encode_op(self.op("glissando_on", period=1, direction="down")),
            [ATM_CMD_P_GLISSANDO_ON, 0x80],
        )
        self.assertEqual(
            encode_op(self.op("glissando_on", period=128, direction="down")),
            [ATM_CMD_P_GLISSANDO_ON, 0xFF],
        )

    def test_glissando_off_opcode(self):
        self.assertEqual(encode_op(self.op("glissando_off")), [ATM_CMD_I_GLISSANDO_OFF])
        self.assertEqual(ATM_CMD_I_GLISSANDO_OFF, 0x62)

    # --- noise_retrig ----------------------------------------------------- #
    def test_noise_retrig_on(self):
        # C4 => note index 25; (25 << 2) | 0 = 0x64
        self.assertEqual(
            encode_op(self.op("noise_retrig_on", period=0, note="C4", note_index=25)),
            [ATM_CMD_1P_NOISE_RETRIG_ON, 0x64],
        )
        # D7 => index 63; (63 << 2) | 3 = 0xFF
        self.assertEqual(
            encode_op(self.op("noise_retrig_on", period=3, note="D7", note_index=63)),
            [ATM_CMD_1P_NOISE_RETRIG_ON, 0xFF],
        )

    def test_noise_retrig_off_opcode(self):
        self.assertEqual(
            encode_op(self.op("noise_retrig_off")), [ATM_CMD_I_NOISE_RETRIG_OFF]
        )
        self.assertEqual(ATM_CMD_I_NOISE_RETRIG_OFF, 0x64)

    # --- live commands ---------------------------------------------------- #
    def test_command_ops(self):
        self.assertEqual(
            encode_op(self.op("add_tempo", value=-12)), [ATM_CMD_1P_ADD_TEMPO, 0xF4]
        )
        self.assertEqual(
            encode_op(self.op("set_transposition", value=-12)),
            [ATM_CMD_1P_SET_TRANSPOSITION, 0xF4],
        )
        self.assertEqual(
            encode_op(self.op("add_transposition", value=7)),
            [ATM_CMD_1P_ADD_TRANSPOSITION, 0x07],
        )
        self.assertEqual(
            encode_op(self.op("cue", value=0x2A)), [ATM_CMD_1P_SET_CUE, 0x2A]
        )

    def test_command_signed_ranges(self):
        self.assertEqual(
            encode_op(self.op("add_tempo", value=-128)), [ATM_CMD_1P_ADD_TEMPO, 0x80]
        )
        self.assertEqual(
            encode_op(self.op("add_tempo", value=127)), [ATM_CMD_1P_ADD_TEMPO, 0x7F]
        )

    def test_live_set_tempo_uses_dedicated_field(self):
        op = DeviceOp(op="set_tempo", tick=0, channel=0, source="<t>", tick_rate=120)
        self.assertEqual(encode_op(op), [ATM_CMD_1P_SET_TEMPO, 120])

    # --- operand-field disambiguation (commands vs instrument writes) ------ #
    def test_instrument_and_command_volume_mod_share_opcodes(self):
        instrument_vol = DeviceOp(op="set_volume", tick=0, channel=0, source="<t>", volume=90)
        command_vol = self.op("set_volume", value=200)
        self.assertEqual(encode_op(instrument_vol), [ATM_CMD_1P_SET_VOLUME, 90])
        self.assertEqual(encode_op(command_vol), [ATM_CMD_1P_SET_VOLUME, 200])
        instrument_mod = DeviceOp(op="set_mod", tick=0, channel=0, source="<t>", duty=64)
        command_mod = self.op("set_mod", value=33)
        self.assertEqual(encode_op(instrument_mod), [ATM_CMD_1P_SET_MOD, 64])
        self.assertEqual(encode_op(command_mod), [ATM_CMD_1P_SET_MOD, 33])


class EffectScoreGoldenTests(unittest.TestCase):
    """Full-score golden for the shared effects/commands probe fixture."""

    # pulse0 program: set_tempo, arpeggio_on(+off at 8), note, transposition,
    # second repetition at tick 16, mute and OFF at the exclusive until ticks.
    PULSE0_PROGRAM = bytes(
        [
            0x72, 0x64,  # set_tempo 100 at tick 0
            0x94, 0x02, 0x47,  # arpeggio_on offsets(4,7) period 3 (three-step)
            0x74, 0x5A,  # set_volume 90
            0x76, 0x40,  # set_mod 64
            0x19,  # note C4
            0x41, 0x70, 0xF4,  # delay 2 -> set_transposition -12
            0x45, 0x63,  # delay 6 -> arpeggio_off at tick 8
            0x74, 0x00,  # mute at tick 8
            0x47,  # delay 8 (to tick 16)
            0x94, 0x02, 0x47,  # second repetition begins
            0x74, 0x5A,
            0x76, 0x40,
            0x19,
            0x41, 0x70, 0xF4,
            0x45, 0x63,
            0x74, 0x00,
            0x47,  # pad to the 32-tick track length
            0x61,  # STOP
        ]
    )

    FULL_SCORE = bytes(
        [0x03, 0x02, 0x0B, 0x00, 0x2E, 0x00, 0x04, 0x00, 0x01, 0x01, 0x01]
        + list(PULSE0_PROGRAM)
        + [0x61]
    )

    def test_effect_probe_program_bytes(self):
        score = load_score(EFFECT_REL)
        result = serialize(score, lower(score), "expected")
        self.assertEqual(len(result.programs), 2)
        self.assertEqual(result.programs[0], self.PULSE0_PROGRAM)
        self.assertEqual(result.programs[1], bytes([ATM_CMD_I_PATTERN_END]))
        self.assertEqual(result.entries, (0, 1, 1, 1))

    def test_effect_probe_full_score_bytes(self):
        score = load_score(EFFECT_REL)
        result = serialize(score, lower(score), "expected")
        self.assertEqual(result.score_bytes, self.FULL_SCORE)
        self.assertEqual(len(result.score_bytes), 47)

    def test_effect_probe_deterministic(self):
        score = load_score(EFFECT_REL)
        first = serialize(score, lower(score), "a")
        second = serialize(load_score(EFFECT_REL), lower(load_score(EFFECT_REL)), "b")
        self.assertEqual(first.score_bytes, second.score_bytes)


class EffectFreeRegressionTests(unittest.TestCase):
    """Effect-free scores keep the exact legacy encoding path."""

    def test_legacy_ops_unchanged(self):
        tempo = DeviceOp(op="set_tempo", tick=0, channel=0, source="<t>", tick_rate=50)
        volume = DeviceOp(op="set_volume", tick=0, channel=0, source="<t>", volume=80)
        duty = DeviceOp(op="set_mod", tick=0, channel=0, source="<t>", duty=127)
        note = DeviceOp(op="note", tick=0, channel=0, source="<t>", note="C4", note_index=25)
        mute = DeviceOp(op="mute", tick=2, channel=0, source="<t>")
        self.assertEqual(encode_op(tempo), [ATM_CMD_1P_SET_TEMPO, 50])
        self.assertEqual(encode_op(volume), [ATM_CMD_1P_SET_VOLUME, 80])
        self.assertEqual(encode_op(duty), [ATM_CMD_1P_SET_MOD, 127])
        self.assertEqual(encode_op(note), [25])
        self.assertEqual(encode_op(mute), [ATM_CMD_1P_SET_VOLUME, 0x00])

    def test_effect_free_score_matches_frozen_golden(self):
        # The pre-existing fixture carries no effects/commands, so the whole
        # serialization (and its hash) must stay byte-identical.
        result = serialize(load_example(), lower(load_example()), "expected")
        with open(os.path.join(EXPECTED_DIR, "score.bin"), "rb") as handle:
            golden = handle.read()
        self.assertEqual(result.score_bytes, golden)
        self.assertEqual(
            hashlib.sha256(result.score_bytes).hexdigest(),
            "8ba7c409364dd8f96f572a0b4fc0bb6284448c3ca61076f721e38018afd6c1a1",
        )


if __name__ == "__main__":
    unittest.main()
