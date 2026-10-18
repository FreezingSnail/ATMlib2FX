"""FX jukebox generator tests (ATMlib2FX-hlh.14).

Permanent tests for ``tools/music_authoring/fx_jukebox.py``: catalog-order
planning, stream/symbol naming, header determinism and ASCII folding, the
packer-stdout parsing, and fail-loudly reporting when the FX adapter rejects a
song. Fixture stream data and synthetic build reports are used throughout; no
toolchain (no ``atm-music``, no ``fx_image``) and no temp files are needed.
"""

from __future__ import annotations

import io
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
_TOOLS = os.path.join(REPO_ROOT, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import music_authoring.fx_jukebox as fx_jukebox  # noqa: E402

REAL_CATALOG = os.path.join(REPO_ROOT, "examples/music_authoring/catalog.json")


class FakeProc:
    """Minimal ``subprocess.CompletedProcess`` stand-in."""

    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def entry(song_id, name, source, folder="Test"):
    return {"id": song_id, "name": name, "source": source, "folder": folder}


def report(effective_tick_rate=50, total_ticks=120, loop=True, stream_bytes=269):
    features = ["notes", "rests"]
    if loop:
        features.append("whole_song_loop")
    return {
        "clock": {"effective_tick_rate": effective_tick_rate},
        "total_ticks": total_ticks,
        "required_features": features,
        "stream": {"bytes": stream_bytes},
    }


PACK_STDOUT = "\n".join(
    [
        "tool=fx_image",
        "contract=finite-v1 compact directly-consumed stream",
        "stream_count=2",
        "stream0_name=basic",
        "stream0_offset=0",
        "stream0_len=269",
        "stream0_loop=0",
        "stream1_name=stress",
        "stream1_offset=269",
        "stream1_len=101",
        "stream1_loop=1",
        "bitmap=0",
        "image_len=370",
        "data_bytes=512",
        "data_offset=16776704",
        "data_page=65534",
        "abs_image_end=16776704",
        "chip_bytes=16777216",
        "page_bytes=256",
        "fits_24bit=1",
    ]
)


class StreamNameTests(unittest.TestCase):
    def test_stream_name_keeps_catalog_ids(self):
        self.assertEqual(fx_jukebox.stream_name("cg_opening"), "cg_opening")
        self.assertEqual(fx_jukebox.stream_name("snapdragon_sprint"), "snapdragon_sprint")

    def test_stream_name_sanitizes_foreign_characters(self):
        self.assertEqual(fx_jukebox.stream_name("a-b.c"), "a_b_c")
        self.assertEqual(fx_jukebox.stream_name("9lives"), "_9lives")

    def test_is_identifier(self):
        self.assertTrue(fx_jukebox.is_identifier("basic"))
        self.assertTrue(fx_jukebox.is_identifier("_x9"))
        self.assertFalse(fx_jukebox.is_identifier("9x"))
        self.assertFalse(fx_jukebox.is_identifier("a b"))


class PlanTests(unittest.TestCase):
    def test_catalog_order_is_preserved(self):
        entries = [
            entry("cg_opening", "First Light", "examples/music_authoring/creature_gatherer/opening/song.json"),
            entry("overworld", "Gatherer's Road", "examples/music_authoring/creature_gatherer/overworld/song.json"),
            entry("basic", "Basic", "examples/music_authoring/basic/song.json"),
        ]
        plans = fx_jukebox.plan_songs(entries, fx_jukebox.REPO_ROOT)
        self.assertEqual([plan.id for plan in plans], ["cg_opening", "overworld", "basic"])
        self.assertEqual([plan.index for plan in plans], [0, 1, 2])
        self.assertEqual([plan.stream_name for plan in plans], ["cg_opening", "overworld", "basic"])

    def test_folder_falls_back_to_category(self):
        plans = fx_jukebox.plan_songs(
            [{"id": "x", "name": "X", "source": "s", "category": "Frontiers"}],
            fx_jukebox.REPO_ROOT,
        )
        self.assertEqual(plans[0].folder, "Frontiers")

    def test_duplicate_id_rejected(self):
        entries = [
            entry("dup", "One", "a"),
            entry("dup", "Two", "b"),
        ]
        with self.assertRaises(fx_jukebox.FxJukeboxError) as caught:
            fx_jukebox.plan_songs(entries, fx_jukebox.REPO_ROOT)
        self.assertEqual(caught.exception.code, "DUPLICATE_ID")

    def test_missing_key_rejected(self):
        with self.assertRaises(fx_jukebox.FxJukeboxError) as caught:
            fx_jukebox.plan_songs([{"id": "x", "name": "X"}], fx_jukebox.REPO_ROOT)
        self.assertEqual(caught.exception.code, "CATALOG_INVALID")

    def test_invalid_identifier_rejected(self):
        with self.assertRaises(fx_jukebox.FxJukeboxError) as caught:
            fx_jukebox.plan_songs(
                [entry("9bad", "N", "s")], fx_jukebox.REPO_ROOT
            )
        self.assertEqual(caught.exception.code, "CATALOG_INVALID")


class LoopFactsTests(unittest.TestCase):
    def test_loop_tenths_rounds(self):
        self.assertEqual(fx_jukebox.song_loop_tenths(report(total_ticks=500, effective_tick_rate=50)), 100)
        self.assertEqual(fx_jukebox.song_loop_tenths(report(total_ticks=1208, effective_tick_rate=384)), 31)

    def test_musical_loop_feature(self):
        self.assertTrue(fx_jukebox.musical_loop(report(loop=True)))
        self.assertFalse(fx_jukebox.musical_loop(report(loop=False)))

    def test_missing_clock_facts_rejected(self):
        with self.assertRaises(fx_jukebox.FxJukeboxError) as caught:
            fx_jukebox.song_loop_tenths({"total_ticks": 10})
        self.assertEqual(caught.exception.code, "BUILD_REPORT_INVALID")


class PackerOutputTests(unittest.TestCase):
    def test_parse_stdout_and_layout(self):
        facts = fx_jukebox.parse_fx_image_stdout(PACK_STDOUT)
        data_page, image_bytes, streams = fx_jukebox.fx_image_layout(facts)
        self.assertEqual(data_page, 65534)
        self.assertEqual(image_bytes, 370)
        self.assertEqual(len(streams), 2)
        self.assertEqual(streams[0]["name"], "basic")
        self.assertEqual(streams[0]["offset"], 0)
        self.assertEqual(streams[0]["length"], 269)
        self.assertFalse(streams[0]["stream_loop"])
        self.assertEqual(streams[1]["offset"], 269)
        self.assertTrue(streams[1]["stream_loop"])

    def test_incomplete_stdout_rejected(self):
        with self.assertRaises(fx_jukebox.FxJukeboxError) as caught:
            fx_jukebox.fx_image_layout(fx_jukebox.parse_fx_image_stdout("stream_count=2"))
        self.assertEqual(caught.exception.code, "PACK_OUTPUT_INVALID")


class FixtureStreamTests(unittest.TestCase):
    """Committed fx_image fixtures stand in for adapter output (no toolchain)."""

    def read(self, rel):
        with open(os.path.join(REPO_ROOT, rel), "rb") as handle:
            return handle.read()

    def test_fixture_magics_match_packer_loop_flag(self):
        finite = self.read("examples/music_authoring/fx/basic/expected/stream.bin")
        loop = self.read("examples/music_authoring/fx/loop/expected/stream.bin")
        self.assertEqual(finite[0], 0xC0)
        self.assertTrue(finite)
        self.assertEqual(loop[0], 0xC1)

    def test_headers_from_fixture_extents_are_deterministic(self):
        basic = self.read("examples/music_authoring/fx/basic/expected/stream.bin")
        stress = self.read("examples/music_authoring/fx/stress/expected/stream.bin")
        layout = (65534, len(basic) + len(stress), [
            {"index": 0, "name": "basic", "offset": 0, "length": len(basic), "stream_loop": False},
            {"index": 1, "name": "stress", "offset": len(basic), "length": len(stress), "stream_loop": False},
        ])
        plans = fx_jukebox.plan_songs(
            [
                entry("basic", "Basic authoring example", "examples/music_authoring/basic/song.json"),
                entry("stress", "Stress", "examples/music_authoring/fx/stress/song.json"),
            ],
            fx_jukebox.REPO_ROOT,
        )
        reports = [report(loop=True), report(loop=True)]
        page, image_bytes, records = fx_jukebox.assemble_records(plans, reports, layout)
        first = fx_jukebox.render_header(records, "cd" * 32, page, image_bytes)
        second = fx_jukebox.render_header(records, "cd" * 32, page, image_bytes)
        self.assertEqual(first, second)
        self.assertEqual(records[1].offset, len(basic))
        self.assertEqual(records[1].length, len(stress))


class AssembleTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            entry("basic", "Basic authoring example", "examples/music_authoring/basic/song.json"),
            entry("stress", "Stress", "examples/music_authoring/fx/stress/song.json"),
        ]
        self.plans = fx_jukebox.plan_songs(self.entries, fx_jukebox.REPO_ROOT)
        self.layout = fx_jukebox.fx_image_layout(
            fx_jukebox.parse_fx_image_stdout(PACK_STDOUT)
        )

    def test_records_follow_catalog_order_and_layout(self):
        reports = [report(loop=True), report(loop=False, stream_bytes=101)]
        _page, _bytes, records = fx_jukebox.assemble_records(self.plans, reports, self.layout)
        self.assertEqual([record.id for record in records], ["basic", "stress"])
        self.assertEqual(records[0].offset, 0)
        self.assertEqual(records[0].length, 269)
        self.assertTrue(records[0].loop)
        self.assertFalse(records[0].stream_loop)
        self.assertEqual(records[1].offset, 269)
        self.assertTrue(records[1].stream_loop)
        self.assertFalse(records[1].loop)

    def test_stream_order_mismatch_rejected(self):
        layout = (65534, 370, list(reversed(self.layout[2])))
        with self.assertRaises(fx_jukebox.FxJukeboxError) as caught:
            fx_jukebox.assemble_records(self.plans, [report(), report()], layout)
        self.assertEqual(caught.exception.code, "PACK_MISMATCH")


class HeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        records = [
            fx_jukebox.SongRecord(
                index=0,
                id="overworld",
                name="Gatherer's Road \u2014 Overworld",
                folder="Creature Gatherer",
                source="examples/music_authoring/creature_gatherer/overworld/song.json",
                stream_name="overworld",
                offset=0,
                length=269,
                stream_loop=False,
                loop=True,
                loop_tenths=282,
            ),
            fx_jukebox.SongRecord(
                index=1,
                id="basic",
                name="Basic authoring example",
                folder="Authoring Examples",
                source="examples/music_authoring/basic/song.json",
                stream_name="basic",
                offset=269,
                length=101,
                stream_loop=True,
                loop=True,
                loop_tenths=38,
            ),
        ]
        cls.records = records
        cls.header = fx_jukebox.render_header(records, "ab" * 32, 65534, 370)

    def test_index_constants_and_count(self):
        self.assertIn("#ifndef ATMLIB_JUKEBOX_FX_SONGS_H", self.header)
        self.assertIn("#define JUKEBOX_FX_DATA_PAGE 65534u", self.header)
        self.assertIn("#define JUKEBOX_FX_IMAGE_BYTES 370u", self.header)
        self.assertIn("#define JUKEBOX_FX_SONG_COUNT 2u", self.header)

    def test_per_song_stream_index_macros(self):
        self.assertIn("#define JUKEBOX_FX_SONG_OVERWORLD_OFFSET 0u", self.header)
        self.assertIn("#define JUKEBOX_FX_SONG_OVERWORLD_LENGTH 269u", self.header)
        self.assertIn("#define JUKEBOX_FX_SONG_OVERWORLD_LOOP 1u", self.header)
        self.assertIn("#define JUKEBOX_FX_SONG_OVERWORLD_STREAM_LOOP 0u", self.header)
        self.assertIn("#define JUKEBOX_FX_SONG_OVERWORLD_LOOP_TENTHS 282u", self.header)
        self.assertIn("#define JUKEBOX_FX_SONG_BASIC_STREAM_LOOP 1u", self.header)

    def test_display_table_and_symbols(self):
        self.assertIn("const char jukebox_fx_song_overworld_name[] PROGMEM", self.header)
        self.assertIn("const char jukebox_fx_song_overworld_folder[] PROGMEM", self.header)
        self.assertIn(
            "const struct jukebox_fx_song jukebox_fx_songs[JUKEBOX_FX_SONG_COUNT] PROGMEM = {",
            self.header,
        )
        self.assertIn("jukebox_fx_song_overworld_name, jukebox_fx_song_overworld_folder,", self.header)

    def test_display_text_is_ascii_folded(self):
        self.assertNotIn("\u2014", self.header)
        self.assertIn('"Gatherer\'s Road - Overworld"', self.header)

    def test_header_is_deterministic(self):
        again = fx_jukebox.render_header(self.records, "ab" * 32, 65534, 370)
        self.assertEqual(again, self.header)

    def test_header_shares_folding_with_progmem_jukebox(self):
        from music_authoring.jukebox import fold_text

        self.assertIn('"' + fold_text(self.records[0].name) + '"', self.header)


