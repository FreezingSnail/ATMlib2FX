"""Whole-song loops against the original engine, including sparse channels."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from music_authoring.lower import lower, build_review_payload
from music_authoring.progmem_backend import build
from music_authoring.validate import validate_document, load_and_validate


class LoopTests(unittest.TestCase):
    def score(self, loop=True, channel='pulse0'):
        doc = {
            'format': 'atmlib-score', 'version': 1, 'id': 'loop_test', 'loop': loop,
            'clock': {'tick_rate': 100, 'ticks_per_beat': 25, 'beats_per_bar': 4},
            'instruments': {'p': {'voice': 'pulse', 'volume': 70, 'duty': 128}},
            'patterns': {
                'long': {'ticks': 8, 'events': [{'at': 0, 'note': 'C4', 'duration': 3, 'instrument': 'p'}]},
                'short': {'ticks': 4, 'events': [{'at': 1, 'note': 'E4', 'duration': 1, 'instrument': 'p'}]}
            },
            'tracks': {channel: [{'pattern': 'long', 'repeat': 1}], 'pulse2': [{'pattern': 'short', 'repeat': 1}]}
        }
        return validate_document(doc, source_path='<loop-test>', raw_bytes=json.dumps(doc).encode())

    def test_loop_requires_boolean(self):
        for value in (1, 0, 'true', None, {}):
            score, diagnostics = self.score(value)
            self.assertIsNone(score)
            self.assertIn(('TYPE_MISMATCH', '/loop'), [(d.code, d.path) for d in diagnostics])

    def test_original_engine_restarts_without_gap_or_short_track_drift(self):
        for channel in ('pulse0', 'pulse1'):
            with self.subTest(channel=channel):
                score, diagnostics = self.score(channel=channel)
                self.assertEqual(diagnostics, [])
                lowered = lower(score)
                self.assertEqual(build_review_payload(score, lowered)['loop'], {'start_tick': 0, 'end_tick': 8})
                out = ROOT / 'build/music-authoring/loop-tests' / channel
                build(score, lowered, str(out))
                binary = out / 'trace'
                subprocess.run(['cc', '-std=c11', '-O1', '-w',
                    '-I' + str(ROOT / 'tools/music_authoring/preview/avr_shim'),
                    '-I' + str(ROOT / 'src'), '-I' + str(out),
                    str(ROOT / 'tools/music_authoring/preview/trace_main.c'), '-o', str(binary)], check=True)
                text = subprocess.check_output([str(binary), '25'], text=True)
                rows = list(csv.DictReader(io.StringIO(text)))
                self.assertEqual(len(rows), 25 * 4)
                # Three entire cycles: note, gate, delay, tempo, active and mute
                # state match on every callback, including the restart tick.
                for tick in range(8):
                    for ch in range(4):
                        a = {k:v for k,v in rows[tick*4+ch].items() if k != 'tick'}
                        for cycle in (1, 2):
                            b = {k:v for k,v in rows[(tick+8*cycle)*4+ch].items() if k != 'tick'}
                            # A muted oscillator retains its previous pitch;
                            # compare pitch/duty only while it produces sound.
                            keys = set(a) if a['vol'] != '0' else set(a) - {'note', 'inc', 'cmod'}
                            self.assertEqual({k:a[k] for k in keys}, {k:b[k] for k in keys})
                self.assertTrue(all(r['tempo'] == '100' for r in rows))

    def test_every_catalog_song_is_a_complete_loop_with_varied_real_pacing(self):
        catalog = json.loads((ROOT / 'examples/music_authoring/catalog.json').read_text())
        bpms = set()
        for entry in catalog['entries']:
            score, diagnostics = load_and_validate(str(ROOT / entry['source']))
            self.assertEqual(diagnostics, [], entry['id'])
            self.assertTrue(score.loop, entry['id'])
            timeline = lower(score)
            self.assertEqual(len(set(timeline.track_ticks.values())), 1, entry['id'])
            self.assertLess(timeline.total_ticks / score.clock.effective_tick_rate, 60)
            bpms.add(round(score.clock.effective_bpm, 2))
        self.assertGreaterEqual(len(bpms), 10)


if __name__ == '__main__':
    unittest.main()
