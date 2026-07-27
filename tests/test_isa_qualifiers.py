"""ISA05/07 qualifiers are captured on read and honored on write (default "ZZ")."""

from datetime import date

from edipipe.core import OutGroup, OutTransaction, build_interchange, parse_envelope


def _raw(**kw) -> str:
    return build_interchange(
        [OutGroup("HC", "005010X223A2", [OutTransaction("837", [["BHT", "0019"]])])],
        sender="660500678", receiver="MCO1", interchange_date=date(2026, 7, 27),
        control="1", **kw,
    )


def test_isa_qualifiers_roundtrip():
    inter = parse_envelope(_raw(sender_qualifier="30", receiver_qualifier="ZZ"))
    assert inter.sender_qualifier == "30"
    assert inter.receiver_qualifier == "ZZ"
    assert inter.sender_id == "660500678"  # ISA06 unaffected by the qualifier change


def test_isa_qualifiers_default_zz():
    inter = parse_envelope(_raw())
    assert inter.sender_qualifier == "ZZ" and inter.receiver_qualifier == "ZZ"
