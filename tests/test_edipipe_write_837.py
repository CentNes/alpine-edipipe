"""Self-check for the lifted 837 generator (edipipe.write.x12_837).

Generates 837I/837P and parses the result back through the kernel reader to prove
the writer produces well-formed, reader-consumable interchanges. Also guards that
GS01 is "HC" for every 837 (I/P) per X12 005010.
"""

import pytest

from edipipe.core import parse_envelope
from edipipe.write import (
    X12ClaimData,
    X12ControlNumbers,
    X12Diagnosis,
    X12ServiceLine,
    generate_x12,
)


def _claim() -> X12ClaimData:
    return X12ClaimData(
        claim_id="C1",
        doc_type="UB04",
        patient_control_number="PCN-1",
        total_charges=1250.00,
        type_of_bill="0111",
        subscriber_id="MEM123",
        patient_last="DOE",
        patient_first="JANE",
        patient_dob="19800101",
        patient_sex="F",
        payer_name="FIRST MEDICAL",
        payer_id="FMHP",
        billing_provider_name="HOSPITAL X",
        billing_npi="1234567893",
        billing_tax_id="660000000",
        patient_status="01",
        diagnoses=[X12Diagnosis(sequence=1, qualifier="ABK", icd_code="A000", poa="Y")],
        service_lines=[X12ServiceLine(line_number=1, revenue_code="0450",
                                      total_charges=1250.00, units=1)],
    )


def _control() -> X12ControlNumbers:
    return X12ControlNumbers(isa_control="1", gs_control="1", st_control="1")


def test_837i_roundtrips_through_reader():
    res = generate_x12([_claim()], _control(), "ALPINEFM", "MMISPR", "837I")
    inter = parse_envelope(res.content)
    txns = inter.transaction_sets("837")
    assert len(txns) == 1
    tags = {s[0] for s in txns[0].segments}
    assert {"BHT", "CLM", "HI", "SV2", "CL1"} <= tags   # institutional loop present
    assert res.x12_type == "837I"
    assert res.total_charges == 1250.00


def test_837p_roundtrips_through_reader():
    c = _claim()
    c.doc_type = "CMS1500"
    c.place_of_service = "11"
    c.service_lines = [X12ServiceLine(line_number=1, cpt_code="99213",
                                      total_charges=150.00, units=1,
                                      diagnosis_pointers=["1"])]
    res = generate_x12([c], _control(), "ALPINEFM", "MMISPR", "837P")
    inter = parse_envelope(res.content)
    tags = {s[0] for s in inter.transaction_sets("837")[0].segments}
    assert {"BHT", "CLM", "HI", "SV1"} <= tags   # professional loop uses SV1


def test_gs01_is_hc_for_all_837():
    # GS01 for every 837 (I/P) is "HC" per X12 005010; "HP" is the 835 code.
    # (Was locked to the HP non-conformance; fixed once the accepted PRMMIS
    # reference fixture was confirmed to already use HC — see docs/demo/03-encuentro-837i.txt.)
    for x12_type in ("837I", "837P"):
        res = generate_x12([_claim()], _control(), "S", "R", x12_type)
        gs = [s for s in res.content.split("\n") if s.startswith("GS*")][0]
        assert gs.split("*")[1] == "HC", x12_type


def test_empty_claims_refused():
    with pytest.raises(ValueError):
        generate_x12([], _control(), "S", "R", "837I")
