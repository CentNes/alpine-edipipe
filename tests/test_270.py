"""Round-trip test for the 270 eligibility-inquiry generator."""

from datetime import date

from edipipe.read.x12_eligibility import EligibilitySubject, parse_270
from edipipe.write import build_270


def test_270_roundtrips_through_reader():
    subjects = [
        EligibilitySubject(
            member_id="M1", last="DOE", first="JANE", dob=date(1980, 1, 1),
            gender="F", trace_number="T1", inquiries=["30", "1"],
        )
    ]
    raw = build_270(subjects, sender="PROV1", receiver="ALPINEFM",
                    interchange_date=date(2026, 7, 25), control="1")
    parsed = parse_270(raw)
    assert parsed.transaction == "270" and parsed.subject_count == 1
    s = parsed.subjects[0]
    assert s.member_id == "M1" and s.last == "DOE" and s.first == "JANE"
    assert s.dob == date(1980, 1, 1) and s.gender == "F"
    assert s.trace_number == "T1"
    assert set(s.inquiries) == {"30", "1"}
