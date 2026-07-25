"""X12 generation (write side) for the shared edipipe kernel.

Mirror of `edipipe.read`. Today: 837I/837P (lifted from digitalizacion's
claimspipe.x12gen, the portfolio's only production X12 writer). Future: 270/276/278
generation, built on `edipipe.core.build.build_interchange`.
"""

from edipipe.write.x12_837 import (
    X12ClaimData,
    X12Code,
    X12ControlNumbers,
    X12Diagnosis,
    X12GenerationResult,
    X12Procedure,
    X12ServiceLine,
    generate_x12,
)

__all__ = [
    "generate_x12",
    "X12ClaimData",
    "X12ControlNumbers",
    "X12GenerationResult",
    "X12Diagnosis",
    "X12Procedure",
    "X12Code",
    "X12ServiceLine",
]
