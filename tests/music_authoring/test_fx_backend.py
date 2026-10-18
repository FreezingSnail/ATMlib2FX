"""Finite-v1 compact FX backend tests (ATMlib2FX-3ii.3).

Permanent tests: pinned stream framing, deterministic bytes, golden assets,
packing metadata, and source-pointed admission failures for content outside the
finite-v1 input matrix. No files are written to temp directories; generated
artifacts go under ``build/music-authoring/fx``.

The stream framing, limits and semantics are the ``hlh.6 review`` contract in
``research/fx/fx-architecture-decision.md`` (read-only here).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
_TOOLS = os.path.join(REPO_ROOT, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from music_authoring import fx_backend as fx  # noqa: E402
from music_authoring.cli import main as cli_main  # noqa: E402
from music_authoring.lower import lower  # noqa: E402
from music_authoring.progmem_backend import capability_summary  # noqa: E402
from music_authoring.score import parse_json_bytes  # noqa: E402
from music_authoring.validate import validate_document  # noqa: E402

BASIC_REL = "examples/music_authoring/fx/basic/song.json"
STRESS_REL = "examples/music_authoring/fx/stress/song.json"
EXPECTED_DIR = os.path.join(REPO_ROOT, "examples/music_authoring/fx/basic/expected")
LANE = os.path.join(REPO_ROOT, "build/music-authoring/fx")


def load(rel: str):
    with open(os.path.join(REPO_ROOT, rel), "rb") as handle:
        raw = handle.read()
    parsed = parse_json_bytes(raw)
    score, diagnostics = validate_document(
        parsed.document, source_path=rel, raw_bytes=raw, parsed=parsed
    )
    assert not diagnostics, diagnostics
    return score


def decode_stream(stream: bytes):
    """Decode the pinned framing; return (passes, end_offset).

    ``passes`` are dicts with ``gap``, ``bitmap``, ``groups`` (channel -> bytes)
    and ``ids`` (the flat command-id list), so a test can check that no
    traversal/long-delay command survives into a finite-v1 stream.
    """
    assert stream[0] == fx.FORMAT_MAGIC, stream[0]
    passes = []
    pos = 1
    while True:
        length = stream[pos]
        pos += 1
        if length == 0:
            return passes, pos
        assert length >= fx.MIN_RECORD_LEN and length <= fx.RING_CAPACITY, length
        start = pos
        b0 = stream[pos]
        pos += 1
        if b0 < 0x80:
            gap = b0
        elif b0 != 0xFF:
            gap = ((b0 & 0x7F) << 8) | stream[pos]
            pos += 1
        else:
            gap = (stream[pos] << 8) | stream[pos + 1]
            pos += 2
        bitmap = stream[pos]
        pos += 1
        assert 1 <= bitmap <= 15, bitmap
        groups = {}
        ids = []
        for channel in range(4):
            if not (bitmap & (1 << channel)):
                continue
            glen = stream[pos]
            pos += 1
            assert glen >= 1, glen
            body = stream[pos : pos + glen]
            pos += glen
            cursor = 0
            while cursor < len(body):
                command = body[cursor]
                size = cmd_size(command)
                assert cursor + size <= len(body), (command, cursor, len(body))
                ids.append(command)
                cursor += size
            assert cursor == len(body), (cursor, len(body))
            groups[channel] = body
        assert pos - start + 1 == length, (pos - start + 1, length)
        passes.append({"gap": gap, "bitmap": bitmap, "groups": groups, "ids": ids})
    # unreachable


def cmd_size(command: int) -> int:
    """Original ATMlib command byte length (src/atm_cmd_constants.h)."""
    if command < 64:
        return 1
    if command < 0x60:
        return 1
    if command < 0x70:
        return 1
    if command < 0x80:
        return 2
    return 1 + (((command >> 4) & 0x07) + 1)


# Traversal-only / unsupported opcodes that must never survive into finite v1.
TRAVERSAL_IDS = frozenset({0x81, 0x82, 0x83, 0x85, 0x95})


def pass_ticks(passes):
    ticks = []
    tick = 0
    for index, record in enumerate(passes):
        ticks.append(tick)
        tick += record["gap"] + 1
    return ticks


def make_score(document, rel="<constructed>"):
    """Validate an inline score document exactly like ``load`` does for files."""
    parsed = parse_json_bytes(json.dumps(document).encode())
    score, diagnostics = validate_document(
        parsed.document, source_path=rel, raw_bytes=b"{}", parsed=parsed
    )
    assert not diagnostics, diagnostics
    return score


def gap_extent_document():
    """One 70000-tick gate: an inter-pass gap (69999) beyond the varint max."""
    return {
        "format": "atmlib-score",
        "version": 1,
        "id": "gap_extent",
        "clock": {"tick_rate": 255, "ticks_per_beat": 25, "beats_per_bar": 4},
        "instruments": {"lead": {"voice": "pulse", "volume": 80, "duty": 127}},
        "patterns": {
            "long": {
                "ticks": 70000,
                "events": [
                    {"at": 0, "note": "C4", "duration": 70000, "instrument": "lead"}
                ],
            }
        },
        "tracks": {"pulse0": [{"pattern": "long", "repeat": 1}]},
    }


def terminal_heavy_document():
    """Four staggered 8-tick tracks: the terminal pass (mutes + STOPs) is widest.

    The terminal pass record is 19 bytes while every earlier pass is at most
    11 bytes, so a window table that overwrites the terminal record with the
    END charge visibly understates the worst one-callback window.
    """
    return {
        "format": "atmlib-score",
        "version": 1,
        "id": "terminal_heavy",
        "clock": {"tick_rate": 60, "ticks_per_beat": 25, "beats_per_bar": 4},
        "instruments": {
            "lead": {"voice": "pulse", "volume": 80, "duty": 127},
            "perc": {"voice": "noise", "volume": 90},
        },
        "patterns": {
            "lead0": {
                "ticks": 8,
                "events": [
                    {"at": 0, "note": "C4", "duration": 8, "instrument": "lead"}
                ],
            },
            "lead1": {
                "ticks": 8,
                "events": [
                    {"at": 2, "note": "E4", "duration": 6, "instrument": "lead"}
                ],
            },
            "lead2": {
                "ticks": 8,
                "events": [
                    {"at": 4, "note": "G4", "duration": 4, "instrument": "lead"}
                ],
            },
            "perc": {
                "ticks": 8,
                "events": [
                    {"at": 6, "note": "C2", "duration": 2, "instrument": "perc"}
                ],
            },
        },
        "tracks": {
            "pulse0": [{"pattern": "lead0", "repeat": 1}],
            "pulse1": [{"pattern": "lead1", "repeat": 1}],
            "pulse2": [{"pattern": "lead2", "repeat": 1}],
            "noise": [{"pattern": "perc", "repeat": 1}],
        },
    }


def gate_document(duration, tick_rate=60):
    """One sustained note over an otherwise idle score.

    Passes at ticks 0 and ``duration`` (inter-pass gap ``duration-1``); pulses
    1/2 and noise are idle and stop at tick 0.  Pass 0 carries pulse0's
    setup (tempo/volume/mod) + note plus the idle channels' STOP; the terminal
    pass carries pulse0's mute + STOP.  Used to pin the record ``len`` byte
    against multi-byte gap varints.
    """
    return {
        "format": "atmlib-score",
        "version": 1,
        "id": f"gate_{duration}",
        "clock": {"tick_rate": tick_rate, "ticks_per_beat": 25, "beats_per_bar": 4},
        "instruments": {"lead": {"voice": "pulse", "volume": 80, "duty": 127}},
        "patterns": {
            "long": {
                "ticks": duration,
                "events": [
                    {"at": 0, "note": "C4", "duration": duration, "instrument": "lead"}
                ],
            }
        },
        "tracks": {"pulse0": [{"pattern": "long", "repeat": 1}]},
    }


class FramingTests(unittest.TestCase):
    def test_stream_decodes_to_pinned_structure(self):
        score = load(BASIC_REL)
        lowered = lower(score)
        stream, meta, _warnings = fx.serialize_compact(score, lowered)
        self.assertEqual(stream[0], 0xC0)
        self.assertEqual(stream[-1], 0x00)
        passes, end = decode_stream(stream)
        self.assertEqual(end, len(stream))
        self.assertEqual(len(passes), meta["passes"])
        for record in passes:
            self.assertTrue(record["bitmap"])
            self.assertTrue(record["groups"])
        self.assertEqual(passes[-1]["gap"], 0)
        ticks = pass_ticks(passes)
        self.assertEqual(ticks[-1], lowered.total_ticks)

    def test_gap_codec_boundaries(self):
        cases = {
            0: bytes([0x00]),
            0x7F: bytes([0x7F]),
            0x80: bytes([0x80, 0x80]),
            0x7EFF: bytes([0xFE, 0xFF]),
            0x7F00: bytes([0xFF, 0x7F, 0x00]),
            0xFFFF: bytes([0xFF, 0xFF, 0xFF]),
        }
        for value, expected in cases.items():
            self.assertEqual(fx._gap_bytes(value), expected, value)

    def test_no_traversal_bytes_in_finite_stream(self):
        for rel in (BASIC_REL, STRESS_REL):
            score = load(rel)
            stream, _meta, _w = fx.serialize_compact(score, lower(score))
            passes, _end = decode_stream(stream)
            for record in passes:
                for command in record["ids"]:
                    self.assertNotIn(command, TRAVERSAL_IDS, (rel, command))


class DeterminismTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.score = load(BASIC_REL)
        cls.lowered = lower(cls.score)
        cls.result = fx.serialize(cls.score, cls.lowered, "expected")

    def test_serialize_is_deterministic(self):
        again = fx.serialize(self.score, lower(self.score), "expected")
        self.assertEqual(self.result.stream_bytes, again.stream_bytes)
        self.assertEqual(self.result.header_bytes, again.header_bytes)
        self.assertEqual(self.result.review_bytes, again.review_bytes)
        self.assertEqual(self.result.report_bytes, again.report_bytes)

    def test_build_writes_byte_identical_artifacts(self):
        first = os.path.join(LANE, "determinism-a")
        second = os.path.join(LANE, "determinism-b")
        result_a, files_a = fx.build(self.score, self.lowered, first)
        result_b, files_b = fx.build(self.score, self.lowered, second)
        self.assertEqual(result_a.stream_bytes, result_b.stream_bytes)
        for name in ("stream.bin", "stream.h", "review.json"):
            with open(files_a[name], "rb") as handle:
                a = handle.read()
            with open(files_b[name], "rb") as handle:
                b = handle.read()
            self.assertEqual(a, b, name)

    def test_golden_stream_and_header(self):
        with open(os.path.join(EXPECTED_DIR, "stream.bin"), "rb") as handle:
            golden = handle.read()
        self.assertEqual(self.result.stream_bytes, golden)
        self.assertEqual(
            hashlib.sha256(self.result.stream_bytes).hexdigest(),
            "b14e02cc3619c3bc40119b76b9a6d362a2a72ec5522e71f8f9bdbd24ae5534e3",
        )
        with open(os.path.join(EXPECTED_DIR, "stream.h"), "rb") as handle:
            header = handle.read()
        self.assertEqual(self.result.header_bytes, header)

    def test_golden_review_payload(self):
        with open(os.path.join(EXPECTED_DIR, "review.json"), "rb") as handle:
            golden = handle.read()
        self.assertEqual(self.result.review_bytes, golden)

    def test_golden_stress_fixture(self):
        score = load(STRESS_REL)
        stream, meta, warnings = fx.serialize_compact(score, lower(score))
        self.assertEqual(warnings, [])
        expected = os.path.join(
            REPO_ROOT, "examples/music_authoring/fx/stress/expected/stream.bin"
        )
        with open(expected, "rb") as handle:
            self.assertEqual(stream, handle.read())
        # Sparse song at the 2000/7 Hz stress rate: a wider frame window is
        # admitted because the per-tick consumption is small.
        self.assertEqual(meta["service_ticks"], 6)
        self.assertLessEqual(meta["required_window_bytes"], fx.RING_CAPACITY)
        self.assertEqual(meta["required_window_bytes"], meta["window_bytes"]["6"])


class PackingMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.score = load(BASIC_REL)
        cls.result = fx.serialize(cls.score, lower(cls.score), "expected")
        cls.stream = cls.result.report["stream"]

    def test_metadata_shape(self):
        stream = self.stream
        self.assertEqual(stream["bytes"], len(self.result.stream_bytes))
        self.assertEqual(stream["ring_capacity"], fx.RING_CAPACITY)
        self.assertEqual(stream["fetch_chunk"], fx.FETCH_CHUNK)
        for key in (
            "ticks",
            "passes",
            "payload_bytes",
            "framing_bytes",
            "max_group_bytes",
            "max_record_bytes",
            "window_bytes",
            "service_ticks",
            "required_window_bytes",
        ):
            self.assertIn(key, stream)

    def test_admission_bounds_hold(self):
        stream = self.stream
        self.assertLessEqual(stream["max_record_bytes"], fx.RING_CAPACITY)
        self.assertLessEqual(stream["required_window_bytes"], fx.RING_CAPACITY)
        self.assertEqual(
            stream["required_window_bytes"],
            stream["window_bytes"][str(stream["service_ticks"])],
        )
        self.assertEqual(stream["framing_bytes"] + 2, stream["bytes"])  # magic + END

    def test_window_table_counts_terminal_record(self):
        # Regression: the END charge used to overwrite the longest track's
        # STOP pass at tick == total_ticks, understating window_bytes and
        # required_window_bytes whenever the terminal record was the widest.
        score = make_score(terminal_heavy_document(), rel="<terminal-heavy>")
        lowered = lower(score)
        stream, meta, warnings = fx.serialize_compact(score, lowered)
        self.assertTrue(stream)
        self.assertEqual(warnings, [])
        passes = fx._collect_passes(score, lowered)
        terminal = [p for p in passes if p.tick == lowered.total_ticks]
        self.assertEqual(len(terminal), 1)
        widest = max(p.record_len for p in passes)
        self.assertEqual(terminal[0].record_len, widest)
        # The terminal pass is consumed on the final callback and the
        # all-inactive check then stops the player, so END is never read and
        # the terminal record alone is the worst one-callback window.
        self.assertEqual(meta["window_bytes"]["1"], widest)
        self.assertEqual(
            meta["required_window_bytes"],
            meta["window_bytes"][str(meta["service_ticks"])],
        )
        self.assertGreaterEqual(meta["required_window_bytes"], widest)
        self.assertLessEqual(meta["required_window_bytes"], fx.RING_CAPACITY)

    def test_loop_warns_and_is_not_advertised(self):
        # A looping source is still exported finite, with a source-pointed warning.
        looping = load("examples/music_authoring/basic/song.json")
        stream, _meta, warnings = fx.serialize_compact(looping, lower(looping))
        self.assertTrue(stream)
        codes = [(w.code, w.path, w.severity) for w in warnings]
        self.assertIn(("LOOP_NOT_EXPORTED", "/loop", "warning"), codes)
        summary = capability_summary()
        self.assertFalse(summary["backends"]["fx"]["advertises"]["loops"])

    def test_capabilities_advertise_finite_fx_only(self):
        summary = capability_summary()
        self.assertTrue(summary["backends"]["fx"]["available"])
        self.assertEqual(summary["backends"]["fx"]["format"], "atm_fx_compact_v1")
        self.assertEqual(
            summary["backends"]["fx"]["advertises"],
            {"loops": False, "effects": False, "sfx": False},
        )
        self.assertIn("fx_stream_export", summary["features"])
        for banned in ("fx_loops", "fx_effects", "fx_sfx"):
            self.assertNotIn(banned, summary["features"])


class GapVarintRecordLenTests(unittest.TestCase):
    """Record ``len`` must count the true gap varint extent (drift regression).

    The pinned decoder walks from the byte after ``len``, consumes the actual
    gap varint and fails with ``pos != len`` unless ``len`` is the full wire
    record length.  Sizing records as if every gap were 1 byte understates
    ``max_record``/``window_bytes``/ring admission when a gap needs 2-3 bytes.
    """

    # (pattern ticks, inter-pass gap, first-pass wire len, terminal pass len).
    # First pass = 16 non-gap bytes (len byte, bitmap, pulse0 setup+note group
    # and three idle-channel STOP groups) + the gap varint (1/2/3 bytes);
    # terminal pass = 7 bytes (len, gap, bitmap, mute+STOP group).
    CASES = (
        (128, 127, 17, 7),
        (129, 128, 18, 7),
        (65536, 65535, 19, 7),
    )

    def test_record_len_matches_wire_and_metadata(self):
        for ticks, gap, first_len, stop_len in self.CASES:
            with self.subTest(ticks=ticks, gap=gap):
                score = make_score(gate_document(ticks), rel=f"<gate-{ticks}>")
                lowered = lower(score)
                stream, meta, warnings = fx.serialize_compact(score, lowered)
                self.assertEqual(warnings, [])

                # (a) Emitted len byte == full wire record length; the shared
                # test decoder asserts pos == len for every record.
                self.assertEqual(stream[1], first_len, stream[:8])
                self.assertEqual(len(fx._gap_bytes(gap)), first_len - 16)
                passes, end = decode_stream(stream)
                self.assertEqual(end, len(stream))
                self.assertEqual([p["gap"] for p in passes], [gap, 0])
                self.assertEqual(stream[end - 1 - stop_len], stop_len)

                # (c) Hand-computed packing numbers: the 128-tick gate fits a
                # 1-byte gap varint (17-byte record), 129 ticks need 2 bytes
                # (18), 65536 ticks the full 3 bytes (19); the terminal pass
                # is 7 bytes.  At tick_rate 60 the frame service window is
                # 2 ticks (int((1/52)/(33/2000)) + 1) and no window spans both
                # records, so every window is the first record's length.
                self.assertEqual(meta["service_ticks"], 2)
                self.assertEqual(meta["max_record_bytes"], first_len)
                self.assertEqual(
                    meta["window_bytes"],
                    {str(k): first_len for k in range(1, 9)},
                )
                self.assertEqual(meta["required_window_bytes"], first_len)
                self.assertEqual(meta["framing_bytes"], first_len + stop_len)
                self.assertEqual(meta["stream_bytes"], 1 + first_len + stop_len + 1)


@unittest.skipUnless(shutil.which("cc") or shutil.which("clang"), "no host C compiler")
class GapVarintHarnessTests(unittest.TestCase):
    """Multi-byte gap records must pass the *device* decoder preflight."""

    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cc") or shutil.which("clang")
        cls.dir = os.path.join(LANE, "gap-varint")
        os.makedirs(cls.dir, exist_ok=True)
        cls.binary = os.path.join(cls.dir, "compact_trace")
        subprocess.run(
            [
                compiler,
                "-std=c11",
                "-O1",
                "-w",
                "-I",
                os.path.join(REPO_ROOT, "tools/music_authoring/preview/avr_shim"),
                "-I",
                os.path.join(REPO_ROOT, "src"),
                os.path.join(REPO_ROOT, "tests/music_authoring/fx/compact_trace_main.c"),
                "-o",
                cls.binary,
            ],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        )

    def test_device_decoder_accepts_multibyte_gaps(self):
        # (b) gap 127 control and the 2-byte (128) / 3-byte (65535) extents:
        # the decoder's fill preflight (walk(0) == rec_len) must report no
        # format error, at one service per tick and across the 2-tick
        # service window phases.
        for ticks, gap in ((128, 127), (129, 128), (65536, 65535)):
            with self.subTest(ticks=ticks, gap=gap):
                score = make_score(gate_document(ticks), rel=f"<gate-{ticks}>")
                stream, _meta, _warnings = fx.serialize_compact(score, lower(score))
                path = os.path.join(self.dir, f"gate-{ticks}.bin")
                with open(path, "wb") as handle:
                    handle.write(stream)
                for service_every, phase in ((1, 0), (2, 0), (2, 1)):
                    proc = subprocess.run(
                        [self.binary, path, str(ticks + 64), str(service_every), str(phase)],
                        cwd=REPO_ROOT,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    line = next(
                        l for l in proc.stderr.splitlines() if l.startswith("compact trace:")
                    )
                    self.assertIn("error=0", line, line)
                    self.assertIn("underruns=0", line, line)


class AdmissionTests(unittest.TestCase):
    def dense_at_high_rate(self):
        document = {
            "format": "atmlib-score",
            "version": 1,
            "id": "dense_high_rate",
            "clock": {"tick_rate": 255, "ticks_per_beat": 25, "beats_per_bar": 4},
            "instruments": {
                "lead": {"voice": "pulse", "volume": 80, "duty": 127},
                "bass": {"voice": "pulse", "volume": 64, "duty": 200},
                "perc": {"voice": "noise", "volume": 90},
            },
            "patterns": {
                "lead_line": {
                    "ticks": 16,
                    "events": [
                        {"at": 0, "note": "C4", "duration": 4, "instrument": "lead"},
                        {"at": 8, "note": "E4", "duration": 4, "instrument": "lead"},
                        {"at": 12, "note": "G4", "duration": 4, "instrument": "lead"},
                    ],
                },
                "short": {
                    "ticks": 8,
                    "events": [
                        {"at": 0, "note": "C5", "duration": 1, "instrument": "lead"},
                        {"at": 1, "note": "D5", "duration": 1, "instrument": "lead"},
                        {"at": 2, "note": "E5", "duration": 3, "instrument": "lead"},
                    ],
                },
                "bassline": {
                    "ticks": 16,
                    "events": [
                        {"at": 0, "note": "C3", "duration": 8, "instrument": "bass"},
                        {"at": 8, "note": "G3", "duration": 8, "instrument": "bass"},
                    ],
                },
                "percs": {
                    "ticks": 16,
                    "events": [
                        {"at": 0, "note": "A2", "duration": 2, "instrument": "perc"},
                        {"at": 8, "note": "A2", "duration": 2, "instrument": "perc"},
                    ],
                },
            },
            "tracks": {
                "pulse0": [{"pattern": "lead_line", "repeat": 1}],
                "pulse1": [{"pattern": "short", "repeat": 2}],
                "pulse2": [{"pattern": "bassline", "repeat": 1}],
                "noise": [{"pattern": "percs", "repeat": 1}],
            },
        }
        parsed = parse_json_bytes(json.dumps(document).encode())
        score, diagnostics = validate_document(
            parsed.document, source_path="<dense-high-rate>", raw_bytes=b"{}", parsed=parsed
        )
        assert not diagnostics, diagnostics
        return score

    def test_due_group_limit_points_at_source_event(self):
        score = self.dense_at_high_rate()
        with self.assertRaises(fx.FxAdmissionError) as ctx:
            fx.serialize_compact(score, lower(score))
        diagnostic = ctx.exception.diagnostic
        self.assertEqual(diagnostic.code, "DUE_GROUP_TOO_LARGE")
        # The high tick rate widens the frame service window; the diagnostic
        # points at the actionable source field.
        self.assertEqual(diagnostic.path, "/clock/tick_rate")
        self.assertIn("service window", diagnostic.message)

    def test_gap_extent_points_at_source_event(self):
        # Regression: a 70000-tick gate leaves a 69999-tick inter-pass gap,
        # beyond the 65535-tick varint.  It must be a source-pointed
        # LIMIT_EXCEEDED admission error, not a bare host ValueError.
        score = make_score(gap_extent_document(), rel="<gap-extent>")
        with self.assertRaises(fx.FxAdmissionError) as ctx:
            fx.serialize_compact(score, lower(score))
        diagnostic = ctx.exception.diagnostic
        self.assertEqual(diagnostic.code, "LIMIT_EXCEEDED")
        self.assertEqual(diagnostic.path, "/patterns/long/events/0")
        self.assertIn("69999", diagnostic.message)
        self.assertIn("65535", diagnostic.message)
        self.assertEqual(fx.diagnostics_for(ctx.exception)[0].path, diagnostic.path)

    def test_unsupported_op_is_capability_unsupported(self):
        op = SimpleNamespace(op="slide", source="/patterns/p/events/0")
        with self.assertRaises(fx.FxAdmissionError) as ctx:
            fx._op_bytes(op)
        self.assertEqual(ctx.exception.diagnostic.code, "CAPABILITY_UNSUPPORTED")
        self.assertEqual(ctx.exception.diagnostic.path, "/patterns/p/events/0")

    def test_diagnostics_for_maps_admission_error(self):
        op = SimpleNamespace(op="lfo", source="/x")
        try:
            fx._op_bytes(op)
        except fx.FxAdmissionError as exc:
            diagnostics = fx.diagnostics_for(exc)
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].code, "CAPABILITY_UNSUPPORTED")


class CliTests(unittest.TestCase):
    def _run(self, argv):
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = cli_main(argv)
        return code, buffer.getvalue()

    def test_build_fx_exit_zero_and_artifacts(self):
        out = os.path.join(LANE, "cli-basic")
        code, payload = self._run(
            ["build", BASIC_REL, "--backend", "fx", "--out", out, "--json"]
        )
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(payload)["ok"])
        for name in ("stream.bin", "stream.h", "review.json", "report.json"):
            self.assertTrue(os.path.exists(os.path.join(out, name)), name)

    def test_build_progmem_default_unchanged(self):
        out = os.path.join(LANE, "cli-progmem")
        code, _payload = self._run(
            ["build", BASIC_REL, "--backend", "progmem", "--out", out, "--json"]
        )
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(os.path.join(out, "score.bin")))
        self.assertFalse(os.path.exists(os.path.join(out, "stream.bin")))

    def test_gap_extent_cli_reports_source_not_tool_error(self):
        # Regression: the oversized-gap build used to exit 3 TOOL_ERROR with an
        # empty path; it must exit 2 with a source-pointed admission diagnostic.
        out = os.path.join(LANE, "cli-gap-extent")
        os.makedirs(out, exist_ok=True)
        song = os.path.join(out, "song.json")
        with open(song, "w", encoding="utf-8") as handle:
            json.dump(gap_extent_document(), handle)
        code, payload = self._run(
            [
                "build",
                song,
                "--backend",
                "fx",
                "--out",
                os.path.join(out, "assets"),
                "--json",
            ]
        )
        self.assertEqual(code, 2)
        body = json.loads(payload)
        self.assertFalse(body["ok"])
        diagnostic = body["diagnostics"][0]
        self.assertEqual(diagnostic["code"], "LIMIT_EXCEEDED")
        self.assertEqual(diagnostic["path"], "/patterns/long/events/0")
        self.assertFalse(
            os.path.exists(os.path.join(out, "assets", "stream.bin")),
            "inadmissible source must not produce assets",
        )

    def test_validate_and_render_reject_fx(self):
        code, payload = self._run(["validate", BASIC_REL, "--backend", "fx", "--json"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(payload)["diagnostics"][0]["code"], "BACKEND_UNAVAILABLE")
        code, _payload = self._run(
            ["render", BASIC_REL, "--backend", "fx", "--out", LANE, "--json"]
        )
        self.assertEqual(code, 2)


class PlaybackEquivalenceTests(unittest.TestCase):
    """Host original-engine vs device-decoder trace equivalence (slow, real C)."""

    @unittest.skipUnless(shutil.which("cc") or shutil.which("clang"), "no host C compiler")
    def test_equivalence_lane_matches(self):
        script = os.path.join(REPO_ROOT, "tests/music_authoring/fx/run-fx-trace.sh")
        proc = subprocess.run(
            ["bash", script],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("equivalence: MATCH", proc.stdout)
        summary = os.path.join(LANE, "lane", "equivalence.txt")
        with open(summary, "r", encoding="utf-8") as handle:
            text = handle.read()
        self.assertEqual(text.count("result=MATCH"), 2)


if __name__ == "__main__":
    unittest.main()
