"""Round-trip: build_835(txn) → parse_835 reproduces the remittance."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from edipipe import parse_835
from edipipe.core import Delimiters
from edipipe.read.x12_835 import (
    Adjustment835,
    Claim835,
    ProviderAdjustment835,
    Service835,
    Transaction835,
)
import pytest

from edipipe.write import AchDetails, build_835


def _txn() -> Transaction835:
    paid = Claim835(
        patient_control_number="PCN1", status_code="1", charge_amount=Decimal("250"),
        payment_amount=Decimal("142.50"), patient_responsibility=Decimal("5"), filing_indicator="MC",
        payer_claim_control_number="AHP-0001", facility_type_code="11", frequency_code="1",
        patient_last="RIVERA", patient_first="ANA", patient_identifier="PV000123",
        rendering_npi="1234567893", statement_period_start=date(2026, 9, 3), received_date=date(2026, 9, 5),
        services=[
            Service835("99214", ["25"], Decimal("150"), Decimal("92.50"), units=Decimal("1"),
                       service_date=date(2026, 9, 3),
                       adjustments=[Adjustment835("service", "CO", "45", Decimal("52.50")),
                                    Adjustment835("service", "PR", "3", Decimal("5"))]),
            Service835("83036", [], Decimal("100"), Decimal("50"), units=Decimal("1"),
                       adjustments=[Adjustment835("service", "CO", "45", Decimal("50"))]),
        ],
    )
    denied = Claim835(
        patient_control_number="PCN2", status_code="4", charge_amount=Decimal("150"),
        payment_amount=Decimal("0"), patient_responsibility=Decimal("0"), filing_indicator="MC",
        payer_claim_control_number="AHP-0002", facility_type_code="11", frequency_code="1",
        patient_identifier="PV000999",
        adjustments=[Adjustment835("claim", "CO", "27", Decimal("150"))],
        services=[Service835("99213", [], Decimal("150"), Decimal("0"), remark_codes=["N30"])],
    )
    return Transaction835(
        payment_amount=Decimal("142.50"), payment_method="ACH", payment_date=date(2026, 9, 12),
        trace_number="EFT0001", payer_name="ALPINE HEALTH PLAN", payer_id="ALPHP",
        payee_name="CLINICA SAN JUAN", payee_npi="1234567893", claims=[paid, denied],
        provider_adjustments=[ProviderAdjustment835("1234567893", date(2026, 12, 31), "WO", "OVP1", Decimal("0"))],
    )


def _check(raw: str) -> None:
    f = parse_835(raw)
    t = f.transactions[0]
    assert t.payment_amount == Decimal("142.50") and t.payment_method == "ACH"
    assert t.payment_date == date(2026, 9, 12) and t.trace_number == "EFT0001"
    assert t.payer_name == "ALPINE HEALTH PLAN" and t.payer_id == "ALPHP"
    assert t.payee_npi == "1234567893"
    c1, c2 = t.claims
    assert (c1.status_code, c1.payment_amount, c1.patient_responsibility) == ("1", Decimal("142.50"), Decimal("5"))
    assert c1.patient_identifier == "PV000123" and c1.rendering_npi == "1234567893"
    assert c1.statement_period_start == date(2026, 9, 3) and c1.received_date == date(2026, 9, 5)
    s1 = c1.services[0]
    assert s1.procedure_code == "99214" and s1.modifiers == ["25"] and s1.service_date == date(2026, 9, 3)
    assert [(a.group_code, a.reason_code, a.amount) for a in s1.adjustments] == [
        ("CO", "45", Decimal("52.50")), ("PR", "3", Decimal("5"))]
    assert c2.status_code == "4"
    assert [(a.level, a.reason_code) for a in c2.adjustments] == [("claim", "27")]
    assert c2.services[0].remark_codes == ["N30"]
    assert t.provider_adjustments[0].reason_code == "WO"
    # balancing: BPR02 == sum(CLP04) - sum(PLB)
    assert t.payment_amount == sum(c.payment_amount for c in t.claims) - sum(
        p.amount for p in t.provider_adjustments)


def test_835_roundtrip():
    _check(build_835(_txn(), sender="ALPHP", receiver="1234567893",
                     interchange_date=date(2026, 9, 12), control="7", ach=ACH))


def test_835_roundtrip_custom_delimiters():
    _check(build_835(_txn(), sender="ALPHP", receiver="1234567893", interchange_date=date(2026, 9, 12),
                     control="8", ach=ACH,
                     delims=Delimiters(element="|", component=">", segment="\n", repetition="^")))


ACH = AchDetails(sender_dfi="011000015", sender_account="000111", originating_company_id="1660000001",
                 receiver_dfi="021000021", receiver_account="999888")


def test_835_ach_requires_bank_details():
    with pytest.raises(ValueError):
        build_835(_txn(), sender="ALPHP", receiver="P", interchange_date=date(2026, 9, 12), control="9")
    raw = build_835(_txn(), sender="ALPHP", receiver="P", interchange_date=date(2026, 9, 12), control="9", ach=ACH)
    bpr = next(s for s in raw.split("~") if s.strip().startswith("BPR")).strip().split("*")
    assert bpr[4:16] == ["ACH", "CCP", "01", "011000015", "DA", "000111", "1660000001", "", "01",
                         "021000021", "DA", "999888"]
    assert bpr[16] == "20260912"


def test_835_check_payment_without_bank_details():
    txn = replace(_txn(), payment_method=None)
    t = parse_835(build_835(txn, sender="ALPHP", receiver="P", interchange_date=date(2026, 9, 12),
                            control="10")).transactions[0]
    assert t.payment_method == "CHK" and t.payment_amount == Decimal("142.50")


def test_835_inpatient_keeps_claim_remarks():
    txn = _txn()
    txn.claims[0] = replace(txn.claims[0], covered_days=Decimal("3"), drg_amount=Decimal("80"),
                            remark_codes=["N30", "MA01", "M15"])
    c = parse_835(build_835(txn, sender="ALPHP", receiver="P", interchange_date=date(2026, 9, 12),
                            control="11", ach=ACH)).transactions[0].claims[0]
    assert c.covered_days == Decimal("3") and c.drg_amount == Decimal("80")
    assert c.remark_codes == ["N30", "MA01", "M15"]
