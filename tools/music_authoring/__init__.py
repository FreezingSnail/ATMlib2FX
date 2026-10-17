"""Host-side model music authoring for ATMlib2FX.

This package implements the strict v1 score contract described in
``docs/music-authoring-interface.md``.  It parses and validates source JSON,
lowers it to a canonical host event timeline and serializes the original
PROGMEM score backend.  It never generates or executes C from untrusted input.
"""

from .score import TOOL_NAME, TOOL_VERSION

__all__ = ["TOOL_NAME", "TOOL_VERSION"]
