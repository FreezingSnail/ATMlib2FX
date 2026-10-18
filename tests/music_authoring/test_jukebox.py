"""Jukebox header generator tests (ATMlib2FX-dch).

Permanent tests for ``tools/music_authoring/jukebox.py``: deterministic header
rendering, PROGMEM symbol/table shape, byte counts that match the canonical
serializer, ASCII folding of smart punctuation, set selection, duplicate-id and
invalid-set rejection, and the real-catalog fits math.  No files are written to
temp dirs.
"""

from __future__ import annotations

import io
import contextlib
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
_TOOLS = os.path.join(REPO_ROOT, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import music_authoring.jukebox as jukebox  # noqa: E402
from music_authoring.lower import lower  # noqa: E402
from music_authoring.progmem_backend import serialize  # noqa: E402
from music_authoring.validate import load_and_validate  # noqa: E402

BASIC_SOURCE = "examples/music_authoring/basic/song.json"
GUIDE_SOURCE = "examples/music_authoring/guide/song.json"
REAL_CATALOG = os.path.join(REPO_ROOT, "examples/music_authoring/catalog.json")


def entry(song_id, name, source, folder="Test"):
    return {"id": song_id, "name": name, "source": source, "folder": folder}


def serialize_size(source):
    score, diagnostics = load_and_validate(os.path.join(REPO_ROOT, source))
    assert score is not None, diagnostics
    return len(serialize(score, lower(score), "").score_bytes)


class FoldTests(unittest.TestCase):
    def test_smart_punctuation_folds_to_ascii(self):
        self.assertEqual(jukebox.fold_text("a\u2014b\u2013c"), "a-b-c")
        self.assertEqual(jukebox.fold_text("\u2018x\u2019"), "'x'")
        self.assertEqual(jukebox.fold_text("\u201cy\u201d"), '"y"')
        self.assertEqual(jukebox.fold_text("wait\u2026"), "wait...")
        self.assertEqual(jukebox.fold_text("caf\u00e9"), "caf?")

    def test_c_escape_after_fold(self):
        self.assertEqual(jukebox.ascii_c_string('a"b\\c'), 'a\\"b\\\\c')


class RenderHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = [
            entry("basic", "Basic example", BASIC_SOURCE),
            entry("guide", "Guide example", GUIDE_SOURCE),
        ]
        cls.records = jukebox.build_songs(cls.entries, jukebox.REPO_ROOT)
        cls.header = jukebox.render_header(
            "test", "Test Set", cls.records, "ab" * 32
        )

    def test_symbols_and_guard(self):
        self.assertIn("#ifndef ATMLIB_JUKEBOX_SONGS_TEST_H", self.header)
        self.assertIn("#define ATMLIB_JUKEBOX_SONGS_TEST_H", self.header)
        self.assertIn("JUKEBOX_SONG_COUNT 2u", self.header)
        self.assertIn("JUKEBOX_SET_LABEL \"Test Set\"", self.header)
        self.assertIn('#include <avr/pgmspace.h>', self.header)
        for song_id in ("basic", "guide"):
            self.assertIn(f"const char jukebox_song_{song_id}_name[] PROGMEM", self.header)
            self.assertIn(f"const char jukebox_song_{song_id}_folder[] PROGMEM", self.header)
            self.assertIn(f"const uint8_t jukebox_song_{song_id}_score[] PROGMEM", self.header)

    def test_byte_counts_match_serializer(self):
        self.assertEqual(
            self.records[0]["bytes"],
            serialize_size(BASIC_SOURCE),
        )
        self.assertEqual(
            self.records[1]["bytes"],
            serialize_size(GUIDE_SOURCE),
        )
        for record in self.records:
            self.assertIn(f"{record['bytes']}u", self.header)

    def test_table_rows_reference_each_song(self):
        self.assertIn(
            "const struct jukebox_song jukebox_songs[JUKEBOX_SONG_COUNT] PROGMEM = {",
            self.header,
        )
        for song_id in ("basic", "guide"):
            row = f"{{ jukebox_song_{song_id}_name, jukebox_song_{song_id}_folder, jukebox_song_{song_id}_score,"
            self.assertIn(row, self.header)

    def test_display_text_is_ascii_folded(self):
        records = jukebox.build_songs(
            [entry("dash", "Gatherer's Road \u2014 Test", BASIC_SOURCE)],
            jukebox.REPO_ROOT,
        )
        header = jukebox.render_header("test", "Set", records, "00")
        self.assertNotIn("\u2014", header)
        self.assertIn('"Gatherer\'s Road - Test"', header)

    def test_render_is_deterministic(self):
        again = jukebox.render_header("test", "Test Set", self.records, "ab" * 32)
        self.assertEqual(again, self.header)


class SelectionTests(unittest.TestCase):
    def test_unknown_set_rejected(self):
        with self.assertRaises(jukebox.JukeboxError) as caught:
            jukebox.select_entries([entry("basic", "B", BASIC_SOURCE)], "bogus")
        self.assertEqual(caught.exception.code, "INVALID_SET")

    def test_duplicate_ids_rejected(self):
        entries = [
            entry("dup", "First", BASIC_SOURCE),
            entry("dup", "Second", GUIDE_SOURCE),
        ]
        with self.assertRaises(jukebox.JukeboxError) as caught:
            jukebox.build_songs(entries, jukebox.REPO_ROOT)
        self.assertEqual(caught.exception.code, "DUPLICATE_ID")

    def test_main_rejects_unknown_set_without_writing(self):
        out = os.path.join(REPO_ROOT, "build", "jukebox", "test_should_not_exist.h")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = jukebox.main(["--set", "bogus", "--out", out, "--json"])
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(out))


class RealCatalogFitsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        catalog, sha, _ = jukebox.load_catalog(REAL_CATALOG)
        cls.entries = catalog["entries"]
        cls.sha = sha

    def fits(self, set_name):
        records, _text, _label = jukebox.generate(
            set_name, self.entries, self.sha, jukebox.REPO_ROOT
        )
        song_bytes = sum(record["bytes"] for record in records)
        return song_bytes, song_bytes + jukebox.SHELL_ESTIMATE <= jukebox.DEFAULT_BUDGET_BYTES

    def test_frontiers_fits_and_all_does_not(self):
        frontiers_bytes, frontiers_fits = self.fits("frontiers")
        self.assertTrue(frontiers_fits)
        self.assertEqual(frontiers_bytes, 14100)

        gatherer_bytes, gatherer_fits = self.fits("gatherer")
        self.assertTrue(gatherer_fits)
        self.assertEqual(gatherer_bytes, 16296)

        all_bytes, all_fits = self.fits("all")
        self.assertFalse(all_fits)
        self.assertEqual(all_bytes, 30396)


if __name__ == "__main__":
    unittest.main()
