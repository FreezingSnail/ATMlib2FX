"""Regression tests for the compact-FX ``capabilities --json`` report."""

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
from music_authoring.fx_backend import capability_summary  # noqa: E402
from music_authoring.score import (  # noqa: E402
    CHANNEL_NAMES,
    ENGINE_NAME,
    HOST_LIMITS,
    SCHEMA_VERSION,
    TICK_BASE_HZ,
    TOOL_NAME,
    TOOL_VERSION,
)


def _run_cli(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(argv)
    return code, json.loads(buf.getvalue())


class CapabilityAvailabilityTests(unittest.TestCase):
    def test_fx_backend_is_the_only_backend(self):
        summary = capability_summary()
        self.assertEqual(list(summary["backends"]), ["fx"])
        self.assertTrue(summary["backends"]["fx"]["available"])

    def test_cli_surface_reports_fx_backend(self):
        code, payload = _run_cli(["capabilities", "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(list(payload["backends"]), ["fx"])
        self.assertTrue(payload["capabilities"]["validate"]["available"])
        self.assertTrue(payload["capabilities"]["build"]["available"])

    def test_removed_commands_are_not_advertised(self):
        summary = capability_summary()
        for name in ("inspect", "render", "wav_preview", "progmem"):
            self.assertNotIn(name, summary["capabilities"])
            self.assertNotIn(name, summary["backends"])


class CapabilityStableFieldsTests(unittest.TestCase):
    def test_consumer_fields_unchanged(self):
        summary = capability_summary()
        self.assertEqual(summary["schema_version"], SCHEMA_VERSION)
        self.assertEqual(summary["tool"], {"name": TOOL_NAME, "version": TOOL_VERSION})
        self.assertEqual(summary["engine"]["name"], ENGINE_NAME)
        self.assertEqual(summary["channels"], list(CHANNEL_NAMES))
        self.assertEqual(summary["engine"]["tick_base_hz"], TICK_BASE_HZ)
        self.assertEqual(summary["host_limits"], dict(HOST_LIMITS))

    def test_features_list_is_fx_only(self):
        features = capability_summary()["features"]
        self.assertIn("fx_stream_export", features)
        self.assertIn("finite_v1_fx", features)
        self.assertNotIn("progmem_export", features)
