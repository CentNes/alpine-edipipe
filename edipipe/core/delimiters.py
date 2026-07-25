"""X12 delimiter handling.

Inbound: delimiters are ALWAYS read from the received ISA header — never
assumed, never overridden by trading-partner config. Outbound generation uses
partner-configured delimiters (or `default()`).

The ISA is a fixed-width 106-character segment; the delimiters live at known
offsets:
- element separator      = raw[3]
- repetition separator   = raw[82]  (ISA11, 005010 — used by 271 EB / 278 loops)
- component separator    = raw[104] (ISA16)
- segment terminator     = raw[105]
"""

from __future__ import annotations

from dataclasses import dataclass

from edipipe.core.errors import EnvelopeError

ISA_LEN = 106


@dataclass(frozen=True)
class Delimiters:
    element: str = "*"
    component: str = ":"
    repetition: str = "^"
    segment: str = "~"

    @classmethod
    def from_isa(cls, raw: str) -> "Delimiters":
        if len(raw) < ISA_LEN:
            raise EnvelopeError("Truncated ISA header: cannot read delimiters")
        element = raw[3]
        repetition = raw[82]
        component = raw[104]
        segment = raw[105]
        # In 4010 ISA11 held a fixed "U" rather than a repetition separator.
        # We target 005010; if we see the legacy sentinel, fall back to the
        # conventional caret so downstream repetition splits stay well-defined.
        if repetition.isalnum():
            repetition = "^"
        return cls(
            element=element,
            component=component,
            repetition=repetition,
            segment=segment,
        )
