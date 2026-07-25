"""Element value conversions shared across transaction readers.

These operate on already-tokenized element strings and never raise on empty
input — X12 situational elements are frequently absent.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from edipipe.core.errors import ParseError


def dec(value: str | None) -> Decimal:
    """Parse a numeric element to Decimal; empty/None -> 0."""
    if not value:
        return Decimal("0")
    try:
        return Decimal(value)
    except InvalidOperation as exc:  # pragma: no cover - defensive
        raise ParseError(f"Invalid numeric value in segment element: {value!r}") from exc


def ymd8(value: str | None) -> date | None:
    """Parse an X12 date element to a date.

    Format is chosen by LENGTH, not by trial order: 8 digits = CCYYMMDD
    (DTM/SVC dates), 6 digits = YYMMDD (the ISA09 interchange date). Trying
    "%Y%m%d" first would mis-parse a 6-digit ISA date — Python reads "260612"
    as year 2606, month 01, day 02 rather than 2026-06-12.
    """
    if not value:
        return None
    value = value.strip()
    if len(value) == 8:
        fmt = "%Y%m%d"
    elif len(value) == 6:
        fmt = "%y%m%d"
    else:
        return None
    try:
        return datetime.strptime(value, fmt).date()
    except ValueError:
        return None
