"""X12 generation (write side) for the shared edipipe kernel.

Mirror of `edipipe.read`. 837I/837P (lifted from digitalizacion's claimspipe.x12gen,
the portfolio's original production X12 writer) + 271 eligibility responses, all on
`edipipe.core.build.build_interchange`. Future: 276/277 + 278 generation.
"""

from edipipe.write.x12_271 import build_271
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
    "build_271",
    "X12ClaimData",
    "X12ControlNumbers",
    "X12GenerationResult",
    "X12Diagnosis",
    "X12Procedure",
    "X12Code",
    "X12ServiceLine",
]
