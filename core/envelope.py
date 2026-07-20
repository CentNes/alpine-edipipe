"""Interchange envelope parsing (ISA/GS/ST).

Walk the envelope exactly once and yield structured TransactionSet objects.
Transaction readers consume a TransactionSet — they never re-tokenize or
re-scan the raw interchange. This is what makes dispatch a clean lookup on
ST01 (no whole-file substring scans, no ambiguous type sniffing).

Segments are kept as plain `list[str]` (element 0 = segment tag). A TransactionSet's
`segments` list holds the body only — the ST and SE control segments are consumed
by the envelope walk and excluded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from edipipe.core.convert import ymd8
from edipipe.core.delimiters import Delimiters
from edipipe.core.errors import EnvelopeError

Segment = list[str]


def _at(seg: Segment, idx: int) -> str | None:
    """Element accessor: 1-based within the segment, empty string -> None."""
    if idx < len(seg) and seg[idx] != "":
        return seg[idx]
    return None


@dataclass
class TransactionSet:
    code: str  # ST01, e.g. "835"
    control: str | None  # ST02
    segments: list[Segment]  # body only (ST/SE excluded)
    delims: Delimiters
    ordinal: int  # 1-based position within the interchange

    def element(self, seg: Segment, idx: int) -> str | None:
        return _at(seg, idx)


@dataclass
class FunctionalGroup:
    functional_id: str | None  # GS01 (e.g. "HP" for 835, "BE" for 834)
    control: str | None  # GS06
    version: str | None  # GS08 (e.g. "005010X221A1")
    transactions: list[TransactionSet] = field(default_factory=list)


@dataclass
class Interchange:
    delims: Delimiters
    interchange_date: date | None  # ISA09
    sender_id: str | None  # ISA06
    receiver_id: str | None  # ISA08
    control: str | None  # ISA13
    usage: str | None  # ISA15 ("P" production / "T" test)
    groups: list[FunctionalGroup] = field(default_factory=list)

    def transaction_sets(self, code: str | None = None) -> list[TransactionSet]:
        return [
            ts
            for group in self.groups
            for ts in group.transactions
            if code is None or ts.code == code
        ]


def _tokenize(raw: str, delims: Delimiters) -> list[Segment]:
    segments: list[Segment] = []
    for chunk in raw.rstrip().split(delims.segment):
        chunk = chunk.strip("\r\n ")
        if not chunk:
            continue
        segments.append(chunk.split(delims.element))
    return segments


def parse_envelope(raw: str) -> Interchange:
    """Tokenize and structure an X12 interchange into ISA/GS/ST loops."""
    raw = raw.lstrip("﻿ \r\n\t")
    if not raw.startswith("ISA"):
        raise EnvelopeError("Not an X12 interchange: missing ISA header")
    delims = Delimiters.from_isa(raw)
    segments = _tokenize(raw, delims)

    isa = segments[0]
    interchange = Interchange(
        delims=delims,
        interchange_date=ymd8(_at(isa, 9)),
        sender_id=(_at(isa, 6) or "").strip() or None,
        receiver_id=(_at(isa, 8) or "").strip() or None,
        control=_at(isa, 13),
        usage=_at(isa, 15),
    )

    current_group: FunctionalGroup | None = None
    body: list[Segment] | None = None
    st_code: str | None = None
    st_control: str | None = None
    ordinal = 0

    for seg in segments:
        tag = seg[0]
        if tag == "ISA" or tag == "TA1":
            continue
        if tag == "GS":
            current_group = FunctionalGroup(
                functional_id=_at(seg, 1),
                control=_at(seg, 6),
                version=_at(seg, 8),
            )
            interchange.groups.append(current_group)
        elif tag == "GE":
            current_group = None
        elif tag == "ST":
            ordinal += 1
            st_code = _at(seg, 1)
            st_control = _at(seg, 2)
            body = []
            # Tolerate an ST with no enclosing GS by opening a synthetic group,
            # so a malformed-but-parseable interchange still yields its txns.
            if current_group is None:
                current_group = FunctionalGroup(functional_id=None, control=None, version=None)
                interchange.groups.append(current_group)
        elif tag == "SE":
            if body is not None and st_code is not None:
                current_group.transactions.append(
                    TransactionSet(
                        code=st_code,
                        control=st_control,
                        segments=body,
                        delims=delims,
                        ordinal=ordinal,
                    )
                )
            body = None
            st_code = None
            st_control = None
        elif tag == "IEA":
            continue
        elif body is not None:
            body.append(seg)

    return interchange
