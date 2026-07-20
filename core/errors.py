"""Parse error hierarchy for edipipe."""


class ParseError(Exception):
    """Raised when a transaction body is structurally invalid."""


class EnvelopeError(ParseError):
    """Raised when the ISA/GS/ST interchange envelope is malformed."""
