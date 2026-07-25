"""Round-trip test for the 271 eligibility-response generator.

build_271(subjects) then parse_271 must reproduce the subjects — member id/name/DOB,
active benefit lines (EB) and AAA rejections — including under non-default delimiters.
"""

from datetime import date

from edipipe.core import Delimiters
from edipipe.read.x12_eligibility import BenefitInfo, EligibilitySubject, parse_271
from edipipe.write import build_271


def _subjects():
    active = EligibilitySubject(
        member_id="MBR001", last="DOE", first="JANE",
        dob=date(1980, 1, 1), gender="F", trace_number="TRACE-1",
        benefits=[BenefitInfo(code="1", coverage_level="IND",
                              service_types=["30"], insurance_type="MC",
                              plan_description="PLAN VITAL")],
    )
    rejected = EligibilitySubject(
        member_id="MBR999", last="ROE", first="JOHN", trace_number="TRACE-2",
        rejections=["75"],  # subscriber not found
    )
    return [active, rejected]


def test_271_roundtrips_through_reader():
    raw = build_271(
        _subjects(), sender="ALPINEFM", receiver="PROV1",
        interchange_date=date(2026, 7, 25), control="1",
    )
    parsed = parse_271(raw)
    assert parsed.transaction == "271"
    assert parsed.subject_count == 2

    a = next(s for s in parsed.subjects if s.member_id == "MBR001")
    assert a.last == "DOE" and a.first == "JANE"
    assert a.dob == date(1980, 1, 1) and a.gender == "F"
    assert a.trace_number == "TRACE-1"
    assert a.is_active and not a.rejected
    assert a.benefits[0].service_types == ["30"]
    assert a.benefits[0].insurance_type == "MC"

    r = next(s for s in parsed.subjects if s.member_id == "MBR999")
    assert r.rejected and r.rejections == ["75"]
    assert not r.is_active


def test_271_roundtrips_non_default_delimiters():
    delims = Delimiters(element="|", component=">", repetition="~", segment="^")
    raw = build_271(
        _subjects(), sender="ALPINEFM", receiver="PROV1",
        interchange_date=date(2026, 7, 25), control="2", delims=delims,
    )
    parsed = parse_271(raw)
    assert parsed.subject_count == 2
    a = next(s for s in parsed.subjects if s.member_id == "MBR001")
    assert a.benefits[0].service_types == ["30"]  # component split honored the ">" sep
