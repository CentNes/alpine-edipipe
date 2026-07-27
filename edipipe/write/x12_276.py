"""X12 276 (005010X212) claim-status-INQUIRY generator (provider-side).

The inquiry counterpart to build_277: a provider (or MCO) asking a payer for the
status of a submitted claim — member, trace, control numbers, charge (AMT*T3) and
service dates, no STC (that's the response). Built on core.build_interchange; reuses
the reader's ClaimStatus shape and round-trips through parse_276 (X212 group).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from edipipe.core import Delimiters, OutGroup, OutTransaction, build_interchange
from edipipe.read.x12_claim_status import ClaimStatus

Segment = list[str]


def _amt(a: Decimal | None) -> str:
    return "" if a is None else f"{a}"


def build_276(
    claims: list[ClaimStatus],
    *,
    sender: str,
    receiver: str,
    interchange_date: date,
    control: str,
    source_name: str = "PROVIDER",
    receiver_name: str = "FIRST MEDICAL",
    delims: Delimiters = Delimiters(),
) -> str:
    body: list[Segment] = [
        ["BHT", "0010", "13", "0001", interchange_date.strftime("%Y%m%d"), "1200"],
        ["HL", "1", "", "20", "1"],
        ["NM1", "PR", "2", receiver_name, "", "", "", "", "PI", receiver],  # payer being asked
        ["HL", "2", "1", "21", "1"],
        ["NM1", "41", "2", source_name, "", "", "", "", "46", sender],     # requester
    ]
    hl = 3
    for i, c in enumerate(claims):
        body.append(["HL", str(hl), "2", "22", "0"])
        body.append(["NM1", "IL", "1", "", "", "", "", "", "MI", c.member_id or ""])
        # TRN required (X212) and the reader keys each claim on it — always emit.
        body.append(["TRN", "1", c.trace_number or f"NOTRACE{i + 1}"])
        if c.patient_control_number:
            body.append(["REF", "EJ", c.patient_control_number])
        if c.payer_claim_control_number:
            body.append(["REF", "1K", c.payer_claim_control_number])
        if c.bill_type:
            body.append(["REF", "BLT", c.bill_type])
        if c.charge_amount is not None:
            body.append(["AMT", "T3", _amt(c.charge_amount)])
        if c.service_from:
            f = c.service_from.strftime("%Y%m%d")
            if c.service_to and c.service_to != c.service_from:
                body.append(["DTP", "472", "RD8", f"{f}-{c.service_to.strftime('%Y%m%d')}"])
            else:
                body.append(["DTP", "472", "D8", f])
        hl += 1

    return build_interchange(
        [OutGroup("HR", "005010X212", [OutTransaction("276", body, control="0001")])],
        sender=sender,
        receiver=receiver,
        interchange_date=interchange_date,
        control=control,
        delims=delims,
    )
