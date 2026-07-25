"""X12 271 (005010X279A1) eligibility-response generator.

The write-side mirror of read/x12_eligibility for the 271: a payer (e.g. First
Medical) answering an inbound 270 with active/inactive benefit lines (EB) or an
AAA rejection. Built on core.build_interchange so the envelope and SE/GE/IEA
control counts are produced one way, shared with every other generator.

Round-trip contract: parse_271(build_271(subjects, ...)) reproduces the subjects —
member id / name / DOB, their EB benefit lines and AAA rejections. Input reuses the
reader's EligibilitySubject / BenefitInfo dataclasses so read and write share one
shape.

GS01 for a 271 is "HB" (Eligibility, Coverage or Benefit Information); the 270
inquiry uses "HS".
"""

from __future__ import annotations

from datetime import date

from edipipe.core import Delimiters, OutGroup, OutTransaction, build_interchange
from edipipe.read.x12_eligibility import EligibilitySubject

Segment = list[str]


def _d8(d: date | None) -> str:
    return d.strftime("%Y%m%d") if d else ""


def build_271(
    subjects: list[EligibilitySubject],
    *,
    sender: str,
    receiver: str,
    interchange_date: date,
    control: str,
    source_name: str = "FIRST MEDICAL",
    receiver_name: str = "PROVIDER",
    delims: Delimiters = Delimiters(),
) -> str:
    comp = delims.component
    body: list[Segment] = [
        ["BHT", "0022", "11", "0001", interchange_date.strftime("%Y%m%d"), "1200"],
        # 2000A information source (HL level 20) — the payer
        ["HL", "1", "", "20", "1"],
        ["NM1", "PR", "2", source_name, "", "", "", "", "PI", sender],
        # 2000B information receiver (HL level 21) — the provider/inquirer
        ["HL", "2", "1", "21", "1"],
        ["NM1", "1P", "2", receiver_name, "", "", "", "", "XX", receiver],
    ]

    hl = 3
    for subj in subjects:
        body.append(["HL", str(hl), "2", "22", "0"])
        body.append(
            ["NM1", "IL", "1", subj.last or "", subj.first or "",
             "", "", "", "MI", subj.member_id or ""]
        )
        if subj.trace_number:
            body.append(["TRN", "2", subj.trace_number])
        if subj.dob or subj.gender:
            body.append(["DMG", "D8", _d8(subj.dob), subj.gender or ""])
        for b in subj.benefits:
            services = comp.join(b.service_types) if b.service_types else ""
            body.append(
                ["EB", b.code or "", b.coverage_level or "", services,
                 b.insurance_type or "", b.plan_description or ""]
            )
        for reason in subj.rejections:
            body.append(["AAA", "N", "", reason])
        hl += 1

    return build_interchange(
        [OutGroup("HB", "005010X279A1", [OutTransaction("271", body, control="0001")])],
        sender=sender,
        receiver=receiver,
        interchange_date=interchange_date,
        control=control,
        delims=delims,
    )
