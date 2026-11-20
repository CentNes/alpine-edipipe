"""X12 837 claim reader (837P 005010X222A1 / 837I 005010X223A2) — payer side.

The `x12_837i` reader extracts encounter-validation fields (dx/POA, discharge
status). This one reads what a payer needs to ADJUDICATE: subscriber, billing /
rendering / referring providers, claim header (CLM, dates, CL1, REF*F8) and every
service line (SV1 professional / SV2 institutional with DTP*472).

Round-trip contract: parse_837(generate_x12(claims, ...)) reproduces the claims'
member id, providers, diagnoses, charges and service lines. Billing-provider NM1*85
is honored both in 2010AA (before CLM, X12-standard) and after CLM (the shared
writer's layout); in the latter case it attaches to the open claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from edipipe.core import ParseError, parse_envelope
from edipipe.core.convert import dec as _dec
from edipipe.core.convert import ymd8 as _d8
from edipipe.core.envelope import TransactionSet, _at as _elem


@dataclass
class ClaimLine837:
    line_number: int
    procedure_code: str | None = None  # SV1-1-2 / SV2-2-2 (CPT/HCPCS)
    modifiers: list[str] = field(default_factory=list)
    revenue_code: str | None = None  # SV2-1 (837I)
    charge: Decimal = Decimal("0")
    units: Decimal = Decimal("1")
    place_of_service: str | None = None  # SV1-5
    diagnosis_pointers: list[str] = field(default_factory=list)  # SV1-7
    rendering_npi: str | None = None  # NM1*82 in 2420A (overrides the claim's)
    service_date: date | None = None  # DTP*472
    service_date_to: date | None = None


@dataclass
class Claim837:
    claim_type: str  # "837P" | "837I"
    patient_control_number: str  # CLM01
    total_charge: Decimal = Decimal("0")  # CLM02
    facility_code: str | None = None  # CLM05-1 (POS for 837P, bill-type facility for 837I)
    frequency_code: str | None = None  # CLM05-3 (1 original, 7 replacement, 8 void)
    original_claim_number: str | None = None  # REF*F8
    member_id: str | None = None  # NM1*IL NM109 (subscriber, 2010BA)
    member_last: str | None = None
    member_first: str | None = None
    member_dob: date | None = None
    member_gender: str | None = None
    patient_last: str | None = None  # NM1*QC (dependent patient, 2010CA); None when patient = subscriber
    patient_first: str | None = None
    patient_dob: date | None = None
    patient_gender: str | None = None
    payer_name: str | None = None
    payer_id: str | None = None
    billing_npi: str | None = None
    billing_name: str | None = None
    billing_tax_id: str | None = None
    attending_npi: str | None = None  # NM1*71
    rendering_npi: str | None = None  # NM1*82 (claim level, 2310B)
    referring_npi: str | None = None  # NM1*DN
    facility_npi: str | None = None  # NM1*77
    statement_from: date | None = None  # DTP*434 / 431
    statement_to: date | None = None
    admission_date: date | None = None  # DTP*435
    admission_type: str | None = None  # CL101
    admission_source: str | None = None  # CL102
    patient_status: str | None = None  # CL103
    diagnoses: list[str] = field(default_factory=list)  # HI ABK/ABF (principal first)
    procedures: list[str] = field(default_factory=list)  # HI BBR/BBQ (ICD-10-PCS)
    lines: list[ClaimLine837] = field(default_factory=list)

    @property
    def service_from(self) -> date | None:
        dates = [ln.service_date for ln in self.lines if ln.service_date]
        return min(dates) if dates else self.statement_from


def _range(qual: str | None, value: str | None) -> tuple[date | None, date | None]:
    if not value:
        return None, None
    if qual == "RD8" and "-" in value:
        a, b = value.split("-", 1)
        return _d8(a), _d8(b)
    d = _d8(value)
    return d, d


def read_837(ts: TransactionSet, claim_type: str) -> list[Claim837]:
    """Parse one 837 transaction set body into its claims."""
    comp = ts.delims.component
    claims: list[Claim837] = []
    claim: Claim837 | None = None
    line: ClaimLine837 | None = None
    sub: dict[str, object] = {}
    patient: dict[str, object] = {}
    billing: dict[str, str | None] = {}
    level: str | None = None

    for seg in ts.segments:
        tag = seg[0]
        if tag == "HL":
            claim, line = None, None
            level = _elem(seg, 3)
            if level == "20":
                billing = {}
            elif level == "22":
                sub, patient = {}, {}
            elif level == "23":
                patient = {}
        elif tag == "NM1":
            q = _elem(seg, 1)
            ident = _elem(seg, 9)
            if q == "IL":
                sub.update(member_id=ident, last=_elem(seg, 3), first=_elem(seg, 4))
            elif q == "QC":
                patient.update(last=_elem(seg, 3), first=_elem(seg, 4))
            elif q == "PR":
                sub.update(payer_name=_elem(seg, 3), payer_id=ident)
            elif q == "85":
                if claim is not None:
                    claim.billing_npi, claim.billing_name = ident, _elem(seg, 3)
                else:
                    billing = {"npi": ident, "name": _elem(seg, 3)}
            elif claim is not None and q == "82":
                if line is not None:
                    line.rendering_npi = ident
                else:
                    claim.rendering_npi = ident
            elif claim is not None and q == "71":
                claim.attending_npi = ident
            elif claim is not None and q == "DN":
                claim.referring_npi = ident
            elif claim is not None and q == "77":
                claim.facility_npi = ident
        elif tag == "DMG" and claim is None:
            target = patient if level == "23" else sub
            target.update(dob=_d8(_elem(seg, 2)), gender=_elem(seg, 3))
        elif tag == "REF":
            q, v = _elem(seg, 1), _elem(seg, 2)
            if q == "EI":
                if claim is not None:
                    claim.billing_tax_id = v
                else:
                    billing["tax_id"] = v
            elif q == "F8" and claim is not None:
                claim.original_claim_number = v
        elif tag == "CLM":
            pcn = _elem(seg, 1)
            if pcn is None:
                raise ParseError("CLM segment missing patient control number")
            parts = (_elem(seg, 5) or "").split(comp)
            claim = Claim837(
                claim_type=claim_type,
                patient_control_number=pcn,
                total_charge=_dec(_elem(seg, 2)),
                facility_code=parts[0] or None,
                frequency_code=parts[2] if len(parts) > 2 and parts[2] else None,
                member_id=sub.get("member_id"),  # type: ignore[arg-type]
                member_last=sub.get("last"),  # type: ignore[arg-type]
                member_first=sub.get("first"),  # type: ignore[arg-type]
                member_dob=sub.get("dob"),  # type: ignore[arg-type]
                member_gender=sub.get("gender"),  # type: ignore[arg-type]
                patient_last=patient.get("last"),  # type: ignore[arg-type]
                patient_first=patient.get("first"),  # type: ignore[arg-type]
                patient_dob=patient.get("dob"),  # type: ignore[arg-type]
                patient_gender=patient.get("gender"),  # type: ignore[arg-type]
                payer_name=sub.get("payer_name"),  # type: ignore[arg-type]
                payer_id=sub.get("payer_id"),  # type: ignore[arg-type]
                billing_npi=billing.get("npi"),
                billing_name=billing.get("name"),
                billing_tax_id=billing.get("tax_id"),
            )
            claims.append(claim)
            line = None
        elif tag == "DTP" and claim is not None:
            q = _elem(seg, 1)
            start, end = _range(_elem(seg, 2), _elem(seg, 3))
            if q == "472" and line is not None:
                line.service_date, line.service_date_to = start, end
            elif q in ("434", "431"):
                claim.statement_from, claim.statement_to = start, end
            elif q == "435":
                claim.admission_date = start
        elif tag == "CL1" and claim is not None:
            claim.admission_type = _elem(seg, 1)
            claim.admission_source = _elem(seg, 2)
            claim.patient_status = _elem(seg, 3)
        elif tag == "HI" and claim is not None:
            for raw in seg[1:]:
                parts = raw.split(comp)
                if len(parts) < 2 or not parts[1]:
                    continue
                if parts[0] in ("ABK", "BK"):
                    claim.diagnoses.insert(0, parts[1])
                elif parts[0] in ("ABF", "BF"):
                    claim.diagnoses.append(parts[1])
                elif parts[0] in ("BBR", "BBQ", "BR", "BQ"):
                    claim.procedures.append(parts[1])
        elif tag == "LX" and claim is not None:
            line = None
        elif tag in ("SV1", "SV2") and claim is not None:
            line = ClaimLine837(line_number=len(claim.lines) + 1)
            if tag == "SV1":
                proc = (_elem(seg, 1) or "").split(comp)
                line.procedure_code = proc[1] if len(proc) > 1 else proc[0] or None
                line.modifiers = [m for m in proc[2:6] if m]
                line.charge = _dec(_elem(seg, 2))
                line.units = _dec(_elem(seg, 4)) if _elem(seg, 4) else Decimal("1")
                line.place_of_service = _elem(seg, 5) or claim.facility_code
                line.diagnosis_pointers = [p for p in (_elem(seg, 7) or "").split(comp) if p]
            else:
                line.revenue_code = _elem(seg, 1)
                proc = (_elem(seg, 2) or "").split(comp)
                code = proc[1] if len(proc) > 1 and proc[0] in ("HC", "HP") else proc[0]
                line.procedure_code = code or None
                line.modifiers = [m for m in proc[2:6] if m] if len(proc) > 1 and proc[0] in ("HC", "HP") else [m for m in proc[1:5] if m]
                line.charge = _dec(_elem(seg, 3))
                line.units = _dec(_elem(seg, 5)) if _elem(seg, 5) else Decimal("1")
            claim.lines.append(line)
    return claims


def parse_837(raw: str) -> list[Claim837]:
    """Parse a raw 837P/837I interchange into claims (type from GS08 version)."""
    interchange = parse_envelope(raw)
    claims: list[Claim837] = []
    found = False
    for group in interchange.groups:
        claim_type = "837I" if (group.version or "").startswith("005010X223") else "837P"
        for ts in group.transactions:
            if ts.code != "837":
                continue
            found = True
            claims.extend(read_837(ts, claim_type))
    if not found:
        raise ParseError("Interchange contains no 837 transaction set")
    return claims
