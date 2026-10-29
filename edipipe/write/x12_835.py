"""X12 835 (005010X221A1) remittance generator — payer → provider.

The write-side mirror of read/x12_835: a payer that adjudicated claims emits the
payment/advice (BPR/TRN, payer/payee N1 loops, one CLP per claim with claim- and
service-level CAS, SVC lines, LQ*HE remarks, PLB provider adjustments).

Round-trip contract: parse_835(build_835(txn, ...)) reproduces the Transaction835 —
payment, trace, payer/payee, every claim with status/charge/paid/patient
responsibility, adjustments, services and remarks. Input reuses the reader's
dataclasses so read and write share one shape.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import date
from decimal import Decimal

from edipipe.core import Delimiters, OutGroup, OutTransaction, build_interchange
from edipipe.read.x12_835 import Adjustment835, Transaction835

Segment = list[str]


def _d8(d: date | None) -> str:
    return d.strftime("%Y%m%d") if d else ""


def _m(amount: Decimal | float | int | None) -> str:
    q = Decimal(str(amount or 0)).quantize(Decimal("0.01"))
    return format(q.normalize() if q == q.to_integral() else q, "f")


def _cas(adjustments: list[Adjustment835]) -> list[Segment]:
    """One CAS per group code, up to 6 reason/amount/quantity triplets each."""
    by_group: OrderedDict[str, list[Adjustment835]] = OrderedDict()
    for a in adjustments:
        by_group.setdefault(a.group_code, []).append(a)
    out: list[Segment] = []
    for group, adjs in by_group.items():
        for i in range(0, len(adjs), 6):
            seg: Segment = ["CAS", group]
            for a in adjs[i : i + 6]:
                seg += [a.reason_code, _m(a.amount), _m(a.quantity) if a.quantity is not None else ""]
            out.append(seg)
    return out


def build_835(
    txn: Transaction835,
    *,
    sender: str,
    receiver: str,
    interchange_date: date,
    control: str,
    functional_id: str = "HP",
    version: str = "005010X221A1",
    delims: Delimiters = Delimiters(),
) -> str:
    comp = delims.component
    pay_date = txn.payment_date or interchange_date
    method = txn.payment_method or ("ACH" if txn.payment_amount else "NON")
    bpr: Segment = ["BPR", "I" if txn.payment_amount else "H", _m(txn.payment_amount), "C", method]
    bpr += [""] * 11 + [_d8(pay_date)]  # BPR05..BPR15 blank, BPR16 effective date
    body: list[Segment] = [
        bpr,
        ["TRN", "1", txn.trace_number or control, "1" + (txn.payer_id or sender)[:9]],
        ["DTM", "405", _d8(txn.production_date or interchange_date)],
        ["N1", "PR", txn.payer_name or sender],
    ]
    if txn.payer_id:
        body.append(["REF", "2U", txn.payer_id])
    payee: Segment = ["N1", "PE", txn.payee_name or receiver]
    if txn.payee_npi:
        payee += ["XX", txn.payee_npi]
    body.append(payee)

    if txn.claims:
        body.append(["LX", "1"])
    for c in txn.claims:
        body.append([
            "CLP", c.patient_control_number, c.status_code, _m(c.charge_amount),
            _m(c.payment_amount), _m(c.patient_responsibility), c.filing_indicator or "MC",
            c.payer_claim_control_number or "", c.facility_type_code or "", c.frequency_code or "",
        ])
        body.extend(_cas(c.adjustments))
        if c.patient_last or c.patient_identifier:
            body.append(["NM1", "QC", "1", c.patient_last or "", c.patient_first or "",
                         "", "", "", "MI", c.patient_identifier or ""])
        if c.rendering_npi:
            body.append(["NM1", "82", "1", c.rendering_name or "", "", "", "", "", "XX", c.rendering_npi])
        if c.drg_amount is not None or c.covered_days is not None:
            body.append(["MIA", _m(c.covered_days) if c.covered_days is not None else "",
                         _m(c.outlier_amount) if c.outlier_amount is not None else "", "",
                         _m(c.drg_amount) if c.drg_amount is not None else ""])
        elif c.remark_codes:
            body.append(["MOA", "", ""] + c.remark_codes[:5])
        if c.statement_period_start:
            body.append(["DTM", "232", _d8(c.statement_period_start)])
        if c.statement_period_end:
            body.append(["DTM", "233", _d8(c.statement_period_end)])
        if c.received_date:
            body.append(["DTM", "050", _d8(c.received_date)])
        for s in c.services:
            proc = comp.join(["HC", s.procedure_code, *s.modifiers[:4]])
            body.append(["SVC", proc, _m(s.charge_amount), _m(s.paid_amount),
                         s.revenue_code or "", _m(s.units) if s.units is not None else ""])
            if s.service_date:
                body.append(["DTM", "472", _d8(s.service_date)])
            body.extend(_cas(s.adjustments))
            for rc in s.remark_codes:
                body.append(["LQ", "HE", rc])
    for p in txn.provider_adjustments:
        reason = p.reason_code + (comp + p.reference_id if p.reference_id else "")
        body.append(["PLB", p.provider_id, _d8(p.fiscal_period or pay_date), reason, _m(p.amount)])

    return build_interchange(
        [OutGroup(functional_id, version, [OutTransaction("835", body, control="0001")])],
        sender=sender,
        receiver=receiver,
        interchange_date=interchange_date,
        control=control,
        delims=delims,
    )
