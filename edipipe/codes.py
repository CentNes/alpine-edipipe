"""Code dictionaries for X12 interpretation.

Descriptions are the official English texts (abbreviated where long). These
are reference data, not UI strings — the UI layer translates labels, while
code descriptions are displayed as published by X12/WPC (CAQH CORE 360 rule
requires uniform use of the published CARC/RARC meanings).
"""

# CLP02 — Claim Status Codes (835 TR3, 005010X221A1)
CLAIM_STATUS_CODES: dict[str, str] = {
    "1": "Processed as Primary",
    "2": "Processed as Secondary",
    "3": "Processed as Tertiary",
    "4": "Denied",
    "19": "Processed as Primary, Forwarded to Additional Payer(s)",
    "20": "Processed as Secondary, Forwarded to Additional Payer(s)",
    "21": "Processed as Tertiary, Forwarded to Additional Payer(s)",
    "22": "Reversal of Previous Payment",
    "23": "Not Our Claim, Forwarded to Additional Payer(s)",
    "25": "Predetermination Pricing Only - No Payment",
}

DENIED_STATUS_CODES = {"4"}

# Claim Adjustment Reason Codes (CARC) — common subset
CARC: dict[str, str] = {
    "1": "Deductible amount",
    "2": "Coinsurance amount",
    "3": "Co-payment amount",
    "16": "Claim/service lacks information or has submission/billing error(s)",
    "18": "Exact duplicate claim/service",
    "22": "This care may be covered by another payer per coordination of benefits",
    "23": "Impact of prior payer(s) adjudication",
    "29": "The time limit for filing has expired",
    "45": "Charge exceeds fee schedule/maximum allowable",
    "50": "Non-covered: not deemed a medical necessity by the payer",
    "96": "Non-covered charge(s)",
    "97": "Benefit for this service is included in another service already adjudicated",
    "109": "Claim/service not covered by this payer/contractor",
    "119": "Benefit maximum for this time period or occurrence has been reached",
    "151": "Payer deems the information submitted does not support this many/frequency of services",
    "181": "Procedure code was invalid on the date of service",
    "197": "Precertification/authorization/notification/pre-treatment absent",
    "204": "Service/equipment/drug is not covered under the patient's current benefit plan",
    "252": "An attachment/other documentation is required to adjudicate this claim/service",
    "B7": "Provider was not certified/eligible to be paid for this procedure/service on this date of service",
    "B15": "Service/procedure requires a qualifying service/procedure be received and covered",
    "CO45": "Charge exceeds fee schedule (contractual obligation)",
    # DRG / inpatient PPS adjustments — relevant since the ASES APR-DRG go-live
    # (2025-10-01). These are the published X12 CARCs tied to the DRG concepts in
    # the ASES MCO APR-DRG Readiness Attestation (outlier payments, medical
    # education add-ons, non-covered days). The authoritative ASES-specific DRG
    # code set lives in the PRMMIS 835 companion guide (scanned — pending OCR);
    # expand this block once confirmed. Descriptions here are the published X12
    # texts — do not invent codes.
    "69": "Day outlier amount",
    "70": "Cost outlier - Adjustment to compensate for additional costs",
    "74": "Indirect Medical Education Adjustment",
    "75": "Direct Medical Education Adjustment",
    "78": "Non-Covered days/Room charge adjustment",
}

# Subset of CARC codes carried in the MIA (Medicare/Medicaid Inpatient
# Adjudication) loop of an inpatient 835 — used to flag DRG-related lines in
# reporting. All are members of CARC above.
DRG_INPATIENT_CARC: set[str] = {"69", "70", "74", "75", "78"}

# Remittance Advice Remark Codes (RARC) — common subset (incl. MIA/MOA usage)
RARC: dict[str, str] = {
    "M15": "Separately billed services/tests have been bundled",
    "M20": "Missing/incomplete/invalid HCPCS",
    "M51": "Missing/incomplete/invalid procedure code(s)",
    "M76": "Missing/incomplete/invalid diagnosis or condition",
    "M79": "Missing/incomplete/invalid charge",
    "MA04": "Secondary payment cannot be considered without the identity of the primary payer",
    "MA130": "Claim contains incomplete/invalid information; no appeal rights — resubmit",
    "N4": "Missing/incomplete/invalid prior insurance carrier(s) EOB",
    "N30": "Patient ineligible for this service",
    "N130": "Consult plan benefit documents/guidelines for coverage information",
    "N179": "Additional information has been requested from the member",
    "N286": "Missing/incomplete/invalid referring provider primary identifier",
    "N290": "Missing/incomplete/invalid rendering provider primary identifier",
    "N362": "The number of days or units exceeds our acceptable maximum",
    "N522": "Duplicate of a claim processed or to be processed as a crossover claim",
}

# Maternity procedure codes — business rule carried over from the legacy
# Relisc report notes: a claim is a maternity claim when any adjudicated
# service line procedure code is one of these (global OB / delivery codes).
MATERNITY_PROCEDURE_CODES: set[str] = {
    "59400", "59409", "59410", "59412", "59414",
    "59510", "59514", "59515",
    "59610", "59612", "59614", "59618", "59620", "59622",
}

# CLP08 — Facility type code (first two digits of the NUBC bill type)
FACILITY_TYPE_CODES: dict[str, str] = {
    "11": "Hospital — Inpatient",
    "12": "Hospital — Inpatient (Medicare Part B only)",
    "13": "Hospital — Outpatient",
    "14": "Hospital — Other",
    "21": "SNF — Inpatient",
    "22": "SNF — Inpatient (Part B)",
    "23": "SNF — Outpatient",
    "71": "Rural Health Clinic",
    "72": "ESRD Facility",
    "73": "FQHC",
    "81": "Hospice (non-hospital)",
    "85": "Critical Access Hospital",
}

CARC_AND_RARC: dict[str, tuple[str, str]] = {
    **{code: ("CARC", desc) for code, desc in CARC.items()},
    **{code: ("RARC", desc) for code, desc in RARC.items()},
}


def describe_reason_code(code: str) -> str:
    return CARC.get(code) or RARC.get(code) or ""
