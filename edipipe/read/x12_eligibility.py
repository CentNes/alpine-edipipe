"""X12 270 / 271 (005010X279A1) eligibility inquiry & response reader.

The 270 is First Medical asking PRMMIS whether a member is eligible (and for
which benefits); the 271 is PRMMIS's answer — active/inactive coverage, benefit
lines, or a rejection (member not found). Both share the same 2000A source /
2000B receiver / 2000C subscriber / 2000D dependent hierarchy, so one reader
handles both, dispatched on the envelope's ST01 (like `ack.py` for 999/277CA).

Reader only (no-regret): envelope walking is done once by `core.parse_envelope`;
this consumes a TransactionSet. Generation/submission of 270s is gated on the
levantamiento (Fase 3) and intentionally not built here.

Key fields:
- 270: per-subscriber member id / name / DOB and the EQ service-type codes asked.
- 271: per-subscriber EB benefit lines (EB01 coverage status) and any AAA
  rejection reason codes (e.g. 75 = subscriber not found). TRN02 (2000C) is the
  trace that correlates a 271 back to its 270.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from edipipe.core import ParseError, parse_envelope
from edipipe.core.convert import ymd8 as _d8
from edipipe.core.envelope import TransactionSet
from edipipe.core.envelope import _at as _elem

# EB01 (coverage/benefit status) → rolled-up status.
_EB_ACTIVE = {"1", "2", "3", "4", "5"}  # active / active-capitated / pending investigation
_EB_INACTIVE = {"6", "7", "8"}  # inactive / inactive-pending

# AAA03 request-validation reject reasons (the ones PRMMIS actually returns).
AAA_REASONS = {
    "42": "Unable to respond at current time",
    "43": "Invalid/missing provider identification",
    "45": "Invalid/missing provider specialty",
    "47": "Invalid/missing provider state",
    "48": "Invalid/missing referring provider ID",
    "51": "Provider not on file",
    "56": "Inappropriate date",
    "57": "Invalid/missing date(s) of service",
    "58": "Invalid/missing date of birth",
    "60": "Date of birth follows date(s) of service",
    "61": "Date of death precedes date(s) of service",
    "62": "Date of service not within provider plan enrollment",
    "63": "Date of service in future",
    "71": "Patient birth date does not match that for the patient on the database",
    "72": "Invalid/missing subscriber/insured ID",
    "73": "Invalid/missing subscriber/insured name",
    "74": "Invalid/missing subscriber/insured gender code",
    "75": "Subscriber/insured not found",
    "76": "Duplicate subscriber/insured ID number",
    "77": "Subscriber found, patient not found",
    "78": "Subscriber/insured not in group/plan identified",
}


def _eb_status(code: str | None) -> str:
    if code in _EB_ACTIVE:
        return "active"
    if code in _EB_INACTIVE:
        return "inactive"
    return "info"


@dataclass
class BenefitInfo:
    """One 271 EB (eligibility/benefit information) line."""

    code: str | None = None  # EB01 coverage/benefit status code
    coverage_level: str | None = None  # EB02 (IND, FAM, ...)
    service_types: list[str] = field(default_factory=list)  # EB03 (may be a composite)
    insurance_type: str | None = None  # EB04 (MC Medicaid, HM HMO, ...)
    plan_description: str | None = None  # EB05
    status: str = "info"  # derived: active | inactive | info


@dataclass
class EligibilitySubject:
    """A subscriber (or dependent) within a 270/271."""

    entity: str = "subscriber"  # subscriber | dependent
    member_id: str | None = None  # NM109 or REF member id
    last: str | None = None
    first: str | None = None
    dob: date | None = None
    gender: str | None = None
    trace_number: str | None = None  # TRN02 (2000C) — correlates 271 ↔ 270
    inquiries: list[str] = field(default_factory=list)  # 270 EQ service-type codes
    benefits: list[BenefitInfo] = field(default_factory=list)  # 271 EB lines
    rejections: list[str] = field(default_factory=list)  # 271 AAA03 reason codes

    @property
    def is_active(self) -> bool:
        """271 only: any benefit line reports active coverage and nothing rejected."""
        return not self.rejections and any(b.status == "active" for b in self.benefits)

    @property
    def rejected(self) -> bool:
        return bool(self.rejections)


@dataclass
class EligibilityFile:
    transaction: str  # "270" | "271"
    own_interchange_control: str | None = None
    sender_id: str | None = None
    receiver_id: str | None = None
    source_name: str | None = None  # 2100A payer (PRMMIS/ASES)
    receiver_name: str | None = None  # 2100B information receiver (the MCO)
    subjects: list[EligibilitySubject] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # source/receiver-level AAA reasons

    @property
    def subject_count(self) -> int:
        return len(self.subjects)


# --------------------------------------------------------------------------
# Body reader (one TransactionSet)
# --------------------------------------------------------------------------

def read_eligibility(ts: TransactionSet) -> tuple[
    list[EligibilitySubject], str | None, str | None, list[str]
]:
    """Parse one 270/271 body → (subjects, source_name, receiver_name, file_errors)."""
    subjects: list[EligibilitySubject] = []
    subject: EligibilitySubject | None = None
    hl_level: str | None = None
    source_name: str | None = None
    receiver_name: str | None = None
    file_errors: list[str] = []
    comp = ts.delims.component

    for seg in ts.segments:
        tag = seg[0]

        if tag == "HL":
            hl_level = _elem(seg, 3)  # HL03 level: 20 source, 21 receiver, 22 subscriber, 23 dependent
            if hl_level in ("22", "23"):
                subject = EligibilitySubject(
                    entity="dependent" if hl_level == "23" else "subscriber"
                )
                subjects.append(subject)

        elif tag == "NM1":
            entity_id = _elem(seg, 1)
            if hl_level == "20":
                source_name = source_name or _elem(seg, 3)
            elif hl_level == "21":
                receiver_name = receiver_name or _elem(seg, 3)
            elif subject is not None and entity_id in ("IL", "03", "QC"):
                subject.last = _elem(seg, 3)
                subject.first = _elem(seg, 4)
                member_id = _elem(seg, 9)
                if member_id:
                    subject.member_id = member_id

        elif tag == "TRN" and subject is not None:
            subject.trace_number = _elem(seg, 2)

        elif tag == "REF" and subject is not None and not subject.member_id:
            # Member-id reference qualifiers (fallback when NM109 is absent).
            if _elem(seg, 1) in ("1L", "1W", "6P", "18", "HJ", "IG", "SY", "N6", "EJ", "Q4"):
                subject.member_id = _elem(seg, 2)

        elif tag == "DMG" and subject is not None:
            subject.dob = _d8(_elem(seg, 2))
            subject.gender = _elem(seg, 3)

        elif tag == "EQ" and subject is not None:  # 270 inquiry
            value = _elem(seg, 1) or ""
            for st in value.split(comp):
                st = st.strip()
                if st:
                    subject.inquiries.append(st)

        elif tag == "EB" and subject is not None:  # 271 benefit
            code = _elem(seg, 1)
            services = [s.strip() for s in (_elem(seg, 3) or "").split(comp) if s.strip()]
            subject.benefits.append(
                BenefitInfo(
                    code=code,
                    coverage_level=_elem(seg, 2),
                    service_types=services,
                    insurance_type=_elem(seg, 4),
                    plan_description=_elem(seg, 5),
                    status=_eb_status(code),
                )
            )

        elif tag == "AAA":  # request-validation rejection
            reason = _elem(seg, 3)
            if reason:
                if subject is not None:
                    subject.rejections.append(reason)
                else:
                    file_errors.append(reason)

    return subjects, source_name, receiver_name, file_errors


# --------------------------------------------------------------------------
# Convenience wrappers (raw interchange → EligibilityFile)
# --------------------------------------------------------------------------

def _parse(raw: str, transaction: str) -> EligibilityFile:
    interchange = parse_envelope(raw)
    txn_sets = interchange.transaction_sets(transaction)
    if not txn_sets:
        raise ParseError(f"Interchange contains no {transaction} transaction set")

    subjects: list[EligibilitySubject] = []
    source_name: str | None = None
    receiver_name: str | None = None
    errors: list[str] = []
    for ts in txn_sets:
        subs, src, rcv, errs = read_eligibility(ts)
        subjects.extend(subs)
        source_name = source_name or src
        receiver_name = receiver_name or rcv
        errors.extend(errs)

    return EligibilityFile(
        transaction=transaction,
        own_interchange_control=interchange.control,
        sender_id=interchange.sender_id,
        receiver_id=interchange.receiver_id,
        source_name=source_name,
        receiver_name=receiver_name,
        subjects=subjects,
        errors=errors,
    )


def parse_270(raw: str) -> EligibilityFile:
    """Parse a raw interchange into its 270 eligibility inquiry."""
    return _parse(raw, "270")


def parse_271(raw: str) -> EligibilityFile:
    """Parse a raw interchange into its 271 eligibility response."""
    return _parse(raw, "271")


def parse_eligibility(raw: str) -> EligibilityFile:
    """Dispatch on ST01: 270 → inquiry, 271 → response."""
    interchange = parse_envelope(raw)
    codes = {ts.code for ts in interchange.transaction_sets()}
    if "271" in codes:
        return parse_271(raw)
    if "270" in codes:
        return parse_270(raw)
    raise ParseError("Interchange is neither a 270 nor a 271 eligibility transaction")
