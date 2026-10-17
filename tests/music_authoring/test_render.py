"""Bounded WAV preview tests (ATMlib2FX-3ii.2).

Permanent tests for the render CLI contract that do not require AVR/absim:
validation/error/exit-code behaviour, duration bounds, WAV structure parsing,
canonical source/event digest identity and render-report assembly.

The full real-AVR capture is exercised separately (and gated by
``ATMLIB_AVR_PREVIEW=1``) because it invokes arduino-cli and the absim emulator.
No files are written to temp dirs.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import struct
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
_TOOLS = os.path.join(REPO_ROOT, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from music_authoring import cli  # noqa: E402
from music_authoring.lower import build_review_payload, lower  # noqa: E402
from music_authoring.render import (  # noqa: E402
    DEFAULT_SECONDS,
    MAX_SECONDS,
    NEUTRAL_LEVEL,
    SAMPLE_RATE,
    RenderError,
    analyze_capture,
    build_render_report,
    compare_source_identity,
    decode_samples,
    duration_plan,
    gate_timeline,
    parse_wav_bytes,
)
from music_authoring.validate import load_and_validate  # noqa: E402

EXAMPLE_REL = "tests/music_authoring/fixtures/basic/song.json"
REVIEW_REL = "tests/music_authoring/fixtures/basic/expected/review.json"


def _make_wav(samples: list[int], rate: int = SAMPLE_RATE, channels: int = 1, bits: int = 16) -> bytes:
    data = struct.pack(f"<{len(samples)}h", *samples)
    block_align = channels * bits // 8
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, rate, rate * block_align, block_align, bits)
    header += b"data" + struct.pack("<I", len(data))
    return header + data


class DurationPlanTests(unittest.TestCase):
    def test_default_is_bounded_and_not_truncated_for_short_song(self):
        plan = duration_plan(total_ticks=32, effective_tick_rate=50, seconds=None)
        self.assertEqual(plan["requested_seconds"], DEFAULT_SECONDS)
        self.assertFalse(plan["truncated"])
        self.assertAlmostEqual(plan["effective_render_seconds"], 0.64 + 0.5, places=6)

    def test_rejects_over_hard_max(self):
        with self.assertRaises(RenderError) as ctx:
            duration_plan(32, 50, MAX_SECONDS + 1)
        self.assertEqual(ctx.exception.code, "DURATION_CAP")
        self.assertEqual(ctx.exception.exit_code, 2)

    def test_rejects_nonpositive(self):
        for bad in (0.0, -3.0):
            with self.assertRaises(RenderError) as ctx:
                duration_plan(32, 50, bad)
            self.assertEqual(ctx.exception.code, "DURATION_CAP")

    def test_reports_truncation_when_window_shorter_than_song(self):
        # 600 ticks at 50 Hz = 12 s song; 1 s window truncates it.
        plan = duration_plan(total_ticks=600, effective_tick_rate=50, seconds=1.0)
        self.assertTrue(plan["truncated"])
        self.assertIn("1", plan["truncation_reason"])
        self.assertEqual(plan["render_ms"], 1000)

    def test_max_seconds_is_300(self):
        self.assertEqual(MAX_SECONDS, 300.0)


class WavStructureTests(unittest.TestCase):
    def test_valid_wav_roundtrip(self):
        samples = [0, 100, -100, 2000, -2000, 0]
        info = parse_wav_bytes(_make_wav(samples))
        self.assertEqual(info["format"]["channels"], 1)
        self.assertEqual(info["format"]["sample_rate"], SAMPLE_RATE)
        self.assertEqual(info["format"]["bits_per_sample"], 16)
        self.assertEqual(info["frames"], len(samples))
        self.assertEqual(decode_samples(_make_wav(samples)), samples)

    def test_rejects_non_riff(self):
        with self.assertRaises(RenderError) as ctx:
            parse_wav_bytes(b"NOTAWAVE" + b"\x00" * 64)
        self.assertEqual(ctx.exception.code, "WAV_INVALID")

    def test_rejects_short_data(self):
        good = _make_wav([1, 2, 3, 4])
        with self.assertRaises(RenderError) as ctx:
            parse_wav_bytes(good[:-4])
        self.assertEqual(ctx.exception.code, "WAV_TRUNCATED")

    def test_rejects_non_16_bit(self):
        with self.assertRaises(RenderError) as ctx:
            decode_samples(_make_wav([0, 0], bits=8))
        self.assertEqual(ctx.exception.code, "WAV_FORMAT")


class SourceIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.score, diagnostics = load_and_validate(os.path.join(REPO_ROOT, EXAMPLE_REL))
        assert cls.score is not None, diagnostics
        cls.lowered = lower(cls.score)
        cls.payload = build_review_payload(cls.score, cls.lowered)
        with open(os.path.join(REPO_ROOT, REVIEW_REL), "r", encoding="utf-8") as handle:
            cls.canonical = json.load(handle)

    def test_matches_canonical_review(self):
        self.assertEqual(compare_source_identity(self.payload, self.canonical), [])

    def test_rejects_source_mismatch(self):
        stale = json.loads(json.dumps(self.canonical))
        stale["source"]["sha256"] = "0" * 64
        codes = [d.code for d in compare_source_identity(self.payload, stale)]
        self.assertIn("SOURCE_DIGEST_MISMATCH", codes)

    def test_rejects_event_mismatch(self):
        stale = json.loads(json.dumps(self.canonical))
        stale["event_digest"]["hex"] = "f" * 64
        codes = [d.code for d in compare_source_identity(self.payload, stale)]
        self.assertIn("EVENT_DIGEST_MISMATCH", codes)


class AnalyzeCaptureTests(unittest.TestCase):
    def test_measures_neutral_silence_and_musical_activity(self):
        first_cb = 100
        music_len = int(round(32 / 50 * SAMPLE_RATE))  # 32000 samples
        samples = [0] * first_cb
        samples += [0, 500, -500, 1200, -1200] * (music_len // 5 + 1)
        samples = samples[: first_cb + music_len]
        samples += [-2000] * (SAMPLE_RATE // 4)  # constant DC rail after end
        analysis = analyze_capture(samples, first_cb, 32, 50)
        self.assertEqual(analysis["neutral_level"], NEUTRAL_LEVEL)
        self.assertEqual(analysis["first_music_callback_sample"], first_cb)
        self.assertTrue(analysis["checks"]["pre_music_steady_near_neutral"])
        self.assertTrue(analysis["checks"]["musical_window_active"])
        self.assertTrue(analysis["checks"]["post_end_is_ac_silent"])
        self.assertEqual(analysis["post_end_dc_level"], -2000)


class RenderReportIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.score, diagnostics = load_and_validate(os.path.join(REPO_ROOT, EXAMPLE_REL))
        assert cls.score is not None, diagnostics
        cls.lowered = lower(cls.score)
        cls.payload = build_review_payload(cls.score, cls.lowered)
        cls.plan = duration_plan(cls.lowered.total_ticks, cls.score.clock.effective_tick_rate, 8.0)
        cls.wav = _make_wav([0] * 10)
        cls.info = parse_wav_bytes(cls.wav)
        capture = {
            "first_callback_found": True,
            "first_callback_sample": 1045,
            "first_nonzero_sample": 211,
            "min_sample": -2000,
            "max_sample": 1232,
            "nonzero_samples": 500,
            "samples_data": [0] * 1045 + [10, -10] * 100 + [-2000] * 5000,
        }
        cls.report = build_render_report(
            score=cls.score,
            lowered=cls.lowered,
            review_payload=cls.payload,
            source_identity_diagnostics=[],
            canonical_review_path="expected/review.json",
            plan=cls.plan,
            capture=capture,
            wav_path="preview.wav",
            wav_sha256="deadbeef",
            wav_bytes=len(cls.wav),
            wav_info=cls.info,
            trace_path="tick_trace.csv",
            provenance={"python": "x"},
            cost={"production": {"score_bytes": 215}},
            commands=[{"step": "x", "argv": ["y"]}],
            artifacts={"wav": "preview.wav"},
        )

    def test_identity_matches_frontend_golden(self):
        with open(os.path.join(REPO_ROOT, REVIEW_REL), "r", encoding="utf-8") as handle:
            golden = json.load(handle)
        self.assertEqual(self.report["source"]["sha256"], golden["source"]["sha256"])
        self.assertEqual(self.report["event_digest"]["hex"], golden["event_digest"]["hex"])
        self.assertTrue(self.report["canonical_review"]["matched"])

    def test_audio_metadata(self):
        audio = self.report["audio"]
        self.assertEqual(audio["sample_rate"], SAMPLE_RATE)
        self.assertEqual(audio["bit_depth"], 16)
        self.assertEqual(audio["channels"], 1)
        self.assertEqual(audio["format"], "pcm-s16le-mono")
        self.assertEqual(audio["neutral_level"], 0)
        self.assertEqual(audio["first_music_callback_sample"], 1045)
        self.assertTrue(audio["first_music_callback_measured"])
        self.assertEqual(audio["sample_count"], self.info["frames"])

    def test_viewer_sync_fields_present(self):
        self.assertIn("first_music_callback_sample", self.report["audio"])
        self.assertIn("rendered_ticks", self.report["render"])
        self.assertIn("total_ticks", self.report["render"])


class CliValidationTests(unittest.TestCase):
    def _run(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(argv)
        return code, json.loads(buf.getvalue())

    def test_backend_unavailable(self):
        code, payload = self._run(["render", os.path.join(REPO_ROOT, EXAMPLE_REL), "--backend", "fx", "--out", "build/x"])
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["diagnostics"][0]["code"], "BACKEND_UNAVAILABLE")

    def test_missing_song_is_io_error(self):
        code, payload = self._run(["render", os.path.join(REPO_ROOT, "does-not-exist.json"), "--out", "build/x"])
        self.assertEqual(code, 3)
        self.assertEqual(payload["diagnostics"][0]["code"], "IO_ERROR")

    def test_duration_cap_rejected(self):
        code, payload = self._run(
            ["render", os.path.join(REPO_ROOT, EXAMPLE_REL), "--seconds", "301", "--out", "build/x"]
        )
        self.assertEqual(code, 2)
        self.assertEqual(payload["diagnostics"][0]["code"], "DURATION_CAP")

    def test_default_seconds_is_bounded(self):
        # --seconds omitted defaults to a bounded 60 s request (never unbounded).
        self.assertEqual(DEFAULT_SECONDS, 60.0)


class IsolationFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.score, diagnostics = load_and_validate(
            os.path.join(REPO_ROOT, "tests/music_authoring/fixtures/basic/isolated.json")
        )
        assert cls.score is not None, diagnostics
        cls.lowered = lower(cls.score)

    def test_gate_timeline_regions(self):
        active = gate_timeline(self.lowered.spans, self.lowered.total_ticks)
        self.assertEqual(self.lowered.total_ticks, 40)
        # Isolated single-voice regions; global neutral silence in [4,8), [13,24), [26,32), [34,40).
        self.assertFalse(any(active[4:8]))
        self.assertFalse(any(active[13:24]))
        self.assertFalse(any(active[26:32]))
        self.assertTrue(all(active[0:4]))
        self.assertTrue(all(active[8:13]))
        self.assertTrue(all(active[24:26]))

    def test_two_identical_noise_notes(self):
        noise = [s for s in self.lowered.spans if s.channel == 3]
        self.assertEqual(len(noise), 2)
        self.assertEqual((noise[0].note, noise[0].duration), (noise[1].note, noise[1].duration))
        self.assertEqual(noise[0].source, noise[1].source)


@unittest.skipUnless(os.environ.get("ATMLIB_AVR_PREVIEW") == "1", "set ATMLIB_AVR_PREVIEW=1 for the real AVR capture")
class RealAvrCaptureTests(unittest.TestCase):
    def test_full_render_produces_audible_wav(self):
        argv = [
            "render", os.path.join(REPO_ROOT, EXAMPLE_REL),
            "--backend", "progmem", "--seconds", "8",
            "--out", os.path.join(REPO_ROOT, "build", "music-authoring", "preview-test"),
            "--json",
        ]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(argv)
        payload = json.loads(buf.getvalue())
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["audio"]["first_music_callback_measured"])
        self.assertGreater(payload["audio"]["analysis"]["peak_abs"], 0)


if __name__ == "__main__":
    unittest.main()