class AdapterFailureTests(unittest.TestCase):
    def setUp(self):
        self.plan = fx_jukebox.plan_songs(
            [entry("snapdragon_sprint", "Snapdragon Sprint", "examples/music_authoring/creature_frontiers/snapdragon_sprint/song.json")],
            fx_jukebox.REPO_ROOT,
        )[0]

    def test_success_parses_report(self):
        def run(cmd, cwd):
            self.assertIn("--backend", cmd)
            self.assertIn("fx", cmd)
            self.assertIn("--ring", cmd)
            envelope = {"ok": True, "diagnostics": [], "report": report()}
            return FakeProc(0, stdout=json.dumps(envelope), stderr="")

        built, warnings = fx_jukebox.run_song_build(
            self.plan, "build/fx-jukebox/lane", run, "tools/atm-music", fx_jukebox.REPO_ROOT, ring=32
        )
        self.assertEqual(built["total_ticks"], 120)
        self.assertEqual(warnings, [])

    def test_streaming_loops_flag_forwarded_only_when_requested(self):
        seen = []

        def run(cmd, cwd):
            seen.append(list(cmd))
            envelope = {"ok": True, "diagnostics": [], "report": report()}
            return FakeProc(0, stdout=json.dumps(envelope), stderr="")

        fx_jukebox.run_song_build(
            self.plan, "build/fx-jukebox/lane", run, "tools/atm-music",
            fx_jukebox.REPO_ROOT, ring=64, streaming_loops=True,
        )
        fx_jukebox.run_song_build(
            self.plan, "build/fx-jukebox/lane", run, "tools/atm-music",
            fx_jukebox.REPO_ROOT, ring=64,
        )
        self.assertIn("--streaming-loops", seen[0])
        self.assertIn("64", seen[0])
        self.assertNotIn("--streaming-loops", seen[1])

    def test_rejection_reports_song_and_diagnostic(self):
        def run(cmd, cwd):
            envelope = {
                "ok": False,
                "diagnostics": [
                    {
                        "code": "CAPABILITY_UNSUPPORTED",
                        "severity": "error",
                        "message": "device op 'noise_retrig' is not encodable",
                    }
                ],
                "artifacts": {},
            }
            return FakeProc(2, stdout=json.dumps(envelope), stderr="boom")

        with self.assertRaises(fx_jukebox.FxJukeboxError) as caught:
            fx_jukebox.run_song_build(
                self.plan, "build/fx-jukebox/lane", run, "tools/atm-music", fx_jukebox.REPO_ROOT
            )
        self.assertEqual(caught.exception.code, "SONG_BUILD_FAILED")
        self.assertEqual(caught.exception.song_id, "snapdragon_sprint")
        self.assertIn("snapdragon_sprint", caught.exception.message)
        self.assertIn("CAPABILITY_UNSUPPORTED", caught.exception.message)

    def test_first_rejection_aborts_the_run(self):
        calls = []

        def run(cmd, cwd):
            calls.append(cmd)
            if cmd[2].endswith("overworld/song.json"):
                return FakeProc(2, stdout=json.dumps({"ok": False, "diagnostics": []}), stderr="x")
            return FakeProc(0, stdout=json.dumps({"ok": True, "diagnostics": [], "report": report()}), stderr="")

        plans = fx_jukebox.plan_songs(
            [
                entry("basic", "Basic", "examples/music_authoring/basic/song.json"),
                entry("overworld", "Overworld", "examples/music_authoring/creature_gatherer/overworld/song.json"),
                entry("guide", "Guide", "examples/music_authoring/guide/song.json"),
            ],
            fx_jukebox.REPO_ROOT,
        )
        with self.assertRaises(fx_jukebox.FxJukeboxError) as caught:
            fx_jukebox.build_song_reports(
                plans, "build/fx-jukebox/lane", run, "tools/atm-music", fx_jukebox.REPO_ROOT
            )
        self.assertEqual(caught.exception.song_id, "overworld")
        # guide (index 2) must never have been attempted.
        self.assertEqual(len(calls), 2)

    def test_nonzero_exit_without_envelope_names_the_song(self):
        def run(cmd, cwd):
            return FakeProc(3, stdout="", stderr="tool error\nlast line")

        with self.assertRaises(fx_jukebox.FxJukeboxError) as caught:
            fx_jukebox.run_song_build(
                self.plan, "build/fx-jukebox/lane", run, "tools/atm-music", fx_jukebox.REPO_ROOT
            )
        self.assertIn("last line", caught.exception.message)


if __name__ == "__main__":
    unittest.main()
