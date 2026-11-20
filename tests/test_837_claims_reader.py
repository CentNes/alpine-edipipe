"""Round-trip: generate_x12 (837P/837I) → parse_837 reproduces payer-side claim data."""

from datetime import date
from decimal import Decimal

from edipipe.read.x12_837 import parse_837
from edipipe.write import (
    X12ClaimData,
    X12ControlNumbers,
    X12Diagnosis,
    X12ServiceLine,
    generate_x12,
)

CTRL = X12ControlNumbers(isa_control="000000101", gs_control="101", st_control="0001")


def _claim(pcn: str, **kw) -> X12ClaimData:
    base = dict(
        claim_id=pcn, doc_type="CMS1500", patient_control_number=pcn, total_charges=250.0,
        subscriber_id="PV000123", patient_last="RIVERA", patient_first="ANA",
        patient_dob="19850302", patient_sex="F", payer_name="ALPINE HEALTH PLAN", payer_id="ALPHP",
        billing_provider_name="CLINICA SAN JUAN", billing_npi="1234567893", billing_tax_id="660000001",
        referring_npi="1999999984",
        diagnoses=[X12Diagnosis(1, "ABK", "E119"), X12Diagnosis(2, "ABF", "I10")],
        service_lines=[
            X12ServiceLine(1, cpt_code="99214", modifiers=["25"], service_date=date(2026, 9, 3),
                           units=1, total_charges=150.0, place_of_service="11", diagnosis_pointers=["1", "2"]),
            X12ServiceLine(2, cpt_code="83036", service_date=date(2026, 9, 3), units=1, total_charges=100.0),
        ],
    )
    base.update(kw)
    return X12ClaimData(**base)


def test_837p_roundtrip():
    raw = generate_x12([_claim("PCN1"), _claim("PCN2", subscriber_id="PV000999", total_charges=150.0,
                                               service_lines=[X12ServiceLine(1, cpt_code="99213", units=1,
                                                                             total_charges=150.0)])],
                       CTRL, "PROV1", "ALPHP", "837P").content
    claims = parse_837(raw)
    assert [c.patient_control_number for c in claims] == ["PCN1", "PCN2"]
    c = claims[0]
    assert c.claim_type == "837P"
    assert c.member_id == "PV000123" and c.member_last == "RIVERA" and c.member_dob == date(1985, 3, 2)
    assert c.payer_id == "ALPHP"
    assert c.billing_npi == "1234567893" and c.billing_tax_id == "660000001"
    assert c.referring_npi == "1999999984"
    assert c.diagnoses == ["E119", "I10"]
    assert c.total_charge == Decimal("250")
    assert c.facility_code == "11" and c.frequency_code == "1"
    assert [ln.procedure_code for ln in c.lines] == ["99214", "83036"]
    assert c.lines[0].modifiers == ["25"] and c.lines[0].diagnosis_pointers == ["1", "2"]
    assert c.lines[0].service_date == date(2026, 9, 3) and c.lines[1].charge == Decimal("100")
    assert claims[1].member_id == "PV000999" and len(claims[1].lines) == 1


def test_837i_roundtrip_with_replacement():
    claim = _claim(
        "INST1", doc_type="UB04", type_of_bill="0117", frequency_code="7",
        original_claim_control_number="ORIG-55", statement_from="20260901", statement_to="20260904",
        admission_date="20260901", admission_type="1", admission_source="7", patient_status="01",
        attending_npi="1888888886",
        service_lines=[X12ServiceLine(1, revenue_code="0120", units=3, total_charges=3000.0,
                                      service_date=date(2026, 9, 1)),
                       X12ServiceLine(2, revenue_code="0300", hcpcs_code="80053", units=1, total_charges=80.0)],
    )
    c = parse_837(generate_x12([claim], CTRL, "HOSP1", "ALPHP", "837I").content)[0]
    assert c.claim_type == "837I"
    assert c.frequency_code == "7" and c.original_claim_number == "ORIG-55"
    assert c.statement_from == date(2026, 9, 1) and c.statement_to == date(2026, 9, 4)
    assert c.admission_date == date(2026, 9, 1) and c.patient_status == "01"
    assert c.attending_npi == "1888888886"
    assert [(ln.revenue_code, ln.procedure_code, ln.units) for ln in c.lines] == [
        ("0120", None, Decimal("3")), ("0300", "80053", Decimal("1"))]


def test_837_dependent_patient_keeps_subscriber_and_rendering_npi():
    raw = "~".join([
        "ISA*00*          *00*          *ZZ*PROV1          *ZZ*ALPHP          *260903*1200*^*00501*000000102*0*T*:",
        "GS*HC*PROV1*ALPHP*20260903*1200*102*X*005010X222A1", "ST*837*0001*005010X222A1",
        "BHT*0019*00*B1*20260903*1200*CH", "HL*1**20*1", "NM1*85*2*CLINICA GRUPO*****XX*1234567893",
        "REF*EI*660000001", "HL*2*1*22*1", "SBR*P**********MC", "NM1*IL*1*RIVERA*ANA****MI*SUB1",
        "DMG*D8*19800101*F", "NM1*PR*2*ALPINE HEALTH PLAN*****PI*ALPHP", "HL*3*2*23*0", "PAT*19",
        "NM1*QC*1*RIVERA*LUIS", "DMG*D8*20100101*M", "CLM*A1*100***11:B:1*Y*A*Y*Y", "HI*ABK:J069",
        "NM1*82*1*SOTO*MARIA****XX*9876543210", "LX*1", "SV1*HC:99213*100*UN*1***1", "DTP*472*D8*20260902",
        "NM1*82*1*CRUZ*JOSE****XX*1112223334", "SE*20*0001", "GE*1*102", "IEA*1*000000102",
    ]) + "~"
    c = parse_837(raw)[0]
    assert c.member_id == "SUB1" and c.payer_id == "ALPHP" and c.member_dob == date(1980, 1, 1)
    assert c.patient_first == "LUIS" and c.patient_dob == date(2010, 1, 1)
    assert c.billing_npi == "1234567893" and c.rendering_npi == "9876543210"
    assert c.lines[0].rendering_npi == "1112223334"
