"""X12 837I (005010X223A2) institutional encounter reader.

Parses the APR-DRG-relevant content of an institutional encounter so it can be
validated BEFORE submission to PRMMIS. Focus (per the ASES "Coding for APR-DRGs"
guide, top causes of denial / reduced payment):
- diagnoses with their Present-On-Admission (POA) indicator
- patient discharge status (drives the transfer-payment policy)
- bill type / frequency, admission type & source
- patient demographics (age from DOB, gender)
- procedures and total charge

Reader, not generator: First Medical already submits encounters; the platform's
role is validation/visibility. Envelope walking is done once by
`core.parse_envelope`; this consumes a TransactionSet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from edipipe.core import ParseError, parse_envelope
from edipipe.core.convert import dec as _dec
from edipipe.core.convert import ymd8 as _d8
from edipipe.core.envelope import TransactionSet
from edipipe.core.envelope import _at as _elem

PRINCIPAL_DX_QUALS = {"ABK", "BK"}
OTHER_DX_QUALS = {"ABF", "BF"}
ADMIT_DX_QUALS = {"ABJ", "BJ"}
PROCEDURE_QUALS = {"BBR", "BR", "APR", "BQ"}


@dataclass
class EncDiagnosis:
    kind: str  # "principal" | "other" | "admitting"
    code: str
    poa: str | None = None  # Y / N / U / W / 1 / None (missing)


@dataclass
class EncProcedure:
    code: str
    proc_date: date | None = None


@dataclass
class Encounter837I:
    patient_control_number: str
    facility_code: str | None = None  # CLM05-1 (e.g. "11" inpatient)
    frequency_code: str | None = None  # CLM05-3
    admission_type: str | None = None  # CL101
    admission_source: str | None = None  # CL102
    patient_status: str | None = None  # CL103 (discharge status)
    dob: date | None = None
    gender: str | None = None  # M / F / U
    statement_from: date | None = None
    statement_to: date | None = None
    total_charge: Decimal = Decimal("0")
    diagnoses: list[EncDiagnosis] = field(default_factory=list)
    procedures: list[EncProcedure] = field(default_factory=list)

    @property
    def principal_diagnosis(self) -> EncDiagnosis | None:
        for d in self.diagnoses:
            if d.kind == "principal":
                return d
        return None

    @property
    def other_diagnoses(self) -> list[EncDiagnosis]:
        return [d for d in self.diagnoses if d.kind == "other"]

    @property
    def diagnoses_missing_poa(self) -> list[EncDiagnosis]:
        return [d for d in self.diagnoses if d.kind in ("principal", "other") and not d.poa]

    @property
    def is_inpatient(self) -> bool:
        return self.facility_code == "11"


def _parse_hi(seg: list[str], comp: str, enc: Encounter837I) -> None:
    for i in range(1, len(seg)):
        raw = _elem(seg, i)
        if not raw:
            continue
        parts = raw.split(comp)
        qual = parts[0].strip() if parts else ""
        code = parts[1].strip() if len(parts) > 1 else ""
        if not code:
            continue
        if qual in PRINCIPAL_DX_QUALS or qual in OTHER_DX_QUALS or qual in ADMIT_DX_QUALS:
            poa = parts[8].strip() if len(parts) > 8 and parts[8].strip() else None
            kind = (
                "principal"
                if qual in PRINCIPAL_DX_QUALS
                else "admitting"
                if qual in ADMIT_DX_QUALS
                else "other"
            )
            enc.diagnoses.append(EncDiagnosis(kind=kind, code=code, poa=poa))
        elif qual in PROCEDURE_QUALS:
            pdate = _d8(parts[3].strip()) if len(parts) > 3 and parts[3].strip() else None
            enc.procedures.append(EncProcedure(code=code, proc_date=pdate))


def read_837i(ts: TransactionSet) -> list[Encounter837I]:
    """Parse the 837I transaction set body into encounters."""
    comp = ts.delims.component
    encounters: list[Encounter837I] = []
    enc: Encounter837I | None = None
    cur_dob: date | None = None
    cur_gender: str | None = None

    for seg in ts.segments:
        tag = seg[0]
        if tag == "DMG":
            cur_dob = _d8(_elem(seg, 2))
            cur_gender = _elem(seg, 3)
        elif tag == "CLM":
            pcn = _elem(seg, 1)
            if pcn is None:
                raise ParseError("CLM segment missing patient control number (CLM01)")
            facility_code = frequency = None
            comp5 = _elem(seg, 5)
            if comp5:
                p = comp5.split(comp)
                facility_code = p[0] if p and p[0] else None
                frequency = p[2] if len(p) > 2 and p[2] else None
            enc = Encounter837I(
                patient_control_number=pcn,
                facility_code=facility_code,
                frequency_code=frequency,
                total_charge=_dec(_elem(seg, 2)),
                dob=cur_dob,
                gender=cur_gender,
            )
            encounters.append(enc)
        elif enc is None:
            continue
        elif tag == "CL1":
            enc.admission_type = _elem(seg, 1)
            enc.admission_source = _elem(seg, 2)
            enc.patient_status = _elem(seg, 3)
        elif tag == "DTP":
            qual = _elem(seg, 1)
            fmt = _elem(seg, 2)
            val = _elem(seg, 3) or ""
            if qual == "434":
                if fmt == "RD8" and "-" in val:
                    lo, hi = val.split("-", 1)
                    enc.statement_from = _d8(lo)
                    enc.statement_to = _d8(hi)
                else:
                    enc.statement_from = _d8(val)
                    enc.statement_to = _d8(val)
        elif tag == "HI":
            _parse_hi(seg, comp, enc)

    return encounters


def parse_837i(raw: str) -> list[Encounter837I]:
    """Parse a raw 837I interchange into encounters."""
    interchange = parse_envelope(raw)
    txn_sets = interchange.transaction_sets("837")
    if not txn_sets:
        raise ParseError("Interchange contains no 837 transaction set")
    encounters: list[Encounter837I] = []
    for ts in txn_sets:
        encounters.extend(read_837i(ts))
    return encounters
