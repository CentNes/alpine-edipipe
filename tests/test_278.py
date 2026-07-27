"""Round-trip test for the 278 prior-auth-response generator.

build_278(reviews) carries HCR decision segments, so parse_278 classifies it as a
response and reproduces the member, request/cert/service types, decision action +
review id, authorization number, diagnoses and dates.
"""

from datetime import date

from edipipe.read.x12_prior_auth import ServiceReview, parse_278
from edipipe.write import build_278


def test_278_response_roundtrips_through_reader():
    reviews = [
        ServiceReview(
            member_id="M1", request_category="HS", certification_type="I",
            service_type="3", action="A1", review_id="REV1", cert_number="AUTH123",
            diagnosis_codes=["A000", "B001"],
            from_date=date(2026, 7, 1), to_date=date(2026, 7, 5),
        )
    ]
    raw = build_278(reviews, sender="ALPINEFM", receiver="PROV1",
                    interchange_date=date(2026, 7, 25), control="1")
    parsed = parse_278(raw)
    assert parsed.kind == "response"   # HCR present → decision
    assert parsed.review_count == 1

    r = parsed.reviews[0]
    assert r.member_id == "M1"
    assert r.action == "A1" and r.certified and r.review_id == "REV1"
    assert r.cert_number == "AUTH123"
    assert set(r.diagnosis_codes) == {"A000", "B001"}
    assert r.request_category == "HS" and r.certification_type == "I"
    assert r.service_type == "3"
    assert r.from_date == date(2026, 7, 1) and r.to_date == date(2026, 7, 5)


def test_278_request_has_no_decision():
    # as_response=False omits HCR → the reader classifies it as a request.
    reviews = [
        ServiceReview(member_id="M1", request_category="HS", certification_type="I",
                      service_type="3", from_date=date(2026, 7, 1))
    ]
    raw = build_278(reviews, sender="PROV1", receiver="ALPINEFM",
                    interchange_date=date(2026, 7, 25), control="1", as_response=False)
    parsed = parse_278(raw)
    assert parsed.kind == "request"
    r = parsed.reviews[0]
    assert r.member_id == "M1" and r.action is None
    assert r.request_category == "HS" and r.service_type == "3"
