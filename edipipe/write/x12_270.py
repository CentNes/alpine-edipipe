"""X12 270 (005010X279A1) eligibility-INQUIRY generator (provider-side).

The inquiry counterpart to build_271: a provider (or MCO) asking a payer whether a
member is eligible and for which benefits (EQ service-type codes). Built on
core.build_interchange; reuses the reader's EligibilitySubject shape and round-trips
through parse_270.
"""

from __future__ import annotations

from datetime import date

from edipipe.core import Delimiters, OutGroup, OutTransaction, build_interchange
from edipipe.read.x12_eligibility import EligibilitySubject

Segment = list[str]


def build_270(
    subjects: list[EligibilitySubject],
    *,
    sender: str,
    receiver: str,
    interchange_date: date,
    control: str,
    source_name: str = "PROVIDER",
    receiver_name: str = "FIRST MEDICAL",
    functional_id: str = "HS",
    version: str = "005010X279A1",
    delims: Delimiters = Delimiters(),
) -> str:
    comp = delims.component
    body: list[Segment] = [
        ["BHT", "0022", "13", "0001", interchange_date.strftime("%Y%m%d"), "1200"],
        ["HL", "1", "", "20", "1"],
        ["NM1", "1P", "2", source_name, "", "", "", "", "XX", sender],   # source = inquirer
        ["HL", "2", "1", "21", "1"],
        ["NM1", "PR", "2", receiver_name, "", "", "", "", "PI", receiver],  # receiver = payer
    ]
    hl = 3
    for s in subjects:
        body.append(["HL", str(hl), "2", "22", "0"])
        body.append(
            ["NM1", "IL", "1", s.last or "", s.first or "",
             "", "", "", "MI", s.member_id or ""]
        )
        if s.trace_number:
            body.append(["TRN", "1", s.trace_number])
        if s.dob or s.gender:
            dob = s.dob.strftime("%Y%m%d") if s.dob else ""
            body.append(["DMG", "D8", dob, s.gender or ""])
        if s.inquiries:
            # CONFORMANCE GAP (tracked, same as EB03 in x12_271): EQ service-type
            # codes are a REPEATING element (repetition sep), not a composite. Joined
            # on the component sep to match the reader; fix reader+writer together when
            # the eligibility generators are wired to a real payer.
            body.append(["EQ", comp.join(s.inquiries)])
        hl += 1

    return build_interchange(
        [OutGroup(functional_id, version, [OutTransaction("270", body, control="0001")])],
        sender=sender,
        receiver=receiver,
        interchange_date=interchange_date,
        control=control,
        delims=delims,
    )
