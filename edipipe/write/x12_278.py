"""X12 278 (005010X217) prior-authorization RESPONSE generator.

The write-side mirror of read/x12_prior_auth for the 278 response: a UMO/payer
returning the review decision (HCR action + review id) for a requested service,
with the authorization number, diagnoses and event dates. Built on
core.build_interchange.

The response is distinguished from the request purely by carrying HCR segments
(same ST01/version), matching the reader's content-based classification — so
parse_278(build_278(...)).kind == "response".

Round-trips through parse_278: reproduces each review's member id, request
category / certification type / service type, decision action + review id,
authorization number, diagnoses and dates, plus per-service (2000F) loops with
their own service type and decision. Reuses the reader's ServiceReview shape.
"""

from __future__ import annotations

from datetime import date

from edipipe.core import Delimiters, OutGroup, OutTransaction, build_interchange
from edipipe.read.x12_prior_auth import ServiceReview

Segment = list[str]


def _event_dtp(review: ServiceReview) -> Segment | None:
    if not review.from_date:
        return None
    f = review.from_date.strftime("%Y%m%d")
    if review.to_date and review.to_date != review.from_date:
        return ["DTP", "435", "RD8", f"{f}-{review.to_date.strftime('%Y%m%d')}"]
    return ["DTP", "435", "D8", f]


def build_278(
    reviews: list[ServiceReview],
    *,
    sender: str,
    receiver: str,
    interchange_date: date,
    control: str,
    as_response: bool = True,
    umo_name: str = "FIRST MEDICAL",
    requester_name: str = "PROVIDER",
    functional_id: str = "HI",
    version: str = "005010X217",
    delims: Delimiters = Delimiters(),
) -> str:
    """Generate a 278. as_response=True emits the HCR decision (→ a response the
    reader classifies as "response"); as_response=False omits HCR (→ a request)."""
    comp = delims.component
    body: list[Segment] = [
        ["BHT", "0007", "11", "0001", interchange_date.strftime("%Y%m%d"), "1200"],
        ["HL", "1", "", "20", "1"],
        ["NM1", "X3", "2", umo_name, "", "", "", "", "PI", sender],
        ["HL", "2", "1", "21", "1"],
        ["NM1", "1P", "2", requester_name, "", "", "", "", "XX", receiver],
    ]

    hl = 2  # highest HL id assigned so far (1 = UMO, 2 = requester)
    for r in reviews:
        subscriber_hl = hl + 1
        body.append(["HL", str(subscriber_hl), "2", "22", "1"])
        body.append(["NM1", "IL", "1", "", "", "", "", "", "MI", r.member_id or ""])
        event_hl = subscriber_hl + 1
        body.append(
            ["HL", str(event_hl), str(subscriber_hl), "EV", "1" if r.services else "0"]
        )
        body.append(
            ["UM", r.request_category or "HS", r.certification_type or "I", r.service_type or ""]
        )
        # HCR (decision) is what makes this a RESPONSE; omit it for a request.
        if as_response:
            body.append(["HCR", r.action or "A1", r.review_id or ""])
        if r.cert_number:
            body.append(["REF", "BB", r.cert_number])
        if r.diagnosis_codes:
            # Principal diagnosis is ABK, secondaries ABF (005010X217).
            body.append(
                ["HI"] + [f"{'ABK' if i == 0 else 'ABF'}{comp}{dx}"
                          for i, dx in enumerate(r.diagnosis_codes)]
            )
        dtp = _event_dtp(r)
        if dtp:
            body.append(dtp)
        hl = event_hl

        # 2000F service-level (SS) loops. Mirror what the reader reads: per
        # service, the service type (UM03) and, in a response, the decision (HCR).
        for svc in r.services:
            service_hl = hl + 1
            body.append(["HL", str(service_hl), str(event_hl), "SS", "0"])
            body.append(
                ["UM", r.request_category or "HS", r.certification_type or "I",
                 svc.service_type or ""]
            )
            if as_response:
                body.append(
                    ["HCR", svc.action or r.action or "A1",
                     svc.review_id or r.review_id or ""]
                )
            if svc.cert_number:
                body.append(["REF", "BB", svc.cert_number])
            hl = service_hl

    return build_interchange(
        [OutGroup(functional_id, version, [OutTransaction("278", body, control="0001")])],
        sender=sender,
        receiver=receiver,
        interchange_date=interchange_date,
        control=control,
        delims=delims,
    )
