"""Round-trip tests for the core envelope writer (build.py).

The contract: parse_envelope(build_interchange(...)) reproduces the groups,
transaction codes, and bodies that went in — including under non-default
(partner) delimiters, and with correct SE/GE/IEA control counts.
"""

from datetime import date

from edipipe.core import (
    Delimiters,
    OutGroup,
    OutTransaction,
    build_interchange,
    parse_envelope,
)


def _sample_837_body() -> list[list[str]]:
    return [
        ["BHT", "0019", "00", "0123", "20260724", "1200", "CH"],
        ["NM1", "41", "2", "ALPINE HEALTH", "", "", "", "", "46", "ALPINEFM"],
        ["CLM", "PATIENT-1", "500", "", "", "11:B:1", "Y", "A", "Y", "Y"],
        ["SE_UNSEEN_TAG", "should", "survive"],  # arbitrary body segment
    ]


def test_roundtrip_default_delimiters():
    body = _sample_837_body()
    raw = build_interchange(
        [OutGroup("HC", "005010X223A2", [OutTransaction("837", body)])],
        sender="ALPINEFM",
        receiver="MMISPR",
        interchange_date=date(2026, 7, 24),
        control="42",
    )
    inter = parse_envelope(raw)
    assert inter.sender_id == "ALPINEFM"
    assert inter.receiver_id == "MMISPR"
    assert inter.control == "000000042"
    assert inter.usage == "P"
    assert inter.interchange_date == date(2026, 7, 24)

    txns = inter.transaction_sets("837")
    assert len(txns) == 1
    assert txns[0].code == "837"
    # Body reproduced exactly (ST/SE stripped by the reader, added by the writer).
    assert txns[0].segments == body
    assert inter.groups[0].version == "005010X223A2"
    assert inter.groups[0].functional_id == "HC"


def test_roundtrip_non_default_delimiters():
    # Pipe element sep, caret terminator, > component, ~ repetition — the reader
    # must recover these from the ISA the writer emitted, not assume defaults.
    delims = Delimiters(element="|", component=">", repetition="~", segment="^")
    body = [["BHT", "0019", "00", "X"], ["NM1", "41", "2", "ALPINE"]]
    raw = build_interchange(
        [OutGroup("HC", "005010X222A1", [OutTransaction("837", body)])],
        sender="PROV1",
        receiver="PAYER1",
        interchange_date=date(2026, 7, 24),
        control="7",
        delims=delims,
    )
    inter = parse_envelope(raw)
    assert inter.delims.element == "|"
    assert inter.delims.segment == "^"
    assert inter.delims.component == ">"
    assert inter.transaction_sets("837")[0].segments == body


def test_control_counts_correct():
    # Two transactions in one group: SE per txn, GE=2, IEA=1.
    g = OutGroup(
        "HC", "005010X223A2",
        [
            OutTransaction("837", [["BHT", "0019"], ["CLM", "A", "100"]], control="0001"),
            OutTransaction("837", [["BHT", "0019"], ["CLM", "B", "200"], ["CLM", "C", "300"]], control="0002"),
        ],
    )
    raw = build_interchange(
        [g], sender="S", receiver="R", interchange_date=date(2026, 7, 24), control="1"
    )
    segs = [line.split("*") for line in raw.split("~") if line]
    by_tag = {}
    for s in segs:
        by_tag.setdefault(s[0], []).append(s)
    # First SE: ST + 2 body + SE = 4; second: ST + 3 body + SE = 5.
    se = by_tag["SE"]
    assert se[0][1] == "4" and se[1][1] == "5"
    assert by_tag["GE"][0][1] == "2"   # two transaction sets
    assert by_tag["IEA"][0][1] == "1"  # one functional group
    # And it parses back to two 837s.
    assert len(parse_envelope(raw).transaction_sets("837")) == 2
