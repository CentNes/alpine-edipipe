"""X12 acknowledgment readers — 999 (Functional Ack) and 277CA (Claim Ack).

Both are inbound from PRMMIS, acknowledging the encounters (837) First Medical
submits. They close the loop: 837 submitted → 999 (syntax accept/reject) →
277CA (claim-level accept/reject) → 835 (adjudication).

Ported from digitalizacion/claimspipe/ack_parser.py onto the edipipe core.
The original `detect_and_parse` (whole-file substring sniff + a ternary
precedence bug) is intentionally NOT ported — dispatch is a clean lookup on the
envelope's ST01 (parse_envelope → transaction_sets("999"|"277")).

Correlation keys produced here:
- 999:   AK1/AK102 = acknowledged functional-group control (matches the
         submitted 837's GS06); AK2/AK202 = acknowledged ST control.
- 277CA: TRN02 = the claim/patient control number (matches encounter CLM01).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from edipipe.core import ParseError, parse_envelope
from edipipe.core.envelope import TransactionSet
from edipipe.core.envelope import _at as _elem

# Status rollup values used across both ack types.
ACCEPTED = "A"
ACCEPTED_WITH_ERRORS = "E"
REJECTED = "R"


@dataclass
class AckDetail:
    """One error/status line under an acknowledged unit."""

    level: str  # "segment" | "element" | "status"
    code: str | None = None  # error or status code
    segment_id: str | None = None  # IK3: the segment in error
    position: str | None = None  # IK3 segment position / IK4 element position
    context: str | None = None  # entity code (277) / element ref / free-text


@dataclass
class AckedUnit:
    """One acknowledged transaction (999) or claim (277CA)."""

    control: str  # 999: AK202 (acked ST control); 277CA: TRN02 (claim control)
    status: str  # A | E | R
    group_control: str | None = None  # 999: AK102; None for 277CA
    details: list[AckDetail] = field(default_factory=list)


@dataclass
class AckFile:
    ack_type: str  # "999" | "277CA"
    own_interchange_control: str | None  # the ack's own ISA13
    sender_id: str | None
    receiver_id: str | None
    units: list[AckedUnit] = field(default_factory=list)
    overall_status: str = ACCEPTED
    acknowledged_group_controls: list[str] = field(default_factory=list)  # 999 AK102s


# --------------------------------------------------------------------------
# Status mapping
# --------------------------------------------------------------------------

def _map_999_status(code: str | None) -> str:
    """IK5/AK9 status code → A/E/R."""
    return {"A": ACCEPTED, "E": ACCEPTED_WITH_ERRORS, "R": REJECTED}.get(
        (code or "").upper(), REJECTED
    )


def _map_277_category(category: str) -> str:
    """277CA STC01 category code → A/E/R.

    A0/A1 = accepted, A2 = accepted with change/errors, A3–A8 = rejected.
    """
    category = (category or "").upper()
    if category in ("A0", "A1") or category.startswith("A1"):
        return ACCEPTED
    if category.startswith("A2"):
        return ACCEPTED_WITH_ERRORS
    return REJECTED


def _rollup(units: list[AckedUnit]) -> str:
    if not units:
        return ACCEPTED
    statuses = {u.status for u in units}
    if statuses == {ACCEPTED}:
        return ACCEPTED
    if REJECTED in statuses:
        return REJECTED
    return ACCEPTED_WITH_ERRORS


# --------------------------------------------------------------------------
# Body readers (one TransactionSet each)
# --------------------------------------------------------------------------

def read_999(ts: TransactionSet) -> tuple[list[AckedUnit], list[str]]:
    """Parse a 999 transaction set body → (acked units, group controls)."""
    units: list[AckedUnit] = []
    group_controls: list[str] = []
    group_control: str | None = None
    current_st: str | None = None
    details: list[AckDetail] = []

    for seg in ts.segments:
        tag = seg[0]
        if tag == "AK1":
            group_control = _elem(seg, 2)  # AK102 = acknowledged GS06
            if group_control:
                group_controls.append(group_control)
        elif tag == "AK2":
            current_st = _elem(seg, 2)  # AK202 = acknowledged ST02
            details = []
        elif tag == "IK3":
            details.append(
                AckDetail(
                    level="segment",
                    segment_id=_elem(seg, 1),
                    position=_elem(seg, 2),
                    code=_elem(seg, 4),
                )
            )
        elif tag == "IK4":
            details.append(
                AckDetail(
                    level="element",
                    position=_elem(seg, 1),
                    context=_elem(seg, 2),
                    code=_elem(seg, 3),
                )
            )
        elif tag == "IK5":
            status = _map_999_status(_elem(seg, 1))
            for i in range(2, 7):  # IK502–IK506 = implementation error codes
                code = _elem(seg, i)
                if code:
                    details.append(AckDetail(level="status", code=code))
            units.append(
                AckedUnit(
                    control=current_st or "",
                    status=status,
                    group_control=group_control,
                    details=details,
                )
            )
            current_st = None
            details = []
        # AK9 (group trailer) status is implied by the IK5 rollup; not needed.

    return units, group_controls


def read_277ca(ts: TransactionSet) -> list[AckedUnit]:
    """Parse a 277CA transaction set body → acked claim units.

    STC lines are attached to the most recent TRN (the claim-status tracking
    number). Higher-level STCs (provider/batch summaries) that precede any TRN
    are captured with an empty control — a known first-cut simplification; the
    claim-level correlation (TRN = CLM01) is what the reporting needs.
    """
    units: list[AckedUnit] = []
    current_trn: str | None = None
    comp = ts.delims.component

    for seg in ts.segments:
        tag = seg[0]
        if tag == "TRN":
            current_trn = _elem(seg, 2)  # TRN02 = claim/patient control number
        elif tag == "STC":
            composite = _elem(seg, 1) or ""
            parts = composite.split(comp)
            category = parts[0].strip() if parts else ""
            status_code = parts[1].strip() if len(parts) > 1 else None
            entity = parts[2].strip() if len(parts) > 2 else None
            status = _map_277_category(category)

            details: list[AckDetail] = []
            if status_code:
                details.append(AckDetail(level="status", code=status_code, context=entity))
            free_text = _elem(seg, 3) or _elem(seg, 4)  # STC03/STC04 message
            if free_text:
                details.append(AckDetail(level="status", context=free_text))

            units.append(
                AckedUnit(control=current_trn or "", status=status, details=details)
            )

    return units


# --------------------------------------------------------------------------
# Convenience wrappers (raw interchange → AckFile)
# --------------------------------------------------------------------------

def parse_999(raw: str) -> AckFile:
    interchange = parse_envelope(raw)
    txn_sets = interchange.transaction_sets("999")
    if not txn_sets:
        raise ParseError("Interchange contains no 999 transaction set")
    units: list[AckedUnit] = []
    group_controls: list[str] = []
    for ts in txn_sets:
        u, g = read_999(ts)
        units.extend(u)
        group_controls.extend(g)
    return AckFile(
        ack_type="999",
        own_interchange_control=interchange.control,
        sender_id=interchange.sender_id,
        receiver_id=interchange.receiver_id,
        units=units,
        overall_status=_rollup(units),
        acknowledged_group_controls=group_controls,
    )


def parse_277ca(raw: str) -> AckFile:
    interchange = parse_envelope(raw)
    # 277CA uses ST01 = "277" (distinguished from 276/277 by GS08 005010X214).
    txn_sets = interchange.transaction_sets("277")
    if not txn_sets:
        raise ParseError("Interchange contains no 277 transaction set")
    units: list[AckedUnit] = []
    for ts in txn_sets:
        units.extend(read_277ca(ts))
    return AckFile(
        ack_type="277CA",
        own_interchange_control=interchange.control,
        sender_id=interchange.sender_id,
        receiver_id=interchange.receiver_id,
        units=units,
        overall_status=_rollup(units),
    )


def parse_ack(raw: str) -> AckFile:
    """Dispatch on ST01: 999 → parse_999, 277 → parse_277ca."""
    interchange = parse_envelope(raw)
    codes = {ts.code for ts in interchange.transaction_sets()}
    if "999" in codes:
        return parse_999(raw)
    if "277" in codes:
        return parse_277ca(raw)
    raise ParseError("Interchange is neither a 999 nor a 277 acknowledgment")
