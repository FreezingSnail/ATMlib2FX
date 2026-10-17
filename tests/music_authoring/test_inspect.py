"""Offline HTML/JS track review + synchronized audition tests (ATMlib2FX-3ii.6).

Permanent tests for the inspect contract that do not require a browser:

* the HTML is deterministic, standalone (no network/CDN/module/external file),
  and embeds the canonical frontend payload with the exact source + event digests;
* authored data is escaped so a ``</script>`` or HTML-comment sequence in a path
  or string cannot terminate the inert data block;
* matching audio previews embed and describe the real WAV metadata and the
  measured first-music-callback offset; mismatched/stale digests reject it;
* report paths are bounded to the requested preview directory;
* a four-channel fixture, a short/silent lane, pattern repetition, one-tick
  gates and a long sparse arrangement all match the canonical payload;
* inspect writes no FX/build artifacts (review only).

Outputs are written under ``build/music-authoring/`` (never temp dirs). The
real browser walkthrough is recorded in the bead, not here.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import os
import re
import struct
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
_TOOLS = os.path.join(REPO_ROOT, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from music_authoring import cli  # noqa: E402
from music_authoring.inspect import (  # noqa: E402
    build_inspect_document,
    escape_json_for_script,
    load_audio_preview,
    render_html,
    serialize_embedded_json,
    _resolve_within,
)
from music_authoring.lower import build_review_payload, lower  # noqa: E402
from music_authoring.progmem_backend import capability_summary  # noqa: E402
from music_authoring.render import capability_report  # noqa: E402
from music_authoring.score import parse_json_bytes  # noqa: E402
from music_authoring.validate import validate_document  # noqa: E402

EXAMPLE_REL = "tests/music_authoring/fixtures/basic/song.json"
ISOLATED_REL = "tests/music_authoring/fixtures/basic/isolated.json"
REVIEW_REL = "tests/music_authoring/fixtures/basic/expected/review.json"
OUT_ROOT = os.path.join(REPO_ROOT, "build", "music-authoring", "inspect-tests")
REAL_PREVIEW = os.path.join(REPO_ROOT, "build", "music-authoring", "preview-det-a")
DATA_RE = re.compile(
    r'<script type="application/json" id="atmlib-data">(.*?)</script>', re.S
)


def load_score(rel_path: str, source_path: str | None = None):
    with open(os.path.join(REPO_ROOT, rel_path), "rb") as handle:
        raw = handle.read()
    parsed = parse_json_bytes(raw)
    return validate_document(
        parsed.document,
        source_path=source_path or rel_path,
        raw_bytes=raw,
        parsed=parsed,
    )


def validate_obj(obj: dict, source_path: str = "<mem>"):
    raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    parsed = parse_json_bytes(raw)
    return validate_document(
        parsed.document, source_path=source_path, raw_bytes=raw, parsed=parsed
    )


def run_cli(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(argv)
    return code, json.loads(buf.getvalue())


def data_block(html: str) -> str:
    match = DATA_RE.search(html)
    assert match, "embedded data block missing"
    return match.group(1)


def make_wav(samples, rate=1000, channels=1, bits=16) -> bytes:
    data = struct.pack(f"<{len(samples)}h", *samples)
    block_align = channels * bits // 8
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    header += b"fmt " + struct.pack(
        "<IHHIIHH", 16, 1, channels, rate, rate * block_align, block_align, bits
    )
    header += b"data" + struct.pack("<I", len(data))
    return header + data


def base_document() -> dict:
    return {
        "format": "atmlib-score",
        "version": 1,
        "id": "t",
        "clock": {"tick_rate": 50, "ticks_per_beat": 25, "beats_per_bar": 4},
        "instruments": {"lead": {"voice": "pulse", "volume": 80, "duty": 127}},
        "patterns": {
            "p": {
                "ticks": 8,
                "events": [{"at": 0, "note": "C4", "duration": 2, "instrument": "lead"}],
            }
        },
        "tracks": {"pulse0": [{"pattern": "p", "repeat": 1}]},
    }


class EscapingTests(unittest.TestCase):
    def test_escapes_script_terminator_and_angle(self):
        escaped = escape_json_for_script("</script><b>&amp;<!--x-->")
        for token in ("<", ">", "&"):
            self.assertNotIn(token, escaped)
        self.assertIn("\\u003c", escaped)

    def test_escaped_document_roundtrips(self):
        document = {
            "path": "</script><script>alert(1)</script>",
            "text": "line\u2028sep\u2029here <!-- --> & more",
        }
        text = serialize_embedded_json(document)
        self.assertEqual(json.loads(text), document)
        self.assertNotIn("</script", text)
        self.assertNotIn("<!--", text)

    def test_json_line_separators_are_escaped(self):
        text = serialize_embedded_json({"x": "\u2028\u2029"})
        self.assertNotIn("\u2028", text)
        self.assertNotIn("\u2029", text)


class DocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        score, diagnostics = load_score(EXAMPLE_REL)
        assert score is not None, diagnostics
        cls.review = build_review_payload(score, lower(score))
        cls.document = build_inspect_document(
            review_payload=cls.review, score_id=score.id, audio=None, audio_diagnostics=[]
        )
        cls.html = render_html(cls.document)
        with open(os.path.join(REPO_ROOT, REVIEW_REL), "r", encoding="utf-8") as handle:
            cls.golden = json.load(handle)

    def test_html_is_deterministic(self):
        self.assertEqual(self.html, render_html(self.document))

    def test_no_network_cdn_module_or_external_file(self):
        lowered = self.html.lower()
        for token in (
            "http://",
            "https://",
            "//cdn",
            "xmlhttprequest",
            "fetch(",
            "import(",
            'type="module"',
            '<link',
            "src=\"//",
        ):
            self.assertNotIn(token, lowered, token)
        self.assertIn("content-security-policy", lowered)
        self.assertIn("default-src 'none'", lowered)

    def test_data_block_roundtrips_and_carries_review(self):
        block = data_block(self.html)
        self.assertNotIn("</script", block)
        parsed = json.loads(block)
        self.assertEqual(parsed["payload"], "atmlib-inspect")
        self.assertEqual(parsed["review"], self.review)
        self.assertEqual(parsed["review"]["source"]["sha256"], self.golden["source"]["sha256"])
        self.assertEqual(
            parsed["review"]["event_digest"]["hex"], self.golden["event_digest"]["hex"]
        )
        self.assertIsNone(parsed["audio"])

    def test_viewer_reports_own_truthful_capabilities(self):
        self.assertTrue(self.document["capabilities"]["inspect"]["available"])
        self.assertTrue(self.document["capabilities"]["render"]["available"])

    def test_no_audio_message_present(self):
        self.assertIn("Audio unavailable", self.html)

    def test_side_effect_note_present(self):
        self.assertIn("never compiles, packs, writes or flashes FX data", self.html)


class CanonicalDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        score, diagnostics = load_score(EXAMPLE_REL)
        assert score is not None, diagnostics
        cls.review = build_review_payload(score, lower(score))
        with open(os.path.join(REPO_ROOT, REVIEW_REL), "r", encoding="utf-8") as handle:
            cls.golden = json.load(handle)

    def test_notes_and_boundaries_match_golden(self):
        self.assertEqual(self.review["notes"], self.golden["notes"])
        self.assertEqual(self.review["pattern_instances"], self.golden["pattern_instances"])
        self.assertEqual(self.review["channels"], self.golden["channels"])
        self.assertEqual(self.review["total_ticks"], self.golden["total_ticks"])

    def test_four_named_lanes_on_common_timeline(self):
        names = [c["name"] for c in self.review["channels"]]
        self.assertEqual(names, ["pulse0", "pulse1", "pulse2", "noise"])

    def test_one_tick_gate_and_repeats_and_silent_lane(self):
        durations = {n["duration"] for n in self.review["notes"]}
        self.assertIn(1, durations)
        repeats = {n["repeat_index"] for n in self.review["notes"]}
        self.assertGreaterEqual(max(repeats), 1)
        pulse2 = next(c for c in self.review["channels"] if c["name"] == "pulse2")
        self.assertEqual(pulse2["note_count"], 2)  # short lane, silent after tick 16


class InjectionTests(unittest.TestCase):
    def test_authored_markup_stays_inert(self):
        malicious = '</script><img src=x onerror=alert(1)><!-- & " \u2028'
        score, diagnostics = validate_obj(base_document(), source_path=malicious)
        assert score is not None, diagnostics
        review = build_review_payload(score, lower(score))
        document = build_inspect_document(
            review_payload=review, score_id=score.id, audio=None, audio_diagnostics=[]
        )
        html = render_html(document)
        block = data_block(html)
        self.assertNotIn("</script", block)
        self.assertNotIn("<img", block)
        parsed = json.loads(block)
        self.assertEqual(parsed["review"]["source"]["path"], malicious)
        # Only the two authored closing script tags may appear anywhere.
        self.assertEqual(html.count("</script>"), 2)


class LargeSparseTests(unittest.TestCase):
    def _doc(self):
        doc = base_document()
        doc["clock"]["tick_rate"] = 200
        doc["patterns"] = {
            "sparse": {
                "ticks": 4096,
                "events": [
                    {"at": 0, "note": "C4", "duration": 4, "instrument": "lead"},
                    {"at": 1024, "note": "E4", "duration": 4, "instrument": "lead"},
                    {"at": 2048, "note": "G4", "duration": 4, "instrument": "lead"},
                    {"at": 3072, "note": "C5", "duration": 4, "instrument": "lead"},
                ],
            }
        }
        doc["tracks"] = {"pulse0": [{"pattern": "sparse", "repeat": 8}]}
        return doc

    def test_long_sparse_arrangement_builds_and_matches_canonical(self):
        score, diagnostics = validate_obj(self._doc())
        assert score is not None, diagnostics
        review = build_review_payload(score, lower(score))
        self.assertEqual(review["total_ticks"], 32768)
        self.assertEqual(len(review["notes"]), 32)
        document = build_inspect_document(
            review_payload=review, score_id=score.id, audio=None, audio_diagnostics=[]
        )
        html = render_html(document)
        parsed = json.loads(data_block(html))
        self.assertEqual(parsed["review"]["notes"], review["notes"])
        # The viewer draws only the visible window; no per-note DOM is embedded.
        self.assertIn("visibleNotes", html)
        self.assertIn("TRACKER_MAX_ROWS", html)

    def test_html_size_is_not_proportional_to_note_count(self):
        # A large sparse song must not balloon the HTML with per-note markup.
        small = base_document()
        score_small, _ = validate_obj(small)
        score_big, _ = validate_obj(self._doc())
        html_small = render_html(
            build_inspect_document(
                review_payload=build_review_payload(score_small, lower(score_small)),
                score_id=score_small.id,
                audio=None,
                audio_diagnostics=[],
            )
        )
        html_big = render_html(
            build_inspect_document(
                review_payload=build_review_payload(score_big, lower(score_big)),
                score_id=score_big.id,
                audio=None,
                audio_diagnostics=[],
            )
        )
        self.assertLess(len(html_big) - len(html_small), 12000)


class ShortSilentLaneTests(unittest.TestCase):
    def test_missing_lane_is_marked_unused(self):
        doc = base_document()
        doc["tracks"] = {"pulse0": [{"pattern": "p", "repeat": 2}]}
        score, diagnostics = validate_obj(doc)
        assert score is not None, diagnostics
        review = build_review_payload(score, lower(score))
        used = {c["name"]: c["used"] for c in review["channels"]}
        self.assertTrue(used["pulse0"])
        self.assertFalse(used["pulse2"])
        self.assertFalse(used["noise"])
        html = render_html(
            build_inspect_document(
                review_payload=review, score_id=score.id, audio=None, audio_diagnostics=[]
            )
        )
        self.assertIn("pulse2", html)


class RepetitionTests(unittest.TestCase):
    def test_repeat_indices_and_instances(self):
        doc = base_document()
        doc["tracks"] = {"pulse0": [{"pattern": "p", "repeat": 3}]}
        score, diagnostics = validate_obj(doc)
        assert score is not None, diagnostics
        review = build_review_payload(score, lower(score))
        self.assertEqual([i["repeat_index"] for i in review["pattern_instances"]], [0, 1, 2])
        self.assertEqual([n["repeat_index"] for n in review["notes"]], [0, 1, 2])
        self.assertEqual(review["total_ticks"], 24)


class PathBoundingTests(unittest.TestCase):
    def test_relative_ref_resolves_inside(self):
        base = os.path.join(REPO_ROOT, "build", "music-authoring")
        resolved = _resolve_within(__import__("pathlib").Path(base), "preview.wav")
        self.assertIsNotNone(resolved)
        self.assertTrue(str(resolved).startswith(os.path.realpath(base)))

    def test_escaping_reference_is_rejected(self):
        base = os.path.join(REPO_ROOT, "build", "music-authoring")
        self.assertIsNone(_resolve_within(__import__("pathlib").Path(base), "../../etc/passwd"))
        self.assertIsNone(_resolve_within(__import__("pathlib").Path(base), "/etc/passwd"))


@unittest.skipUnless(os.path.isdir(REAL_PREVIEW), "real .2 preview not present")
class RealAudioPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        score, diagnostics = load_score(EXAMPLE_REL)
        assert score is not None, diagnostics
        cls.review = build_review_payload(score, lower(score))

    def test_matching_preview_embeds_measured_metadata(self):
        descriptor, diagnostics = load_audio_preview(REAL_PREVIEW, self.review)
        self.assertEqual(diagnostics, [])
        self.assertIsNotNone(descriptor)
        self.assertTrue(descriptor["available"])
        self.assertEqual(descriptor["sample_rate"], 50000)
        self.assertEqual(descriptor["first_music_callback_sample"], 1045)
        self.assertTrue(descriptor["first_music_callback_measured"])
        self.assertEqual(descriptor["effective_tick_rate"], 50)
        self.assertEqual(descriptor["rendered_ticks"], descriptor["total_ticks"])
        self.assertFalse(descriptor["truncated"])
        wav = base64.b64decode(descriptor["wav_base64"])
        self.assertEqual(hashlib.sha256(wav).hexdigest(), descriptor["wav_sha256"])

    def test_stale_source_rejects_audio(self):
        score, diagnostics = load_score(ISOLATED_REL)
        assert score is not None, diagnostics
        other = build_review_payload(score, lower(score))
        descriptor, diagnostics = load_audio_preview(REAL_PREVIEW, other)
        self.assertIsNone(descriptor)
        codes = {d.code for d in diagnostics}
        self.assertIn("SOURCE_DIGEST_MISMATCH", codes)
        self.assertIn("EVENT_DIGEST_MISMATCH", codes)

    def test_mismatched_audio_html_says_unavailable(self):
        score, diagnostics = load_score(ISOLATED_REL)
        other = build_review_payload(score, lower(score))
        audio, audio_diags = load_audio_preview(REAL_PREVIEW, other)
        document = build_inspect_document(
            review_payload=other, score_id=score.id, audio=audio, audio_diagnostics=audio_diags
        )
        html = render_html(document)
        self.assertIsNone(document["audio"])
        self.assertIn("Audio unavailable", html)
        self.assertIn("sha256", data_block(html))


class SyntheticPreviewTests(unittest.TestCase):
    """A crafted truncated preview exercises the rendered-range / truncation path."""

    @classmethod
    def setUpClass(cls):
        cls.dir = os.path.join(OUT_ROOT, "synth-preview")
        os.makedirs(cls.dir, exist_ok=True)
        cls.score, diagnostics = load_score(EXAMPLE_REL)
        assert cls.score is not None, diagnostics
        cls.review = build_review_payload(cls.score, lower(cls.score))
        samples = [0] * 11045  # first callback 1045 + 10 rendered ticks at 50 Hz
        wav = make_wav(samples, rate=50000)
        with open(os.path.join(cls.dir, "preview.wav"), "wb") as handle:
            handle.write(wav)
        report = {
            "payload": "atmlib-render-preview",
            "payload_version": 1,
            "ok": True,
            "source": dict(cls.review["source"]),
            "event_digest": dict(cls.review["event_digest"]),
            "clock": dict(cls.review["clock"]),
            "total_ticks": cls.review["total_ticks"],
            "render": {
                "rendered_ticks": 10,
                "total_ticks": cls.review["total_ticks"],
                "truncated": True,
                "truncation_reason": "requested 0.05s < song+tail",
                "seconds": {"song": 0.64},
            },
            "audio": {
                "wav": "preview.wav",
                "sha256": hashlib.sha256(wav).hexdigest(),
                "format": "pcm-s16le-mono",
                "channels": 1,
                "sample_rate": 50000,
                "bit_depth": 16,
                "sample_count": len(samples),
                "neutral_level": 0,
                "sound_gain": 2000,
                "first_music_callback_sample": 1045,
                "first_music_callback_measured": True,
                "analysis": {"post_end_is_ac_silent": True, "post_end_dc_level": -2000},
            },
            "limitations": ["synthetic"],
        }
        with open(os.path.join(cls.dir, "preview.json"), "w", encoding="utf-8") as handle:
            json.dump(report, handle)

    def test_truncation_is_propagated(self):
        descriptor, diagnostics = load_audio_preview(self.dir, self.review)
        self.assertEqual(diagnostics, [])
        self.assertTrue(descriptor["truncated"])
        self.assertEqual(descriptor["rendered_ticks"], 10)
        self.assertEqual(descriptor["total_ticks"], 32)
        self.assertEqual(descriptor["first_music_callback_sample"], 1045)
        self.assertEqual(descriptor["post_end_dc_level"], -2000)

    def test_viewer_marks_rendered_range(self):
        descriptor, _ = load_audio_preview(self.dir, self.review)
        html = render_html(
            build_inspect_document(
                review_payload=self.review,
                score_id=self.score.id,
                audio=descriptor,
                audio_diagnostics=[],
            )
        )
        self.assertIn("outside rendered audio", html)
        self.assertIn("disabled beyond the rendered range", html)


class CliTests(unittest.TestCase):
    def _out(self, name):
        return os.path.join(OUT_ROOT, name, "review.html")

    def test_inspect_reports_paths_and_digests(self):
        out = self._out("cli")
        song = os.path.join(REPO_ROOT, EXAMPLE_REL)
        code, payload = run_cli(["inspect", song, "--out", out, "--json"])
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"])
        artifacts = payload["artifacts"]
        self.assertTrue(os.path.isfile(artifacts["html"]))
        self.assertTrue(os.path.isfile(artifacts["review_json"]))
        digests = payload["report"]["digests"]
        with open(artifacts["html"], "rb") as handle:
            self.assertEqual(hashlib.sha256(handle.read()).hexdigest(), digests["html_sha256"])
        with open(artifacts["review_json"], "rb") as handle:
            review_bytes = handle.read()
        self.assertEqual(
            hashlib.sha256(review_bytes).hexdigest(), digests["review_json_sha256"]
        )
        # The adjacent JSON is exactly the canonical payload for this invocation.
        score, diagnostics = load_score(EXAMPLE_REL, source_path=song)
        assert score is not None, diagnostics
        expected = build_review_payload(score, lower(score))
        self.assertEqual(json.loads(review_bytes), expected)
        with open(os.path.join(REPO_ROOT, REVIEW_REL), "r", encoding="utf-8") as handle:
            golden = json.load(handle)
        self.assertEqual(expected["source"]["sha256"], golden["source"]["sha256"])
        self.assertEqual(expected["event_digest"]["hex"], golden["event_digest"]["hex"])
        self.assertEqual(expected["notes"], golden["notes"])

    def test_inspect_has_no_fx_side_effects(self):
        out = self._out("noside")
        code, payload = run_cli(["inspect", os.path.join(REPO_ROOT, EXAMPLE_REL), "--out", out, "--json"])
        self.assertEqual(code, 0)
        produced = set(os.listdir(os.path.dirname(out)))
        self.assertEqual(produced, {"review.html", "review.json"})
        self.assertEqual(payload["report"]["side_effects"].split(":")[0], "Review artifact only")
        self.assertNotIn("score.bin", payload["artifacts"])

    def test_missing_song_is_io_error(self):
        code, payload = run_cli(["inspect", os.path.join(REPO_ROOT, "nope.json"), "--out", self._out("x"), "--json"])
        self.assertEqual(code, 3)
        self.assertEqual(payload["diagnostics"][0]["code"], "IO_ERROR")

    def test_invalid_audio_preview_dir(self):
        code, payload = run_cli(
            [
                "inspect",
                os.path.join(REPO_ROOT, EXAMPLE_REL),
                "--audio-preview",
                os.path.join(REPO_ROOT, "build", "music-authoring", "does-not-exist"),
                "--out",
                self._out("y"),
                "--json",
            ]
        )
        self.assertEqual(code, 3)
        self.assertEqual(payload["diagnostics"][0]["code"], "AUDIO_PREVIEW_INVALID")


class CapabilityDivergenceTests(unittest.TestCase):
    """Documents the bounded capability-report mismatch and why it is not changed.

    ``capabilities --json`` still reports inspect/render unavailable because the
    ATMlib2FX-3ii.1 ``review.json`` golden embeds that capabilities block (and
    ``test_progmem`` pins it). Regenerating that golden is out of scope for 3ii.6,
    so the divergence is deliberately preserved and reported here instead.
    """

    def test_capability_summary_keeps_the_pinned_payload(self):
        summary = capability_summary()
        self.assertFalse(summary["capabilities"]["inspect"]["available"])
        self.assertFalse(summary["capabilities"]["render"]["available"])
        with open(os.path.join(REPO_ROOT, REVIEW_REL), "r", encoding="utf-8") as handle:
            golden = json.load(handle)
        self.assertFalse(golden["capabilities"]["capabilities"]["inspect"]["available"])
        self.assertFalse(golden["capabilities"]["capabilities"]["render"]["available"])

    def test_render_and_inspect_report_their_own_availability(self):
        self.assertTrue(capability_report()["capabilities"]["render"]["available"])
        document = build_inspect_document(
            review_payload={"source": {}, "event_digest": {}},
            score_id="x",
            audio=None,
            audio_diagnostics=[],
        )
        self.assertTrue(document["capabilities"]["inspect"]["available"])
        self.assertTrue(document["capabilities"]["canonical_payload_capabilities_pinned"])


if __name__ == "__main__":
    unittest.main()
