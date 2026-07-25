"""X12 generation (write side) for the shared edipipe kernel.

Mirror of `edipipe.read`. 837I/837P (lifted from digitalizacion's claimspipe.x12gen,
the portfolio's original production X12 writer) + payer-side response generators
(271 eligibility, 277 claim status, 278 prior-auth decision), all on
`edipipe.core.build.build_interchange`. Provider-side inquiry generators
(270/276/278 request) follow the same pattern.
"""

from edipipe.write.x12_271 import build_271
from edipipe.write.x12_277 import build_277
from edipipe.write.x12_278 import build_278
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
    "build_277",
    "build_278",
    "X12ClaimData",
    "X12ControlNumbers",
    "X12GenerationResult",
    "X12Diagnosis",
    "X12Procedure",
    "X12Code",
    "X12ServiceLine",
]
