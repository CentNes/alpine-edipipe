"""Round-trip test for the 277 claim-status-response generator.

build_277(claims) then parse_277 reproduces each claim's ids, status category/code
(and rolled-up status), amounts and service dates. parse_277 filtering to X212
groups also proves the generator emits the claim-status 277, not a 277CA.
"""

from datetime import date
from decimal import Decimal

from edipipe.read.x12_claim_status import ClaimStatus, parse_277
from edipipe.write import build_277


def test_277_roundtrips_through_reader():
    claims = [
        ClaimStatus(
            member_id="M1", trace_number="T1", patient_control_number="PCN1",
            payer_claim_control_number="ICN1", bill_type="111",
            status_category="F1", status_code="1", status_date=date(2026, 7, 20),
            charge_amount=Decimal("500.00"), paid_amount=Decimal("450.00"),
            service_from=date(2026, 7, 1), service_to=date(2026, 7, 1),
        ),
        ClaimStatus(member_id="M2", trace_number="T2", status_category="F2",
                    status_code="88", charge_amount=Decimal("300.00")),
    ]
    raw = build_277(claims, sender="ALPINEFM", receiver="SUB1",
                    interchange_date=date(2026, 7, 25), control="1")
    parsed = parse_277(raw)   # X212-only filter; proves it's not a 277CA
    assert parsed.transaction == "277" and parsed.claim_count == 2

    a = next(c for c in parsed.claims if c.member_id == "M1")
    assert a.trace_number == "T1"
    assert a.patient_control_number == "PCN1" and a.payer_claim_control_number == "ICN1"
    assert a.bill_type == "111"
    assert a.status == "paid" and a.status_category == "F1" and a.status_code == "1"
    assert a.charge_amount == Decimal("500.00") and a.paid_amount == Decimal("450.00")
    assert a.service_from == date(2026, 7, 1)

    b = next(c for c in parsed.claims if c.member_id == "M2")
    assert b.status == "denied"


def test_277_traceless_claims_all_survive():
    # Regression (review Critical): TRN is required and the reader creates one claim
    # per TRN — claims without a trace_number must NOT be dropped or overwrite a peer.
    claims = [
        ClaimStatus(member_id="M1", status_category="F1", paid_amount=Decimal("100.00")),
        ClaimStatus(member_id="M2", status_category="F2", charge_amount=Decimal("300.00")),
    ]
    raw = build_277(claims, sender="S", receiver="R",
                    interchange_date=date(2026, 7, 25), control="1")
    parsed = parse_277(raw)
    assert parsed.claim_count == 2
    assert {c.member_id for c in parsed.claims} == {"M1", "M2"}
    assert next(c for c in parsed.claims if c.member_id == "M1").status == "paid"
    assert next(c for c in parsed.claims if c.member_id == "M2").status == "denied"
