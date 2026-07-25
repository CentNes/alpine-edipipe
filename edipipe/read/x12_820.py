"""X12 820 (005010X218) premium / capitation payment reader.

ASES sends the 820 to the MCO as the capitation (premium) payment. This reader
extracts the payment total and the per-detail remittance lines (RMR) so the
payment can be reconciled against the 834 enrollment — the same
sum-of-details == header-total check the 835 reader applies to claims.

Reader only. Envelope walking is done once by `core.parse_envelope`; this
consumes a TransactionSet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from edipipe.core import parse_envelope
from edipipe.core.convert import dec as _dec
from edipipe.core.convert import ymd8 as _d8
from edipipe.core.envelope import TransactionSet
from edipipe.core.envelope import _at as _elem

_PENNY = Decimal("0.01")


@dataclass
class RemitDetail820:
    qualifier: str | None = None  # RMR01 reference id qualifier
    reference_id: str | None = None  # RMR02 (member / group / contract)
    amount: Decimal = Decimal("0")  # RMR04
    name: str | None = None  # optional NM1 within the loop
    period: date | None = None  # optional DTM within the loop


@dataclass
class Payment820:
    credit_debit: str | None = None  # BPR01 (C credit / D debit)
    total_amount: Decimal = Decimal("0")  # BPR02
    payment_method: str | None = None  # BPR04 (ACH, CHK, NON)
    payment_date: date | None = None  # BPR16
    trace_number: str | None = None  # TRN02
    payer_name: str | None = None  # N1*PR (ASES)
    payee_name: str | None = None  # N1*PE (the MCO)
    details: list[RemitDetail820] = field(default_factory=list)

    @property
    def detail_total(self) -> Decimal:
        return sum((d.amount for d in self.details), Decimal("0"))

    @property
    def balanced(self) -> bool:
        """Detail lines reconcile to the header total (within a penny).

        Only meaningful when the 820 is itemized; a summary-only 820 has no
        RMR lines and is reported as balanced by definition.
        """
        if not self.details:
            return True
        return abs(self.total_amount - self.detail_total) <= _PENNY


def read_820(ts: TransactionSet) -> Payment820:
    """Parse a single 820 transaction set body into a Payment820."""
    pay = Payment820()
    detail: RemitDetail820 | None = None

    for seg in ts.segments:
        tag = seg[0]

        if tag == "BPR":
            pay.credit_debit = _elem(seg, 1)
            pay.total_amount = _dec(_elem(seg, 2))
            pay.payment_method = _elem(seg, 4)
            pay.payment_date = _d8(_elem(seg, 16))

        elif tag == "TRN":
            pay.trace_number = _elem(seg, 2)

        elif tag == "N1" and detail is None:
            role = _elem(seg, 1)
            if role == "PR":
                pay.payer_name = _elem(seg, 2)
            elif role == "PE":
                pay.payee_name = _elem(seg, 2)

        elif tag == "RMR":
            detail = RemitDetail820(
                qualifier=_elem(seg, 1),
                reference_id=_elem(seg, 2),
                amount=_dec(_elem(seg, 4)),
            )
            pay.details.append(detail)

        elif detail is not None and tag == "NM1":
            # A named entity inside the remittance loop (e.g. the member).
            last = _elem(seg, 3) or ""
            first = _elem(seg, 4) or ""
            detail.name = (f"{first} {last}").strip() or None

        elif detail is not None and tag == "DTM":
            detail.period = _d8(_elem(seg, 2))

    return pay


def parse_820(raw: str) -> Payment820:
    """Parse a raw 820 interchange into the first 820 payment.

    An interchange normally carries one 820; if several are present their detail
    lines are concatenated under the first payment's header.
    """
    interchange = parse_envelope(raw)
    txns = interchange.transaction_sets("820")
    if not txns:
        from edipipe.core import ParseError

        raise ParseError("Interchange contains no 820 transaction set")
    payment = read_820(txns[0])
    for ts in txns[1:]:
        payment.details.extend(read_820(ts).details)
    return payment
