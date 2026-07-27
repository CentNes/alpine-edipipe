"""X12 277 (005010X212) claim-status-response generator.

The write-side mirror of read/x12_claim_status for the 277 response: a payer
answering a 276 with each claim's status category/code, and — when finalized — the
charge and paid amounts. Built on core.build_interchange.

Emitted in an X212 functional group (GS01 "HN", version 005010X212) so it is the
claim-status 277, NOT the 277CA acknowledgment (X214, handled by ack.py) — matching
the reader's version-based disambiguation.

Round-trips through parse_277: reproduces each claim's member id, trace, control
numbers, status category/code (and rolled-up status), amounts and service dates.
Reuses the reader's ClaimStatus dataclass so read and write share one shape.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from edipipe.core import Delimiters, OutGroup, OutTransaction, build_interchange
from edipipe.read.x12_claim_status import ClaimStatus

Segment = list[str]


def _amt(a: Decimal | None) -> str:
    return "" if a is None else f"{a}"


def _dtp_472(claim: ClaimStatus) -> Segment | None:
    if not claim.service_from:
        return None
    f = claim.service_from.strftime("%Y%m%d")
    if claim.service_to and claim.service_to != claim.service_from:
        return ["DTP", "472", "RD8", f"{f}-{claim.service_to.strftime('%Y%m%d')}"]
    return ["DTP", "472", "D8", f]


def build_277(
    claims: list[ClaimStatus],
    *,
    sender: str,
    receiver: str,
    interchange_date: date,
    control: str,
    source_name: str = "FIRST MEDICAL",
    receiver_name: str = "SUBMITTER",
    provider_name: str | None = None,
    functional_id: str = "HN",
    version: str = "005010X212",
    delims: Delimiters = Delimiters(),
) -> str:
    comp = delims.component
    body: list[Segment] = [
        ["BHT", "0010", "08", "0001", interchange_date.strftime("%Y%m%d"), "1200", "DG"],
        ["HL", "1", "", "20", "1"],
        ["NM1", "PR", "2", source_name, "", "", "", "", "PI", sender],
        ["HL", "2", "1", "21", "1"],
        ["NM1", "41", "2", receiver_name, "", "", "", "", "46", receiver],
    ]
    parent = "2"
    if provider_name:
        body.append(["HL", "3", "2", "19", "1"])
        body.append(["NM1", "1P", "2", provider_name])
        parent = "3"

    hl = int(parent) + 1
    for i, c in enumerate(claims):
        body.append(["HL", str(hl), parent, "22", "0"])
        body.append(["NM1", "IL", "1", "", "", "", "", "", "MI", c.member_id or ""])
        # TRN is required in 005010X212 AND the reader creates one ClaimStatus per
        # TRN — a trace-less claim would be dropped or corrupt its neighbour, so
        # always emit one (synthesizing a control number when the caller has none).
        body.append(["TRN", "2", c.trace_number or f"NOTRACE{i + 1}"])
        category = c.status_category or "F1"
        composite = f"{category}{comp}{c.status_code}" if c.status_code else category
        status_date = c.status_date.strftime("%Y%m%d") if c.status_date else ""
        body.append(["STC", composite, status_date, "", _amt(c.charge_amount), _amt(c.paid_amount)])
        if c.patient_control_number:
            body.append(["REF", "EJ", c.patient_control_number])
        if c.payer_claim_control_number:
            body.append(["REF", "1K", c.payer_claim_control_number])
        if c.bill_type:
            body.append(["REF", "BLT", c.bill_type])
        dtp = _dtp_472(c)
        if dtp:
            body.append(dtp)
        hl += 1

    return build_interchange(
        [OutGroup(functional_id, version, [OutTransaction("277", body, control="0001")])],
        sender=sender,
        receiver=receiver,
        interchange_date=interchange_date,
        control=control,
        delims=delims,
    )
