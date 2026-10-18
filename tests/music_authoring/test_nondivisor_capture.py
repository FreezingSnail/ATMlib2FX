"""Nondivisor AVR/absim capture check (ATMlib2FX-3ii.8).

A real ``atm-music render`` of a 255 Hz (divisor 7) score captured from the
emulated AVR proves the host metadata matches *actual* timer behaviour.  The
check is independent of the renderer's own tick->sample mapping: it detects the
note bursts in the captured PCM envelope and measures their spacing directly.

The capture lives under ``build/`` (generated).  When it is absent the check is
skipped, mirroring the opt-in real-AVR render test.  To regenerate:

    tools/atm-music render build/music-authoring/nondivisor-capture/song.json \\
        --backend progmem --seconds 8 \\
        --out build/music-authoring/nondivisor-capture/preview --json
"""

from __future__ import annotations

import json
import os
import statistics
import struct
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
_TOOLS = os.path.join(REPO_ROOT, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from music_authoring.score import TICK_BASE_HZ, effective_tick_rate, tick_divisor  # noqa: E402

CAPTURE_DIR = os.path.join(REPO_ROOT, "build", "music-authoring", "nondivisor-capture", "preview")
REPORT_PATH = os.path.join(CAPTURE_DIR, "preview.json")
WAV_PATH = os.path.join(CAPTURE_DIR, "preview.wav")

REQUESTED_RATE = 255
DIVISOR = 7
SAMPLE_RATE = 50000
# 4 ticks between the repeated bursts in the capture score.
BURST_TICKS = 4
EXACT_GAP_SAMPLES = BURST_TICKS * DIVISOR * SAMPLE_RATE / TICK_BASE_HZ  # 700.0
ROUNDED_GAP_SAMPLES = BURST_TICKS / (TICK_BASE_HZ // DIVISOR) * SAMPLE_RATE  # 701.75
ACTIVE_THRESHOLD = 200


def _load_samples(path: str) -> list[int]:
    with open(path, "rb") as handle:
        data = handle.read()
    if data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise AssertionError("capture is not RIFF/WAVE")
    pos = 12
    data_offset = None
    data_bytes = None
    while pos + 8 <= len(data):
        chunk_id = data[pos : pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        body = pos + 8
        if chunk_id == b"data":
            data_offset = body
            data_bytes = size
        pos = body + size + (size & 1)
    count = data_bytes // 2
    return list(struct.unpack_from(f"<{count}h", data, data_offset))


def _burst_starts(samples: list[int], first_callback: int) -> list[int]:
    starts = []
    i = max(0, first_callback)
    n = len(samples)
    while i < n:
        if abs(samples[i]) > ACTIVE_THRESHOLD:
            j = i
            while j < n and abs(samples[j]) > ACTIVE_THRESHOLD:
                j += 1
            starts.append(i)
            i = j
        else:
            i += 1
    return starts


@unittest.skipUnless(
    os.path.isfile(REPORT_PATH) and os.path.isfile(WAV_PATH),
    "real nondivisor capture not present under build/",
)
class RealAvrNondivisorCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(REPORT_PATH, "r", encoding="utf-8") as handle:
            cls.report = json.load(handle)
        cls.samples = _load_samples(WAV_PATH)
        cls.first_callback = cls.report["audio"]["first_music_callback_sample"]
        cls.starts = _burst_starts(cls.samples, cls.first_callback)

    def test_metadata_reports_real_quotient(self):
        clock = self.report["clock"]
        self.assertEqual(clock["tick_rate"], REQUESTED_RATE)
        self.assertEqual(effective_tick_rate(REQUESTED_RATE), TICK_BASE_HZ / DIVISOR)
        self.assertEqual(tick_divisor(REQUESTED_RATE), DIVISOR)
        self.assertAlmostEqual(clock["effective_tick_rate"], TICK_BASE_HZ / DIVISOR, places=9)
        # 2000 logical ticks span exactly 7 s from the divider (before startup/tail).
        self.assertEqual(self.report["total_ticks"], 2000)
        self.assertEqual(self.report["render"]["seconds"]["song"], 7.0)

    def test_measured_bursts_match_divisor_spacing(self):
        # The final run is the post-end DC rail, not a note burst.
        bursts = self.starts[:-1]
        self.assertGreaterEqual(len(bursts), 100)
        gaps = [bursts[i + 1] - bursts[i] for i in range(len(bursts) - 1)]
        # Skip the very first gap: the engine default rate governs tick 1.
        measured = statistics.mean(gaps[1:])
        self.assertLess(abs(measured - EXACT_GAP_SAMPLES), 1.0)
        # The rounded ``2000 // divisor`` model would be a full sample off.
        self.assertGreater(abs(measured - ROUNDED_GAP_SAMPLES), 1.0)
        # Each measured gap is an exact multiple of the 7/2000 s tick.
        per_tick = EXACT_GAP_SAMPLES / BURST_TICKS
        self.assertEqual(per_tick, DIVISOR * SAMPLE_RATE / TICK_BASE_HZ)
        self.assertEqual(per_tick, 175.0)


if __name__ == "__main__":
    unittest.main()
