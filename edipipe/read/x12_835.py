"""X12 835 (005010X221A1) reader — Health Care Claim Payment/Advice.

Ported from the original remitpipe/x12_835.py onto the shared edipipe core.
Envelope walking now lives in edipipe.core.envelope; this module parses the
835 *body* from a TransactionSet. Behavior is identical to the pre-port parser
(the 835 test suite is the acceptance oracle).

Supported segments: BPR, TRN, DTM (405/232/233/050/472), N1 (PR/PE), REF,
LX, CLP, CAS (claim & service level), NM1 (QC/82), MIA, MOA, SVC, LQ (HE), PLB.
Unknown situational segments are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from edipipe.core import Delimiters, ParseError, parse_envelope
from edipipe.core.convert import dec as _dec
from edipipe.core.convert import ymd8 as _d8
from edipipe.core.envelope import TransactionSet, _at as _elem


# --------------------------------------------------------------------------
# Result dataclasses
# --------------------------------------------------------------------------

@dataclass
class Adjustment835:
    level: str  # "claim" | "service"
    group_code: str  # CO, CR, OA, PI, PR
    reason_code: str
    amount: Decimal
    quantity: Decimal | None = None


@dataclass
class Service835:
    procedure_code: str
    modifiers: list[str] = field(default_factory=list)
    charge_amount: Decimal = Decimal("0")
    paid_amount: Decimal = Decimal("0")
    revenue_code: str | None = None
    units: Decimal | None = None
    service_date: date | None = None
    adjustments: list[Adjustment835] = field(default_factory=list)
    remark_codes: list[str] = field(default_factory=list)  # LQ*HE


@dataclass
class Claim835:
    patient_control_number: str
    status_code: str
    charge_amount: Decimal
    payment_amount: Decimal
    patient_responsibility: Decimal
    filing_indicator: str | None
    payer_claim_control_number: str | None
    facility_type_code: str | None
    frequency_code: str | None
    patient_last: str | None = None
    patient_first: str | None = None
    patient_identifier: str | None = None
    rendering_npi: str | None = None
    rendering_name: str | None = None
    statement_period_start: date | None = None
    statement_period_end: date | None = None
    received_date: date | None = None
    # Inpatient adjudication (MIA segment). Present only on inpatient claims;
    # relevant to APR-DRG payment validation (ASES go-live 2025-10-01).
    covered_days: Decimal | None = None  # MIA01
    outlier_amount: Decimal | None = None  # MIA02 (PPS operating outlier)
    drg_amount: Decimal | None = None  # MIA04 (claim DRG amount)
    remark_codes: list[str] = field(default_factory=list)  # MIA/MOA + LQ rollup
    adjustments: list[Adjustment835] = field(default_factory=list)
    services: list[Service835] = field(default_factory=list)

    @property
    def service_date(self) -> date | None:
        dates = [s.service_date for s in self.services if s.service_date]
        if dates:
            return min(dates)
        return self.statement_period_start

    @property
    def all_remark_codes(self) -> list[str]:
        seen: list[str] = []
        for code in self.remark_codes + [c for s in self.services for c in s.remark_codes]:
            if code and code not in seen:
                seen.append(code)
        return seen


@dataclass
class ProviderAdjustment835:
    """PLB — provider-level adjustment (positive amount reduces payment)."""

    provider_id: str
    fiscal_period: date | None
    reason_code: str
    reference_id: str | None
    amount: Decimal


@dataclass
class Transaction835:
    payment_amount: Decimal = Decimal("0")
    payment_method: str | None = None  # BPR04 (ACH, CHK, NON)
    payment_date: date | None = None  # BPR16
    trace_number: str | None = None  # TRN02
    production_date: date | None = None  # DTM*405
    payer_name: str | None = None
    payer_id: str | None = None
    payee_name: str | None = None
    payee_npi: str | None = None
    claims: list[Claim835] = field(default_factory=list)
    provider_adjustments: list[ProviderAdjustment835] = field(default_factory=list)


@dataclass
class RemitFile835:
    interchange_date: date | None
    transactions: list[Transaction835] = field(default_factory=list)

    @property
    def payment_amount(self) -> Decimal:
        return sum((t.payment_amount for t in self.transactions), Decimal("0"))

    @property
    def plb_amount(self) -> Decimal:
        return sum(
            (a.amount for t in self.transactions for a in t.provider_adjustments),
            Decimal("0"),
        )

    @property
    def claims(self) -> list[tuple[Transaction835, Claim835]]:
        return [(t, c) for t in self.transactions for c in t.claims]


# --------------------------------------------------------------------------
# Body parser (one TransactionSet -> one Transaction835)
# --------------------------------------------------------------------------

def read_835(ts: TransactionSet) -> Transaction835:
    """Parse a single 835 transaction set body into a Transaction835."""
    component_sep = ts.delims.component
    txn = Transaction835()
    claim: Claim835 | None = None
    service: Service835 | None = None
    loop_n1: str | None = None  # PR (payer) / PE (payee)

    for seg in ts.segments:
        tag = seg[0]

        if tag == "BPR":
            txn.payment_amount = _dec(_elem(seg, 2))
            txn.payment_method = _elem(seg, 4)
            txn.payment_date = _d8(_elem(seg, 16))

        elif tag == "TRN":
            txn.trace_number = _elem(seg, 2)

        elif tag == "N1":
            loop_n1 = _elem(seg, 1)
            if loop_n1 == "PR":
                txn.payer_name = _elem(seg, 2)
            elif loop_n1 == "PE":
                txn.payee_name = _elem(seg, 2)
                if _elem(seg, 3) == "XX":
                    txn.payee_npi = _elem(seg, 4)

        elif tag == "REF" and claim is None and loop_n1 == "PR":
            if _elem(seg, 1) in ("2U", "HI", "NF"):
                txn.payer_id = _elem(seg, 2)

        elif tag == "LX":
            claim = None
            service = None

        elif tag == "CLP":
            pcn = _elem(seg, 1)
            status = _elem(seg, 2)
            if pcn is None or status is None:
                raise ParseError("CLP segment missing patient control number or status code")
            claim = Claim835(
                patient_control_number=pcn,
                status_code=status,
                charge_amount=_dec(_elem(seg, 3)),
                payment_amount=_dec(_elem(seg, 4)),
                patient_responsibility=_dec(_elem(seg, 5)),
                filing_indicator=_elem(seg, 6),
                payer_claim_control_number=_elem(seg, 7),
                facility_type_code=_elem(seg, 8),
                frequency_code=_elem(seg, 9),
            )
            txn.claims.append(claim)
            service = None

        elif tag == "NM1" and claim is not None:
            qualifier = _elem(seg, 1)
            if qualifier == "QC":
                claim.patient_last = _elem(seg, 3)
                claim.patient_first = _elem(seg, 4)
                if _elem(seg, 8) in ("MI", "MR", "II", "HN"):
                    claim.patient_identifier = _elem(seg, 9)
            elif qualifier == "82":
                last = _elem(seg, 3) or ""
                first = _elem(seg, 4) or ""
                claim.rendering_name = (f"{first} {last}".strip() or None) if (first or last) else None
                if _elem(seg, 8) == "XX":
                    claim.rendering_npi = _elem(seg, 9)

        elif tag == "MIA" and claim is not None:
            # Inpatient adjudication amounts (DRG payment validation).
            claim.covered_days = _dec(_elem(seg, 1)) if _elem(seg, 1) else None
            claim.outlier_amount = _dec(_elem(seg, 2)) if _elem(seg, 2) else None
            claim.drg_amount = _dec(_elem(seg, 4)) if _elem(seg, 4) else None
            # MIA05, 20, 21, 22, 23 are remark codes
            for idx in (5, 20, 21, 22, 23):
                code = _elem(seg, idx)
                if code:
                    claim.remark_codes.append(code)

        elif tag == "MOA" and claim is not None:
            # MOA03-07 are remark codes
            for idx in (3, 4, 5, 6, 7):
                code = _elem(seg, idx)
                if code:
                    claim.remark_codes.append(code)

        elif tag == "DTM":
            qualifier = _elem(seg, 1)
            when = _d8(_elem(seg, 2))
            if qualifier == "405" and claim is None:
                txn.production_date = when
            elif claim is None:
                continue
            elif service is not None and qualifier == "472":
                service.service_date = when
            elif qualifier == "232":
                claim.statement_period_start = when
            elif qualifier == "233":
                claim.statement_period_end = when
            elif qualifier == "050":
                claim.received_date = when

        elif tag == "CAS":
            group = _elem(seg, 1)
            if group is None:
                raise ParseError("CAS segment missing group code")
            target_level = "service" if service is not None else "claim"
            triplets = seg[2:]
            for i in range(0, len(triplets), 3):
                reason = triplets[i] if i < len(triplets) else ""
                if not reason:
                    continue
                amount = _dec(triplets[i + 1] if i + 1 < len(triplets) else None)
                qty_raw = triplets[i + 2] if i + 2 < len(triplets) else ""
                adj = Adjustment835(
                    level=target_level,
                    group_code=group,
                    reason_code=reason,
                    amount=amount,
                    quantity=_dec(qty_raw) if qty_raw else None,
                )
                if service is not None:
                    service.adjustments.append(adj)
                elif claim is not None:
                    claim.adjustments.append(adj)

        elif tag == "SVC" and claim is not None:
            composite = _elem(seg, 1) or ""
            parts = composite.split(component_sep)
            proc = parts[1] if len(parts) > 1 else parts[0]
            service = Service835(
                procedure_code=proc,
                modifiers=[m for m in parts[2:6] if m],
                charge_amount=_dec(_elem(seg, 2)),
                paid_amount=_dec(_elem(seg, 3)),
                revenue_code=_elem(seg, 4),
                units=_dec(_elem(seg, 5)) if _elem(seg, 5) else None,
            )
            claim.services.append(service)

        elif tag == "LQ":
            # LQ*HE carries a RARC. It normally sits in the service (2110) loop,
            # but a claim-level LQ (no open SVC) attaches to the claim rather
            # than being dropped.
            if _elem(seg, 1) == "HE" and _elem(seg, 2):
                target = service if service is not None else claim
                if target is not None:
                    target.remark_codes.append(seg[2])

        elif tag == "PLB":
            fiscal = _d8(_elem(seg, 2))
            provider_id = _elem(seg, 1) or ""
            # PLB03/04, 05/06, ... are (composite reason, amount) pairs
            idx = 3
            while idx + 1 < len(seg):
                reason_comp = _elem(seg, idx)
                amount_raw = _elem(seg, idx + 1)
                if reason_comp:
                    comp = reason_comp.split(component_sep)
                    txn.provider_adjustments.append(
                        ProviderAdjustment835(
                            provider_id=provider_id,
                            fiscal_period=fiscal,
                            reason_code=comp[0],
                            reference_id=comp[1] if len(comp) > 1 else None,
                            amount=_dec(amount_raw),
                        )
                    )
                idx += 2

    return txn


# --------------------------------------------------------------------------
# Convenience wrapper (raw interchange -> RemitFile835)
# --------------------------------------------------------------------------

def parse_835(raw: str) -> RemitFile835:
    """Parse a raw 835 interchange. Envelope + all 835 transaction sets."""
    interchange = parse_envelope(raw)
    txn_sets = interchange.transaction_sets("835")
    if not txn_sets:
        raise ParseError("Interchange contains no 835 transaction set")

    result = RemitFile835(interchange_date=interchange.interchange_date)
    for ts in txn_sets:
        result.transactions.append(read_835(ts))
    return result
