"""X12 837I/837P EDI generator — the shared kernel's X12 writer.

Generates 005010X223A2 (837I institutional) and 005010X222A1 (837P professional)
transaction sets from structured claim data.

Claims with non-empty errors NEVER generate X12.

--- Provenance ---
Lifted verbatim from digitalizacion's `claimspipe.x12gen` (sub-project A, kernel
unification, 2026-07-24) so both apps share one generator. Kept behavior-identical
on purpose: digitalizacion imports this and deletes its local copy, yielding
byte-identical output. The envelope layer (_build_isa/_build_gs/_build_st + the SE/
GE/IEA tail) can later be routed through `edipipe.core.build.build_interchange`;
deferred to keep this lift behavior-preserving.

KNOWN NON-CONFORMANCE (tracked, deliberately preserved — do NOT "fix" here):
_build_gs emits GS01="HP" for 837I. Per X12 005010, GS01 for every 837 is "HC"
("HP" is the 835 functional-ID code). Preserved as-is pending confirmation of what
First Medical's accepted PRMMIS submission actually sends; see the round-trip test
that locks in this quirk. Fix is its own change, not part of this consolidation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)

ELEMENT_SEP = "*"
SEGMENT_TERM = "~"
COMPONENT_SEP = ":"
REPETITION_SEP = "^"


@dataclass
class X12Diagnosis:
    sequence: int
    qualifier: str
    icd_code: str
    poa: str | None = None   # Present-on-Admission (component 9 of the HI composite, 837I)


@dataclass
class X12Procedure:
    sequence: int
    icd_code: str            # ICD-10-PCS
    qualifier: str = "BBQ"   # BBR principal, BBQ other
    procedure_date: str | date | None = None


@dataclass
class X12Code:
    """UB-04 condition/occurrence/value code for the 837I HI segments."""
    code_type: str           # "condition" | "occurrence" | "value"
    code: str
    sequence: int = 1
    code_date: str | date | None = None   # occurrence
    amount: float | None = None           # value


@dataclass
class X12ServiceLine:
    line_number: int
    revenue_code: str | None = None
    hcpcs_code: str | None = None
    cpt_code: str | None = None
    modifiers: list[str] | None = None
    service_date: date | None = None
    service_date_to: date | None = None
    units: float | None = None
    total_charges: float | None = None
    non_covered_charges: float | None = None
    place_of_service: str | None = None
    diagnosis_pointers: list[str] | None = None


@dataclass
class X12ClaimData:
    """All data needed to render one CLM loop."""
    claim_id: str
    doc_type: str
    patient_control_number: str
    total_charges: float
    place_of_service: str | None = None
    frequency_code: str = "1"
    type_of_bill: str | None = None
    # Payer claim control number (ICN/DCN) of the claim being replaced/voided —
    # emitted as REF*F8 in loop 2300 when frequency_code is 7 (replacement) or 8
    # (void). Required by payers to match a corrected claim to the original.
    original_claim_control_number: str | None = None

    # Subscriber / patient
    subscriber_id: str = ""
    subscriber_last: str = ""
    subscriber_first: str = ""
    patient_last: str = ""
    patient_first: str = ""
    patient_dob: str = ""
    patient_sex: str = ""
    patient_address: str = ""
    patient_city: str = ""
    patient_state: str = ""
    patient_zip: str = ""
    patient_relationship: str = "18"

    # Payer
    payer_name: str = ""
    payer_id: str = ""

    # Billing provider
    billing_provider_name: str = ""
    billing_npi: str = ""
    billing_tax_id: str = ""
    billing_address: str = ""
    billing_city: str = ""
    billing_state: str = ""
    billing_zip: str = ""

    # Attending (837I)
    attending_npi: str | None = None
    attending_last: str | None = None
    attending_first: str | None = None

    # Referring (837P)
    referring_npi: str | None = None
    referring_name: str | None = None

    # Service facility (837P)
    service_facility_name: str | None = None
    service_facility_npi: str | None = None

    # Dates
    statement_from: str | None = None
    statement_to: str | None = None
    admission_date: str | None = None

    # Institutional claim info (837I CL1) — APR-DRG inputs
    admission_type: str | None = None      # UB-04 FL14
    admission_source: str | None = None    # UB-04 FL15
    patient_status: str | None = None      # UB-04 FL17 (discharge status)

    diagnoses: list[X12Diagnosis] = field(default_factory=list)
    procedures: list[X12Procedure] = field(default_factory=list)
    codes: list[X12Code] = field(default_factory=list)
    service_lines: list[X12ServiceLine] = field(default_factory=list)


@dataclass
class X12ControlNumbers:
    isa_control: str
    gs_control: str
    st_control: str


@dataclass
class X12GenerationResult:
    content: str
    control: X12ControlNumbers
    claim_count: int
    total_charges: float
    x12_type: str


def _seg(*elements: str) -> str:
    stripped = ELEMENT_SEP.join(elements)
    return stripped + SEGMENT_TERM


def _pad(value: str | int, length: int) -> str:
    return str(value).rjust(length, "0")


def _fmt_date(d: str | date | None, fmt: str = "%Y%m%d") -> str:
    if d is None:
        return ""
    if isinstance(d, date):
        return d.strftime(fmt)
    cleaned = d.replace("/", "").replace("-", "")
    if len(cleaned) == 8:
        return cleaned
    return d


def _fmt_money(amount: float | None) -> str:
    if amount is None:
        return "0"
    return f"{amount:.2f}"


def _build_isa(
    sender_id: str,
    receiver_id: str,
    control_number: str,
    is_production: bool = False,
) -> str:
    now = datetime.now()
    date_str = now.strftime("%y%m%d")
    time_str = now.strftime("%H%M")
    usage = "P" if is_production else "T"
    return _seg(
        "ISA",
        "00", " " * 10,
        "00", " " * 10,
        "ZZ", sender_id.ljust(15),
        "ZZ", receiver_id.ljust(15),
        date_str, time_str,
        REPETITION_SEP,
        "00501",
        _pad(control_number, 9),
        "0",
        usage,
        COMPONENT_SEP,
    )


def _build_gs(
    sender_code: str,
    receiver_code: str,
    control_number: str,
    x12_type: str,
) -> str:
    now = datetime.now()
    # GS01 for every 837 (I/P/D) is "HC" per X12 005010; "HP" is the 835 code.
    func_id = "HC"
    version = "005010X223A2" if x12_type == "837I" else "005010X222A1"
    return _seg(
        "GS",
        func_id,
        sender_code,
        receiver_code,
        now.strftime("%Y%m%d"),
        now.strftime("%H%M"),
        control_number,
        "X",
        version,
    )


def _build_st(control_number: str, x12_type: str) -> str:
    version = "005010X223A2" if x12_type == "837I" else "005010X222A1"
    return _seg("ST", "837", _pad(control_number, 4), version)


def _build_bht(x12_type: str) -> str:
    now = datetime.now()
    purpose = "00"
    return _seg(
        "BHT",
        "0019",
        purpose,
        now.strftime("%Y%m%d%H%M%S")[:14],
        now.strftime("%Y%m%d"),
        now.strftime("%H%M"),
        "CH",
    )


def _build_submitter_loop(name: str, npi: str) -> list[str]:
    segments: list[str] = []
    segments.append(_seg("HL", "1", "", "20", "1"))
    segments.append(_seg("NM1", "41", "2", name, "", "", "", "", "46", npi))
    segments.append(_seg("PER", "IC", name, "TE", "0000000000"))
    return segments


def _build_subscriber_loop(
    claim: X12ClaimData,
    hl_count: int,
    parent_hl: int,
) -> list[str]:
    segments: list[str] = []
    is_patient_subscriber = claim.patient_relationship == "18"
    child_flag = "0" if is_patient_subscriber else "1"
    segments.append(_seg("HL", str(hl_count), str(parent_hl), "22", child_flag))
    segments.append(_seg(
        "SBR", "P", claim.patient_relationship,
        claim.payer_id or "", "", "", "", "", "", "",
    ))
    segments.append(_seg(
        "NM1", "IL", "1",
        claim.subscriber_last or claim.patient_last,
        claim.subscriber_first or claim.patient_first,
        "", "", "",
        "MI",
        claim.subscriber_id,
    ))
    segments.append(_seg(
        "N3",
        claim.patient_address or "",
    ))
    segments.append(_seg(
        "N4",
        claim.patient_city or "",
        claim.patient_state or "",
        claim.patient_zip or "",
    ))
    segments.append(_seg("DMG", "D8", claim.patient_dob or "", claim.patient_sex or ""))
    segments.append(_seg(
        "NM1", "PR", "2", claim.payer_name,
        "", "", "", "", "PI", claim.payer_id or "",
    ))
    return segments


def _ref_original_claim(claim: X12ClaimData) -> list[str]:
    """REF*F8 (loop 2300) — original payer claim control number, emitted only on
    a replacement (freq 7) or void (freq 8) so the payer can match the correction
    to the claim being replaced."""
    if claim.frequency_code in ("7", "8") and claim.original_claim_control_number:
        return [_seg("REF", "F8", claim.original_claim_control_number)]
    return []


def _build_claim_loop_837i(claim: X12ClaimData) -> list[str]:
    segments: list[str] = []
    facility_code = (claim.type_of_bill or "0111")[:1] if claim.type_of_bill else "1"
    freq = claim.frequency_code or "1"
    segments.append(_seg(
        "CLM",
        claim.patient_control_number,
        _fmt_money(claim.total_charges),
        "",
        "",
        f"{facility_code}{COMPONENT_SEP}B{COMPONENT_SEP}{freq}",
        "Y",
        "A",
        "Y",
        "I",
    ))

    if claim.statement_from:
        dt_from = _fmt_date(claim.statement_from)
        dt_to = _fmt_date(claim.statement_to or claim.statement_from)
        segments.append(_seg("DTP", "434", "RD8", f"{dt_from}-{dt_to}"))
    if claim.admission_date:
        segments.append(_seg("DTP", "435", "D8", _fmt_date(claim.admission_date)))

    # CL1 — admission type/source + patient (discharge) status (APR-DRG inputs).
    if claim.admission_type or claim.admission_source or claim.patient_status:
        segments.append(_seg(
            "CL1",
            claim.admission_type or "",
            claim.admission_source or "",
            claim.patient_status or "",
        ))

    segments.extend(_ref_original_claim(claim))
    segments.extend(_build_diagnoses(claim.diagnoses))
    segments.extend(_build_procedures(claim.procedures))
    segments.extend(_build_codes(claim.codes))

    segments.append(_seg(
        "NM1", "85", "2",
        claim.billing_provider_name, "", "", "", "",
        "XX", claim.billing_npi,
    ))
    segments.append(_seg("N3", claim.billing_address or ""))
    segments.append(_seg(
        "N4", claim.billing_city or "",
        claim.billing_state or "", claim.billing_zip or "",
    ))
    segments.append(_seg("REF", "EI", claim.billing_tax_id or ""))

    if claim.attending_npi:
        segments.append(_seg(
            "NM1", "71", "1",
            claim.attending_last or "",
            claim.attending_first or "",
            "", "", "",
            "XX", claim.attending_npi,
        ))

    for sl in claim.service_lines:
        segments.extend(_build_sv2(sl))

    return segments


def _build_claim_loop_837p(claim: X12ClaimData) -> list[str]:
    segments: list[str] = []
    pos = claim.place_of_service or "11"
    freq = claim.frequency_code or "1"
    segments.append(_seg(
        "CLM",
        claim.patient_control_number,
        _fmt_money(claim.total_charges),
        "",
        "",
        f"{pos}{COMPONENT_SEP}B{COMPONENT_SEP}{freq}",
        "Y",
        "A",
        "Y",
        "I",
    ))

    if claim.statement_from:
        segments.append(_seg("DTP", "431", "D8", _fmt_date(claim.statement_from)))

    segments.extend(_ref_original_claim(claim))
    segments.extend(_build_diagnoses(claim.diagnoses))

    segments.append(_seg(
        "NM1", "85", "2",
        claim.billing_provider_name, "", "", "", "",
        "XX", claim.billing_npi,
    ))
    segments.append(_seg("N3", claim.billing_address or ""))
    segments.append(_seg(
        "N4", claim.billing_city or "",
        claim.billing_state or "", claim.billing_zip or "",
    ))
    segments.append(_seg("REF", "EI", claim.billing_tax_id or ""))

    if claim.referring_npi:
        segments.append(_seg(
            "NM1", "DN", "1",
            claim.referring_name or "",
            "", "", "", "",
            "XX", claim.referring_npi,
        ))

    if claim.service_facility_npi:
        segments.append(_seg(
            "NM1", "77", "2",
            claim.service_facility_name or "",
            "", "", "", "",
            "XX", claim.service_facility_npi,
        ))

    for sl in claim.service_lines:
        segments.extend(_build_sv1(sl))

    return segments


def _build_diagnoses(diagnoses: list[X12Diagnosis]) -> list[str]:
    if not diagnoses:
        return []
    segments: list[str] = []
    principal = [d for d in diagnoses if d.sequence == 1]
    others = [d for d in diagnoses if d.sequence != 1]

    if principal:
        dx = principal[0]
        qualifier = "ABK" if dx.qualifier == "ABK" else "ABF"
        elements = ["HI", _dx_composite(qualifier, dx.icd_code, dx.poa)]
        for other in others[:11]:
            q = "ABF" if other.qualifier != "ABK" else "ABK"
            elements.append(_dx_composite(q, other.icd_code, other.poa))
        segments.append(_seg(*elements))

    return segments


def _dx_composite(qualifier: str, code: str, poa: str | None) -> str:
    """HI diagnosis composite. In the 837I, the Present-on-Admission indicator
    is component 9 of the principal/other diagnosis composite (positions 3-8
    are unused), i.e. `ABK:code:::::::Y`."""
    comp = f"{qualifier}{COMPONENT_SEP}{code}"
    if poa and qualifier in ("ABK", "ABF"):
        comp += COMPONENT_SEP * 7 + poa
    return comp


def _build_procedures(procedures: list[X12Procedure]) -> list[str]:
    """HI segment for inpatient ICD-10-PCS procedures (837I). Principal is BBR,
    others BBQ; each composite carries the procedure date with a D8 qualifier."""
    if not procedures:
        return []
    elements = ["HI"]
    for p in sorted(procedures, key=lambda x: x.sequence)[:12]:
        comp = f"{p.qualifier}{COMPONENT_SEP}{p.icd_code}"
        if p.procedure_date:
            comp += f"{COMPONENT_SEP}D8{COMPONENT_SEP}{_fmt_date(p.procedure_date)}"
        elements.append(comp)
    return [_seg(*elements)]


# Value codes 80/81 carry covered/non-covered DAY counts; the 837I represents
# those as QTY*CA / QTY*NA rather than a value-amount HI, so they're routed there.
_COVERED_DAYS_VC = "80"
_NONCOVERED_DAYS_VC = "81"


def _build_codes(codes: list[X12Code]) -> list[str]:
    """HI segments for UB-04 condition (BG), occurrence (BH+date) and value
    (BE+amount) codes, plus QTY*CA / QTY*NA for covered/non-covered days (value
    codes 80/81). One HI segment per code type; blank when none of that type."""
    segments: list[str] = []

    def _by(kind: str) -> list[X12Code]:
        return sorted(
            (c for c in codes if c.code_type == kind), key=lambda c: c.sequence
        )

    occurrence = _by("occurrence")
    if occurrence:
        els = ["HI"]
        for c in occurrence[:12]:
            comp = f"BH{COMPONENT_SEP}{c.code}"
            if c.code_date:
                comp += f"{COMPONENT_SEP}D8{COMPONENT_SEP}{_fmt_date(c.code_date)}"
            els.append(comp)
        segments.append(_seg(*els))

    # Value amounts (excluding day-count value codes 80/81, emitted as QTY below).
    value = _by("value")
    amount_vcs = [
        c for c in value if c.code not in (_COVERED_DAYS_VC, _NONCOVERED_DAYS_VC)
    ]
    if amount_vcs:
        els = ["HI"]
        for c in amount_vcs[:12]:
            amt = _fmt_money(c.amount) if c.amount is not None else ""
            els.append(f"BE{COMPONENT_SEP}{c.code}{COMPONENT_SEP}{COMPONENT_SEP}{COMPONENT_SEP}{amt}")
        segments.append(_seg(*els))

    condition = _by("condition")
    if condition:
        els = ["HI"]
        for c in condition[:24]:
            els.append(f"BG{COMPONENT_SEP}{c.code}")
        segments.append(_seg(*els))

    # Covered / non-covered days → QTY*CA / QTY*NA (from value codes 80/81).
    for c in value:
        if c.code == _COVERED_DAYS_VC and c.amount is not None:
            segments.append(_seg("QTY", "CA", str(int(c.amount))))
        elif c.code == _NONCOVERED_DAYS_VC and c.amount is not None:
            segments.append(_seg("QTY", "NA", str(int(c.amount))))

    return segments


def _build_sv2(sl: X12ServiceLine) -> list[str]:
    segments: list[str] = []
    hcpcs_composite = sl.hcpcs_code or ""
    if sl.modifiers:
        hcpcs_composite += COMPONENT_SEP + COMPONENT_SEP.join(sl.modifiers[:4])
    segments.append(_seg(
        "SV2",
        sl.revenue_code or "",
        hcpcs_composite,
        _fmt_money(sl.total_charges),
        "UN",
        str(sl.units or 1),
    ))
    if sl.service_date:
        segments.append(_seg("DTP", "472", "D8", _fmt_date(sl.service_date)))
    return segments


def _build_sv1(sl: X12ServiceLine) -> list[str]:
    segments: list[str] = []
    proc_code = sl.cpt_code or sl.hcpcs_code or ""
    if sl.modifiers:
        proc_code += COMPONENT_SEP + COMPONENT_SEP.join(sl.modifiers[:4])
    proc_composite = f"HC{COMPONENT_SEP}{proc_code}"
    diag_ptrs = ""
    if sl.diagnosis_pointers:
        diag_ptrs = COMPONENT_SEP.join(sl.diagnosis_pointers[:4])
    segments.append(_seg(
        "SV1",
        proc_composite,
        _fmt_money(sl.total_charges),
        "UN",
        str(sl.units or 1),
        sl.place_of_service or "",
        "",
        diag_ptrs,
    ))
    if sl.service_date:
        dt_from = _fmt_date(sl.service_date)
        dt_to = _fmt_date(sl.service_date_to) if sl.service_date_to else dt_from
        if dt_from == dt_to:
            segments.append(_seg("DTP", "472", "D8", dt_from))
        else:
            segments.append(_seg("DTP", "472", "RD8", f"{dt_from}-{dt_to}"))
    return segments


def generate_x12(
    claims: list[X12ClaimData],
    control: X12ControlNumbers,
    sender_id: str,
    receiver_id: str,
    x12_type: str,
    is_production: bool = False,
    payer_edits: dict[str, Any] | None = None,
) -> X12GenerationResult:
    """Generate a complete X12 837 interchange from claim data.

    This is the ONLY function that produces X12 segments.
    Claims with non-empty errors must be filtered BEFORE calling this.
    """
    if not claims:
        raise ValueError("No claims to generate")

    if x12_type not in ("837I", "837P"):
        raise ValueError(f"Unsupported x12_type: {x12_type}")

    edits = payer_edits or {}
    segments: list[str] = []

    segments.append(_build_isa(sender_id, receiver_id, control.isa_control, is_production))
    segments.append(_build_gs(sender_id, receiver_id, control.gs_control, x12_type))
    segments.append(_build_st(control.st_control, x12_type))
    segments.append(_build_bht(x12_type))

    submitter_name = edits.get("submitter_name", sender_id)
    submitter_id = edits.get("submitter_id", sender_id)
    segments.extend(_build_submitter_loop(submitter_name, submitter_id))

    hl_count = 2
    total_charges = 0.0
    for claim in claims:
        segments.extend(_build_subscriber_loop(claim, hl_count, 1))
        hl_count += 1

        if x12_type == "837I":
            segments.extend(_build_claim_loop_837i(claim))
        else:
            segments.extend(_build_claim_loop_837p(claim))

        total_charges += claim.total_charges or 0

    se_count = len([
        s for s in segments
        if not s.startswith("ISA") and not s.startswith("GS")
    ]) + 1
    segments.append(_seg("SE", str(se_count), _pad(control.st_control, 4)))
    segments.append(_seg("GE", "1", control.gs_control))
    segments.append(_seg("IEA", "1", _pad(control.isa_control, 9)))

    content = "\n".join(segments)

    return X12GenerationResult(
        content=content,
        control=control,
        claim_count=len(claims),
        total_charges=total_charges,
        x12_type=x12_type,
    )
