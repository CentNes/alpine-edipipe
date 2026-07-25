"""X12 278 (005010X217) health care services review — prior authorization reader.

The 278 request is First Medical (or a provider) asking the UMO/PRMMIS to
authorize a service; the 278 response returns the review decision. Both are
ST01 = "278" in the same X217 guide, so they cannot be told apart by ST01 or
version — the response is the one that carries HCR (Health Care Services Review)
segments with the decision action code. This reader classifies by that content
(``kind`` = "request" | "response").

Reader only (no-regret): generation/submission of 278 requests is gated on the
levantamiento (Fase 3).

Per patient event (2000E) and optionally per service (2000F) it extracts the
requested service (UM), the decision (HCR action + review/cert id), the
authorization number (REF), diagnoses (HI) and the event dates (DTP).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from edipipe.core import ParseError, parse_envelope
from edipipe.core.convert import ymd8 as _d8
from edipipe.core.envelope import TransactionSet
from edipipe.core.envelope import _at as _elem

# HCR01 action code → human label (278 response decision).
HCR_ACTIONS = {
    "A1": "Certified in total",
    "A2": "Certified — partial",
    "A3": "Not certified",
    "A4": "Pended",
    "A6": "Modified",
    "CT": "Contact payer/UMO",
    "NA": "No action required",
    "C": "Cancelled",
}

# REF qualifiers that carry the authorization / certification number.
_AUTH_REF_QUALS = ("BB", "NT", "G1", "1G", "BAA")


def action_label(code: str | None) -> str:
    return HCR_ACTIONS.get((code or "").upper(), code or "")


def _first_component(value: str | None, comp: str) -> str | None:
    if not value:
        return None
    return value.split(comp)[0].strip() or None


def _dates(fmt: str | None, value: str | None) -> tuple[date | None, date | None]:
    """DTP02 format + DTP03 → (from, to). RD8 = 'CCYYMMDD-CCYYMMDD' range."""
    if not value:
        return None, None
    if (fmt or "").upper() == "RD8" and "-" in value:
        start, _, end = value.partition("-")
        return _d8(start), _d8(end)
    d = _d8(value)
    return d, d


@dataclass
class ReviewService:
    """A 2000F service-level line within a review."""

    service_type: str | None = None  # UM03 / SV first component
    action: str | None = None  # HCR01
    review_id: str | None = None  # HCR02
    cert_number: str | None = None  # REF auth/cert
    from_date: date | None = None
    to_date: date | None = None

    @property
    def action_label(self) -> str:
        return action_label(self.action)


@dataclass
class ServiceReview:
    """One 2000E patient-event review."""

    member_id: str | None = None
    request_category: str | None = None  # UM01 (AR admission, HS health services, SC specialty…)
    certification_type: str | None = None  # UM02 (I initial, R renewal, S revised…)
    service_type: str | None = None  # UM03 first component
    action: str | None = None  # HCR01 (response only)
    review_id: str | None = None  # HCR02
    cert_number: str | None = None  # REF*BB / *NT / *G1
    diagnosis_codes: list[str] = field(default_factory=list)  # HI
    from_date: date | None = None  # DTP
    to_date: date | None = None
    services: list[ReviewService] = field(default_factory=list)

    @property
    def action_label(self) -> str:
        return action_label(self.action)

    @property
    def certified(self) -> bool:
        return (self.action or "").upper() in ("A1", "A2", "A6")


@dataclass
class PriorAuthFile:
    kind: str = "request"  # "request" | "response"
    transaction: str = "278"
    own_interchange_control: str | None = None
    sender_id: str | None = None
    receiver_id: str | None = None
    umo_name: str | None = None  # 2010A (utilization management org)
    requester_name: str | None = None  # 2010B
    reviews: list[ServiceReview] = field(default_factory=list)

    @property
    def review_count(self) -> int:
        return len(self.reviews)


def read_278(ts: TransactionSet) -> tuple[list[ServiceReview], str | None, str | None, bool]:
    """Parse one 278 body → (reviews, umo_name, requester_name, is_response)."""
    reviews: list[ServiceReview] = []
    review: ServiceReview | None = None
    service: ReviewService | None = None
    hl_level: str | None = None
    current_member: str | None = None
    umo_name: str | None = None
    requester_name: str | None = None
    is_response = False
    comp = ts.delims.component

    for seg in ts.segments:
        tag = seg[0]

        if tag == "HL":
            hl_level = _elem(seg, 3)  # 20 UMO, 21 requester, 22 subscriber, 23 dependent, EV event, SS service
            if hl_level == "EV":
                review = ServiceReview(member_id=current_member)
                reviews.append(review)
                service = None
            elif hl_level == "SS" and review is not None:
                service = ReviewService()
                review.services.append(service)

        elif tag == "NM1":
            entity_id = _elem(seg, 1)
            if hl_level == "20":
                umo_name = umo_name or _elem(seg, 3)
            elif hl_level == "21":
                requester_name = requester_name or _elem(seg, 3)
            elif hl_level in ("22", "23") and entity_id in ("IL", "QC", "03"):
                current_member = _elem(seg, 9)
                if review is not None and review.member_id is None:
                    review.member_id = current_member

        elif tag == "UM":
            target = service if (hl_level == "SS" and service is not None) else review
            if isinstance(target, ServiceReview):
                target.request_category = _elem(seg, 1)
                target.certification_type = _first_component(_elem(seg, 2), comp)
                target.service_type = _first_component(_elem(seg, 3), comp)
            elif isinstance(target, ReviewService):
                target.service_type = _first_component(_elem(seg, 3), comp)

        elif tag == "HCR":  # decision — only present in a response
            is_response = True
            target = service if (hl_level == "SS" and service is not None) else review
            if target is not None:
                target.action = _elem(seg, 1)
                target.review_id = _elem(seg, 2)

        elif tag == "REF":
            if _elem(seg, 1) in _AUTH_REF_QUALS:
                target = service if (hl_level == "SS" and service is not None) else review
                if target is not None:
                    target.cert_number = _elem(seg, 2)

        elif tag == "HI" and review is not None:  # diagnoses (event level)
            for i in range(1, len(seg)):
                code = _first_component_after(_elem(seg, i), comp)
                if code:
                    review.diagnosis_codes.append(code)

        elif tag == "DTP":
            target = service if (hl_level == "SS" and service is not None) else review
            frm, to = _dates(_elem(seg, 2), _elem(seg, 3))
            if target is not None and frm is not None:
                qual = _elem(seg, 1)
                if qual == "096" and isinstance(target, ServiceReview):  # discharge → to
                    target.to_date = to or frm
                else:
                    if target.from_date is None:
                        target.from_date = frm
                    target.to_date = to or target.to_date or frm

    return reviews, umo_name, requester_name, is_response


def _first_component_after(value: str | None, comp: str) -> str | None:
    """HI diagnosis composite 'qualifier:code' → the code (second component)."""
    if not value:
        return None
    parts = value.split(comp)
    if len(parts) >= 2 and parts[1].strip():
        return parts[1].strip()
    return parts[0].strip() or None


def parse_278(raw: str) -> PriorAuthFile:
    """Parse a raw interchange into its 278; kind is inferred from HCR presence."""
    interchange = parse_envelope(raw)
    txn_sets = interchange.transaction_sets("278")
    if not txn_sets:
        raise ParseError("Interchange contains no 278 transaction set")

    reviews: list[ServiceReview] = []
    umo_name = requester_name = None
    is_response = False
    for ts in txn_sets:
        r, umo, req, resp = read_278(ts)
        reviews.extend(r)
        umo_name = umo_name or umo
        requester_name = requester_name or req
        is_response = is_response or resp

    return PriorAuthFile(
        kind="response" if is_response else "request",
        own_interchange_control=interchange.control,
        sender_id=interchange.sender_id,
        receiver_id=interchange.receiver_id,
        umo_name=umo_name,
        requester_name=requester_name,
        reviews=reviews,
    )


# Symmetry with the other eligibility/status readers.
parse_prior_auth = parse_278
