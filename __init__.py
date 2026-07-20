"""edipipe — X12 EDI engine for the MMIS platform.

Single source of truth for X12 parsing and (later) generation across all
transaction sets exchanged between First Medical (MCO) and ASES/PRMMIS.
Grew out of `remitpipe` (835-only); the 835 reader is now one module among
many on a shared, transaction-agnostic core.

Public surface:
- parse_envelope(raw)  -> core.Interchange   (envelope walk, any transaction)
- parse_835(raw)       -> RemitFile835        (convenience wrapper; 835 body)
- ParseError / EnvelopeError

House rule: readers never re-walk the envelope. `parse_envelope` runs once and
yields TransactionSet objects; each txn reader consumes one TransactionSet.
"""

from edipipe.core import (
    Delimiters,
    EnvelopeError,
    FunctionalGroup,
    Interchange,
    ParseError,
    TransactionSet,
    parse_envelope,
)
from edipipe.read.ack import (
    AckDetail,
    AckedUnit,
    AckFile,
    parse_277ca,
    parse_999,
    parse_ack,
)
from edipipe.read.x12_835 import (
    Adjustment835,
    Claim835,
    ProviderAdjustment835,
    RemitFile835,
    Service835,
    Transaction835,
    parse_835,
)

__all__ = [
    "parse_envelope",
    "parse_835",
    "parse_999",
    "parse_277ca",
    "parse_ack",
    "ParseError",
    "EnvelopeError",
    "Delimiters",
    "Interchange",
    "FunctionalGroup",
    "TransactionSet",
    "RemitFile835",
    "Transaction835",
    "Claim835",
    "Service835",
    "Adjustment835",
    "ProviderAdjustment835",
    "AckFile",
    "AckedUnit",
    "AckDetail",
]
