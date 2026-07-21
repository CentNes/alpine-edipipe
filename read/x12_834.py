"""X12 834 (005010X220A1) Benefit Enrollment and Maintenance reader.

ASES sends the 834 to the MCO as the member roster — additions, terminations,
changes and audits. This reader extracts the member-level maintenance so the
platform can give visibility into the roster and later reconcile the 820
capitation against who is actually enrolled.

Reader only. The member master (persisting names/DOB/Medicaid IDs) is net-new
PHI and is GATED on the BAA + security sign-off — not built here. Envelope
walking is done once by `core.parse_envelope`; this consumes a TransactionSet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from edipipe.core import parse_envelope
from edipipe.core.convert import ymd8 as _d8
from edipipe.core.envelope import TransactionSet
from edipipe.core.envelope import _at as _elem

# INS03 maintenance type codes.
MAINTENANCE_TYPE = {
    "001": "change",
    "021": "addition",
    "024": "termination",
    "025": "reinstatement",
    "030": "audit",
}
_ADD = {"021", "025"}
_TERM = {"024"}


@dataclass
class Coverage834:
    line_code: str | None = None  # HD03 insurance line (e.g. HLT, DEN, VIS)
    plan_description: str | None = None  # HD04
    begin: date | None = None  # DTP*348
    end: date | None = None  # DTP*349


@dataclass
class Member834:
    maintenance_type_code: str | None = None  # INS03
    maintenance_reason: str | None = None  # INS04
    benefit_status: str | None = None  # INS05
    subscriber_indicator: str | None = None  # INS01 (Y subscriber / N dependent)
    relationship: str | None = None  # INS02
    member_id: str | None = None  # REF*0F or NM109
    group_number: str | None = None  # REF*1L
    last_name: str | None = None  # NM103
    first_name: str | None = None  # NM104
    middle_name: str | None = None  # NM105
    dob: date | None = None  # DMG02
    gender: str | None = None  # DMG03
    eligibility_begin: date | None = None  # DTP*356
    eligibility_end: date | None = None  # DTP*357
    coverages: list[Coverage834] = field(default_factory=list)

    @property
    def maintenance(self) -> str | None:
        return MAINTENANCE_TYPE.get(self.maintenance_type_code or "")

    @property
    def is_add(self) -> bool:
        return self.maintenance_type_code in _ADD

    @property
    def is_term(self) -> bool:
        return self.maintenance_type_code in _TERM

    @property
    def is_change(self) -> bool:
        return self.maintenance_type_code == "001"


@dataclass
class Enrollment834:
    action_code: str | None = None  # BGN08 (2 change, 4 verify, RX replace, 00 original)
    reference: str | None = None  # BGN02
    file_date: date | None = None  # BGN04 or DTP*007
    sponsor_name: str | None = None  # N1*P5
    payer_name: str | None = None  # N1*IN
    members: list[Member834] = field(default_factory=list)

    @property
    def adds(self) -> list[Member834]:
        return [m for m in self.members if m.is_add]

    @property
    def terminations(self) -> list[Member834]:
        return [m for m in self.members if m.is_term]

    @property
    def changes(self) -> list[Member834]:
        return [m for m in self.members if m.is_change]


def read_834(ts: TransactionSet) -> Enrollment834:
    """Parse a single 834 transaction set body into an Enrollment834."""
    enr = Enrollment834()
    member: Member834 | None = None
    coverage: Coverage834 | None = None

    for seg in ts.segments:
        tag = seg[0]

        if tag == "INS":
            member = Member834(
                subscriber_indicator=_elem(seg, 1),
                relationship=_elem(seg, 2),
                maintenance_type_code=_elem(seg, 3),
                maintenance_reason=_elem(seg, 4),
                benefit_status=_elem(seg, 5),
            )
            coverage = None
            enr.members.append(member)

        elif member is None:
            # Header (before the first INS).
            if tag == "BGN":
                enr.reference = _elem(seg, 2)
                enr.file_date = _d8(_elem(seg, 4))
                enr.action_code = _elem(seg, 8)
            elif tag == "N1":
                role = _elem(seg, 1)
                if role == "P5":
                    enr.sponsor_name = _elem(seg, 2)
                elif role == "IN":
                    enr.payer_name = _elem(seg, 2)
            elif tag == "DTP" and _elem(seg, 1) == "007":
                enr.file_date = _d8(_elem(seg, 3)) or enr.file_date

        elif tag == "REF":
            qual = _elem(seg, 1)
            if qual == "0F":
                member.member_id = _elem(seg, 2)
            elif qual == "1L":
                member.group_number = _elem(seg, 2)

        elif tag == "NM1" and _elem(seg, 1) == "IL":
            member.last_name = _elem(seg, 3)
            member.first_name = _elem(seg, 4)
            member.middle_name = _elem(seg, 5)
            if _elem(seg, 8) and member.member_id is None:
                member.member_id = _elem(seg, 9)

        elif tag == "DMG":
            member.dob = _d8(_elem(seg, 2))
            member.gender = _elem(seg, 3)

        elif tag == "HD":
            coverage = Coverage834(
                line_code=_elem(seg, 3),
                plan_description=_elem(seg, 4),
            )
            member.coverages.append(coverage)

        elif tag == "DTP":
            qual = _elem(seg, 1)
            val = _d8(_elem(seg, 3))
            if qual == "356":
                member.eligibility_begin = val
            elif qual == "357":
                member.eligibility_end = val
            elif qual == "348" and coverage is not None:
                coverage.begin = val
            elif qual == "349" and coverage is not None:
                coverage.end = val

    return enr


def parse_834(raw: str) -> Enrollment834:
    """Parse a raw 834 interchange; concatenates members across transaction sets."""
    interchange = parse_envelope(raw)
    combined = Enrollment834()
    for ts in interchange.transaction_sets("834"):
        part = read_834(ts)
        # Header from the first transaction set wins.
        if combined.action_code is None:
            combined.action_code = part.action_code
            combined.reference = part.reference
            combined.file_date = part.file_date
            combined.sponsor_name = part.sponsor_name
            combined.payer_name = part.payer_name
        combined.members.extend(part.members)
    return combined
