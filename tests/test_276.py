"""Round-trip test for the 276 claim-status-inquiry generator."""

from datetime import date
from decimal import Decimal

from edipipe.read.x12_claim_status import ClaimStatus, parse_276
from edipipe.write import build_276


def test_276_roundtrips_through_reader():
    claims = [
        ClaimStatus(
            member_id="M1", trace_number="T1", patient_control_number="PCN1",
            payer_claim_control_number="ICN1", charge_amount=Decimal("500.00"),
            service_from=date(2026, 7, 1), service_to=date(2026, 7, 3),
        )
    ]
    raw = build_276(claims, sender="PROV1", receiver="ALPINEFM",
                    interchange_date=date(2026, 7, 25), control="1")
    parsed = parse_276(raw)
    assert parsed.transaction == "276" and parsed.claim_count == 1
    c = parsed.claims[0]
    assert c.member_id == "M1" and c.trace_number == "T1"
    assert c.patient_control_number == "PCN1" and c.payer_claim_control_number == "ICN1"
    assert c.charge_amount == Decimal("500.00")
    assert c.status == "inquiry"   # no STC in a 276
    assert c.service_from == date(2026, 7, 1) and c.service_to == date(2026, 7, 3)
