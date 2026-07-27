"""The 837I reader extracts the subscriber member id (2010BA NM1*IL NM109).

Uses a member id distinct from the patient control number so the test proves the
value comes from NM109, not CLM01.
"""

from datetime import date

from edipipe.core import OutGroup, OutTransaction, build_interchange
from edipipe.read.x12_837i import parse_837i


def test_837i_extracts_subscriber_member_id():
    body = [
        ["BHT", "0019", "00", "0123", "20260101", "1200", "CH"],
        ["NM1", "41", "2", "SUBMITTER", "", "", "", "", "46", "SUB1"],  # submitter — ignored
        ["SBR", "P", "18", "", "", "", "", "", "", "MC"],
        ["NM1", "IL", "1", "DOE", "JANE", "", "", "", "MI", "MEMBER-XYZ"],  # subscriber
        ["DMG", "D8", "19800101", "F"],
        ["CLM", "PCN-1", "500", "", "", "11:B:1", "Y", "A", "Y", "I"],
        ["HI", "ABK:A000"],
    ]
    raw = build_interchange(
        [OutGroup("HC", "005010X223A2", [OutTransaction("837", body)])],
        sender="ALPINEFM", receiver="MMISPR", interchange_date=date(2026, 1, 1), control="1",
    )
    encs = parse_837i(raw)
    assert len(encs) == 1
    assert encs[0].member_id == "MEMBER-XYZ"          # from NM109
    assert encs[0].patient_control_number == "PCN-1"  # from CLM01 — distinct
    assert encs[0].dob == date(1980, 1, 1) and encs[0].gender == "F"
