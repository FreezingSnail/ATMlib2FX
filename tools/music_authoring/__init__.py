"""Host-side music authoring for ATMlib2FX.

Parses and validates v1 JSON, lowers it to a canonical event timeline, encodes
the engine command bytecode and exports a compact FX stream. It never generates
or executes C from untrusted input.
"""

from .score import TOOL_NAME, TOOL_VERSION

__all__ = ["TOOL_NAME", "TOOL_VERSION"]
