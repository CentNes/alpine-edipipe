"""Writers take per-partner functional_id/version overrides; defaults unchanged."""

from datetime import date

from edipipe.core import parse_envelope
from edipipe.read.x12_eligibility import EligibilitySubject
from edipipe.write import build_271, generate_x12
from edipipe.write.x12_837 import X12ClaimData, X12ControlNumbers


def _subject():
    return [EligibilitySubject(member_id="M1")]


def test_271_override_applied():
    raw = build_271(_subject(), sender="S", receiver="R", interchange_date=date(2026, 7, 26),
                    control="1", functional_id="ZZ", version="005010X999")
    g = parse_envelope(raw).groups[0]
    assert g.functional_id == "ZZ" and g.version == "005010X999"


def test_271_defaults_unchanged():
    raw = build_271(_subject(), sender="S", receiver="R", interchange_date=date(2026, 7, 26),
                    control="1")
    g = parse_envelope(raw).groups[0]
    assert g.functional_id == "HB" and g.version == "005010X279A1"


def _claim():
    return X12ClaimData(
        claim_id="C1", doc_type="UB04", patient_control_number="P1", total_charges=100.0,
    )


def test_837_version_override():
    res = generate_x12([_claim()], X12ControlNumbers("1", "1", "1"), "S", "R", "837I",
                       version="005010X223A3")
    assert parse_envelope(res.content).groups[0].version == "005010X223A3"


def test_837_default_version_unchanged():
    res = generate_x12([_claim()], X12ControlNumbers("1", "1", "1"), "S", "R", "837I")
    assert parse_envelope(res.content).groups[0].version == "005010X223A2"
