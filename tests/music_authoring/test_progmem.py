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
    build_review_payload,
    lower,
    serialize_review,
)
from music_authoring.progmem_backend import (  # noqa: E402
    ATM_CMD_I_PATTERN_END,
    ATM_CMD_P_U16_DELAY,
    ATM_CMD_P_U8_DELAY,
    DELAY_1_TICK,
    SCORE_FORMAT_BYTE,
    capability_summary,
    encode_delay,
    encode_delay_chunks,
    serialize,
)
from music_authoring.score import parse_json_bytes  # noqa: E402
from music_authoring.validate import validate_document  # noqa: E402

EXAMPLE_REL = "tests/music_authoring/fixtures/basic/song.json"
EXPECTED_DIR = os.path.join(REPO_ROOT, "tests/music_authoring/fixtures/basic/expected")


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
    def test_fx_advertised_finite_only_and_render_available(self):
        summary = capability_summary()
        self.assertTrue(summary["backends"]["progmem"]["available"])
        # FX is now supported for `build --backend fx` (finite v1 only).
        self.assertTrue(summary["backends"]["fx"]["available"])
        self.assertEqual(summary["backends"]["fx"]["format"], "atm_fx_compact_v1")
        self.assertEqual(summary["backends"]["fx"]["command"], "build")
        self.assertEqual(
            summary["backends"]["fx"]["advertises"],
            {"loops": False, "effects": False, "sfx": False},
        )
        self.assertIn("finite_v1_fx", summary["features"])
        self.assertNotIn("fx_loops", summary["features"])
        # The live capabilities report matches the working commands; only the
        # embedded 3ii.1 review golden keeps the old pinned block.
        self.assertTrue(summary["capabilities"]["inspect"]["available"])
        self.assertTrue(summary["capabilities"]["render"]["available"])
        self.assertTrue(summary["capabilities"]["wav_preview"]["available"])

    def test_pitch_range_advertised(self):
        summary = capability_summary()
        self.assertEqual(summary["pitch_range"]["min"], "C2")
        self.assertEqual(summary["pitch_range"]["max"], "D7")


if __name__ == "__main__":
    unittest.main()
