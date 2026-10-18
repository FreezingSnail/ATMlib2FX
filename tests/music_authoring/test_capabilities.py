"""Regression tests for the ``capabilities --json`` report (ATMlib2FX-3ii.14.8).

The live capability summary must match real command support: ``inspect``,
``render`` and ``wav_preview`` are implemented and reachable from the CLI, so
the report advertises them as available and carries no obsolete closed-task
reasons. Every non-capability field existing consumers read stays stable.
"""

from __future__ import annotations

import contextlib
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

from music_authoring import cli  # noqa: E402
from music_authoring.progmem_backend import capability_summary  # noqa: E402
from music_authoring.score import (  # noqa: E402
    CHANNEL_NAMES,
    ENGINE_NAME,
    HOST_LIMITS,
    SCHEMA_VERSION,
    TICK_BASE_HZ,
    TOOL_NAME,
    TOOL_VERSION,
)

# Closed beads whose stale "owned by ..." reasons used to leak into the payload.
STALE_TASK_REFS = (
    "ATMlib2FX-3ii.2",
    "ATMlib2FX-3ii.3",
    "ATMlib2FX-3ii.6",
    "ATMlib2FX-hlh.2",
)

WORKING_COMMANDS = ("inspect", "render", "wav_preview")


def _run_cli(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(argv)
    return code, json.loads(buf.getvalue())


class CapabilityAvailabilityTests(unittest.TestCase):
    def test_working_commands_advertised_available(self):
        summary = capability_summary()
        for name in WORKING_COMMANDS:
            self.assertIn(name, summary["capabilities"])
            self.assertTrue(
                summary["capabilities"][name]["available"],
                f"{name} must be advertised available",
            )

    def test_cli_surface_reports_working_commands(self):
        code, payload = _run_cli(["capabilities", "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        for name in WORKING_COMMANDS:
            self.assertTrue(
                payload["capabilities"][name]["available"],
                f"capabilities --json must advertise {name} available",
            )


class CapabilityStaleReferenceTests(unittest.TestCase):
    def test_no_closed_task_references_in_payload(self):
        text = json.dumps(capability_summary())
        for ref in STALE_TASK_REFS:
            self.assertNotIn(ref, text)
        self.assertNotIn("is owned by", text)
        self.assertNotIn("No WAV renderer is implemented", text)


class CapabilityStableFieldsTests(unittest.TestCase):
    EXPECTED_TOP_LEVEL = {
        "schema_version",
        "tool",
        "engine",
        "features",
        "channels",
        "channel_voices",
        "pitch_range",
        "host_limits",
        "backends",
        "capabilities",
        "canonicalization",
        "review_payload_version",
    }

    def test_consumer_fields_unchanged(self):
        summary = capability_summary()
        self.assertEqual(set(summary), self.EXPECTED_TOP_LEVEL)
        self.assertEqual(summary["schema_version"], SCHEMA_VERSION)
        self.assertEqual(summary["tool"], {"name": TOOL_NAME, "version": TOOL_VERSION})
        self.assertEqual(summary["engine"]["name"], ENGINE_NAME)
        self.assertEqual(summary["engine"]["channels"], list(CHANNEL_NAMES))
        self.assertEqual(summary["engine"]["tick_base_hz"], TICK_BASE_HZ)
        self.assertEqual(summary["channels"], list(CHANNEL_NAMES))
        self.assertEqual(summary["host_limits"], dict(HOST_LIMITS))
        self.assertEqual(summary["canonicalization"], "atmlib-canonical-events-v1")
        self.assertEqual(summary["review_payload_version"], 1)
        self.assertEqual(
            summary["pitch_range"],
            {"min": "C2", "max": "D7", "note_indices": [1, 63]},
        )
        self.assertEqual(
            summary["channel_voices"],
            {"pulse0": "pulse", "pulse1": "pulse", "pulse2": "pulse", "noise": "noise"},
        )
        self.assertTrue(summary["backends"]["progmem"]["available"])
        self.assertTrue(summary["backends"]["fx"]["available"])

    def test_features_list_stable(self):
        features = capability_summary()["features"]
        for required in ("validate", "progmem_export", "fx_stream_export", "finite_v1_fx"):
            self.assertIn(required, features)
        for advertised in ("fx_loops", "fx_effects", "fx_commands"):
            self.assertIn(advertised, features)
        self.assertNotIn("fx_sfx", features)


if __name__ == "__main__":
    unittest.main()
