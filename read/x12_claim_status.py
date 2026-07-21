"""X12 276 / 277 (005010X212) claim status inquiry & response reader.

The 276 is First Medical asking PRMMIS for the status of a submitted claim; the
277 (claim status response) answers with a status category/code and, if
finalized, the paid amount. One module handles both, dispatched on ST01.

IMPORTANT — 277 disambiguation: the 277CA claim *acknowledgment* (handled in
`ack.py`) also uses ST01 = "277". The two are told apart by the functional
group version (GS08): 277CA = 005010X214, this claim-status 277 = 005010X212.
So the 277 wrapper here filters transaction sets to X212 groups; it will not
pick up a 277CA, and `ack.py` keeps handling X214.

Reader only (no-regret): generation/submission of 276s is gated on the
levantamiento (Fase 3). Service-line status (2220D SVC/STC) is not broken out —
claim-level status is what the reporting needs (same simplification as 277CA).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from edipipe.core import ParseError, parse_envelope
from edipipe.core.convert import dec as _dec
from edipipe.core.convert import ymd8 as _d8
from edipipe.core.envelope import Interchange, TransactionSet
from edipipe.core.envelope import _at as _elem

# 277 STC01-1 health-care-claim-status category code → rolled-up status.
_STATUS_LABELS = {
    "paid": "Finalized — paid",
    "denied": "Finalized — denied",
    "finalized": "Finalized",
    "pending": "Pending",
    "acknowledged": "Acknowledged / received",
    "info_requested": "Additional information requested",
    "error": "Error / not found",
    "other": "Other",
    "inquiry": "Inquiry (276)",
}


def _status_rollup(category: str | None) -> str:
    """STC01-1 category code → status bucket.

    F1 finalized/payment, F2 finalized/denial, F0/F3/F4/F5 finalized (other);
    P pending, A acknowledged, R request-for-more-info, E/D error.
    """
    c = (category or "").upper()
    if c.startswith("F1"):
        return "paid"
    if c.startswith("F2"):
        return "denied"
    if c.startswith("F"):
        return "finalized"
    if c.startswith("P"):
        return "pending"
    if c.startswith("A"):
        return "acknowledged"
    if c.startswith("R"):
        return "info_requested"
    if c.startswith("E") or c.startswith("D"):
        return "error"
    return "other"


@dataclass
class ClaimStatus:
    """One claim within a 276 inquiry or a 277 response."""

    member_id: str | None = None  # the subscriber the claim belongs to
    trace_number: str | None = None  # TRN02 — correlates 277 back to 276
    patient_control_number: str | None = None  # REF*EJ (matches CLM01 / 837)
    payer_claim_control_number: str | None = None  # REF*1K (PRMMIS claim number)
    bill_type: str | None = None  # REF*BLT
    charge_amount: Decimal | None = None  # 276 AMT*T3 / 277 STC04
    paid_amount: Decimal | None = None  # 277 STC05
    service_from: date | None = None  # DTP*472
    service_to: date | None = None
    status_category: str | None = None  # 277 STC01-1
    status_code: str | None = None  # 277 STC01-2
    status_date: date | None = None  # 277 STC02
    status: str = "inquiry"  # rollup; "inquiry" for 276

    @property
    def status_label(self) -> str:
        return _STATUS_LABELS.get(self.status, self.status)


@dataclass
class ClaimStatusFile:
    transaction: str  # "276" | "277"
    own_interchange_control: str | None = None
    sender_id: str | None = None
    receiver_id: str | None = None
    source_name: str | None = None  # 2100A payer (PRMMIS/ASES)
    receiver_name: str | None = None  # 2100B information receiver
    provider_name: str | None = None  # 2100C service provider
    claims: list[ClaimStatus] = field(default_factory=list)

    @property
    def claim_count(self) -> int:
        return len(self.claims)


def _service_dates(fmt: str | None, value: str | None) -> tuple[date | None, date | None]:
    """DTP02 format + DTP03 → (from, to). RD8 = 'CCYYMMDD-CCYYMMDD' range."""
    if not value:
        return None, None
    if (fmt or "").upper() == "RD8" and "-" in value:
        start, _, end = value.partition("-")
        return _d8(start), _d8(end)
    d = _d8(value)
    return d, d


# --------------------------------------------------------------------------
# Body reader (one TransactionSet)
# --------------------------------------------------------------------------

def read_claim_status(ts: TransactionSet) -> tuple[
    list[ClaimStatus], str | None, str | None, str | None
]:
    """Parse one 276/277 body → (claims, source_name, receiver_name, provider_name)."""
    claims: list[ClaimStatus] = []
    claim: ClaimStatus | None = None
    hl_level: str | None = None
    current_member: str | None = None
    source_name: str | None = None
    receiver_name: str | None = None
    provider_name: str | None = None
    comp = ts.delims.component

    for seg in ts.segments:
        tag = seg[0]

        if tag == "HL":
            # HL03: 20 source, 21 receiver, 19 provider, 22 subscriber, 23 dependent.
            hl_level = _elem(seg, 3)

        elif tag == "NM1":
            entity_id = _elem(seg, 1)
            if hl_level == "20":
                source_name = source_name or _elem(seg, 3)
            elif hl_level == "21":
                receiver_name = receiver_name or _elem(seg, 3)
            elif hl_level == "19":
                provider_name = provider_name or _elem(seg, 3)
            elif hl_level in ("22", "23") and entity_id in ("IL", "QC", "03"):
                current_member = _elem(seg, 9)

        elif tag == "TRN":
            # A new claim-status tracking unit.
            claim = ClaimStatus(member_id=current_member, trace_number=_elem(seg, 2))
            claims.append(claim)

        elif tag == "STC" and claim is not None:  # 277 status
            composite = _elem(seg, 1) or ""
            parts = composite.split(comp)
            claim.status_category = parts[0].strip() if parts else None
            claim.status_code = parts[1].strip() if len(parts) > 1 else None
            claim.status = _status_rollup(claim.status_category)
            claim.status_date = _d8(_elem(seg, 2))
            if _elem(seg, 4) is not None:
                claim.charge_amount = _dec(_elem(seg, 4))
            if _elem(seg, 5) is not None:
                claim.paid_amount = _dec(_elem(seg, 5))

        elif tag == "REF" and claim is not None:
            qual = _elem(seg, 1)
            value = _elem(seg, 2)
            if qual == "EJ":
                claim.patient_control_number = value
            elif qual == "1K":
                claim.payer_claim_control_number = value
            elif qual == "BLT":
                claim.bill_type = value

        elif tag == "AMT" and claim is not None:  # 276 claim charge
            if _elem(seg, 1) == "T3" and claim.charge_amount is None:
                claim.charge_amount = _dec(_elem(seg, 2))

        elif tag == "DTP" and claim is not None:
            if _elem(seg, 1) == "472":  # service date(s)
                claim.service_from, claim.service_to = _service_dates(
                    _elem(seg, 2), _elem(seg, 3)
                )

    return claims, source_name, receiver_name, provider_name


# --------------------------------------------------------------------------
# Convenience wrappers (raw interchange → ClaimStatusFile)
# --------------------------------------------------------------------------

def _x212_sets(interchange: Interchange, code: str) -> list[TransactionSet]:
    """Transaction sets with ST01 == code from X212 functional groups.

    Filtering on the group version keeps the 277 claim-status response (X212)
    from colliding with the 277CA acknowledgment (X214) handled in ack.py.
    """
    out: list[TransactionSet] = []
    for group in interchange.groups:
        version = group.version or ""
        if version and "X212" not in version:
            continue
        out.extend(ts for ts in group.transactions if ts.code == code)
    return out


def _parse(raw: str, transaction: str) -> ClaimStatusFile:
    interchange = parse_envelope(raw)
    txn_sets = _x212_sets(interchange, transaction)
    if not txn_sets:
        raise ParseError(f"Interchange contains no {transaction} (X212) transaction set")

    claims: list[ClaimStatus] = []
    source_name = receiver_name = provider_name = None
    for ts in txn_sets:
        c, src, rcv, prov = read_claim_status(ts)
        claims.extend(c)
        source_name = source_name or src
        receiver_name = receiver_name or rcv
        provider_name = provider_name or prov

    return ClaimStatusFile(
        transaction=transaction,
        own_interchange_control=interchange.control,
        sender_id=interchange.sender_id,
        receiver_id=interchange.receiver_id,
        source_name=source_name,
        receiver_name=receiver_name,
        provider_name=provider_name,
        claims=claims,
    )


def parse_276(raw: str) -> ClaimStatusFile:
    """Parse a raw interchange into its 276 claim status inquiry."""
    return _parse(raw, "276")


def parse_277(raw: str) -> ClaimStatusFile:
    """Parse a raw interchange into its 277 (X212) claim status response."""
    return _parse(raw, "277")


def parse_claim_status(raw: str) -> ClaimStatusFile:
    """Dispatch on ST01 (X212 groups only): 276 → inquiry, 277 → response."""
    interchange = parse_envelope(raw)
    if _x212_sets(interchange, "276"):
        return parse_276(raw)
    if _x212_sets(interchange, "277"):
        return parse_277(raw)
    raise ParseError("Interchange is neither a 276 nor a 277 (X212) claim status transaction")
