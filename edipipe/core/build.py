"""Interchange envelope building (ISA/GS/ST) — the write-side mirror of `envelope.py`.

`parse_envelope` walks a received interchange into Interchange/FunctionalGroup/
TransactionSet. This module does the inverse: given transaction bodies, it emits a
well-formed ISA..IEA string with correct SE/GE/IEA control counts and honoring
configurable (partner) delimiters. A transaction body is the segment list WITHOUT
ST/SE — the writer adds those, exactly as the reader strips them.

Round-trip contract: `parse_envelope(build_interchange(...))` reproduces the input
groups/transactions/bodies. This is the single seam every outbound X12 generator
(837I/837P today, 270/276/278 later) sits on, so envelopes are built one way.

The ISA is fixed-width (106 chars incl. terminator); each delimiter is exactly one
char, so honoring partner delimiters never shifts the ISA delimiter offsets that
`Delimiters.from_isa` reads back (raw[3]/raw[82]/raw[104]/raw[105]).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from edipipe.core.delimiters import Delimiters

Segment = list[str]


@dataclass
class OutTransaction:
    code: str  # ST01, e.g. "837"
    segments: list[Segment]  # body only; ST/SE added by the writer
    control: str | None = None  # ST02; defaults to zero-padded ordinal


@dataclass
class OutGroup:
    functional_id: str  # GS01, e.g. "HC" for 837
    version: str  # GS08, e.g. "005010X223A2"
    transactions: list[OutTransaction] = field(default_factory=list)
    control: str | None = None  # GS06; defaults to ordinal


def render_segment(elements: Segment, delims: Delimiters) -> str:
    """Join elements with the element separator + segment terminator.

    Trailing empty elements are trimmed (X12 convention); the reader tolerates
    their presence or absence, but trimming keeps output clean and stable.
    """
    parts = ["" if e is None else str(e) for e in elements]
    while len(parts) > 1 and parts[-1] == "":
        parts.pop()
    return delims.element.join(parts) + delims.segment


def build_isa(
    delims: Delimiters,
    *,
    sender: str,
    receiver: str,
    interchange_date: date,
    control: str,
    time_: str = "1200",
    usage: str = "P",
    sender_qualifier: str = "ZZ",
    receiver_qualifier: str = "ZZ",
) -> str:
    """Emit the fixed-width ISA segment honoring `delims`.

    sender/receiver are padded/truncated to the ISA's fixed 15-char fields; the
    9-digit control lands in ISA13. ISA11 carries the repetition separator and
    ISA16 the component separator, so the delimiters the reader recovers from the
    header are exactly the ones used to render the body.
    """
    e = delims.element
    fields = [
        "ISA",
        "00", " " * 10,           # ISA01/02 authorization
        "00", " " * 10,           # ISA03/04 security
        f"{sender_qualifier:<2}"[:2], sender[:15].ljust(15),      # ISA05/06
        f"{receiver_qualifier:<2}"[:2], receiver[:15].ljust(15),  # ISA07/08
        interchange_date.strftime("%y%m%d"),  # ISA09 YYMMDD
        time_,                    # ISA10 HHMM
        delims.repetition,        # ISA11 repetition separator
        "00501",                  # ISA12 version
        control[:9].rjust(9, "0"),  # ISA13
        "0",                      # ISA14 ack requested
        usage,                    # ISA15 P/T
        delims.component,         # ISA16 component separator
    ]
    return e.join(fields) + delims.segment


def build_interchange(
    groups: list[OutGroup],
    *,
    sender: str,
    receiver: str,
    interchange_date: date,
    control: str,
    delims: Delimiters = Delimiters(),
    time_: str = "1200",
    usage: str = "P",
    sender_qualifier: str = "ZZ",
    receiver_qualifier: str = "ZZ",
) -> str:
    """Compose ISA..IEA from outbound groups, computing all control counts.

    SE01 = segments from ST through SE inclusive (len(body) + 2).
    GE01 = transaction-set count in the group.
    IEA01 = functional-group count.
    """
    out: list[str] = [
        build_isa(
            delims,
            sender=sender,
            receiver=receiver,
            interchange_date=interchange_date,
            control=control,
            time_=time_,
            usage=usage,
            sender_qualifier=sender_qualifier,
            receiver_qualifier=receiver_qualifier,
        )
    ]
    gs_date = interchange_date.strftime("%Y%m%d")  # GS04 is CCYYMMDD (8), unlike ISA09
    for gi, group in enumerate(groups, start=1):
        gs_control = group.control or str(gi)
        out.append(
            render_segment(
                ["GS", group.functional_id, sender, receiver, gs_date, time_,
                 gs_control, "X", group.version],
                delims,
            )
        )
        for ti, txn in enumerate(group.transactions, start=1):
            st_control = txn.control or f"{ti:04d}"
            out.append(render_segment(["ST", txn.code, st_control], delims))
            for seg in txn.segments:
                out.append(render_segment(seg, delims))
            se_count = len(txn.segments) + 2  # ST..SE inclusive
            out.append(render_segment(["SE", str(se_count), st_control], delims))
        out.append(render_segment(["GE", str(len(group.transactions)), gs_control], delims))
    out.append(render_segment(["IEA", str(len(groups)), control[:9].rjust(9, "0")], delims))
    return "".join(out)
