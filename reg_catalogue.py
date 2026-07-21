"""Reader for the shared regulatory catalogue (single source of truth).

Every Alpine / First Medical (Plan Vital) app reads its laws / regulations /
standards from ONE place: the ``alpine-reg-catalogue`` repo, vendored here as a
git submodule at ``vendor/alpine-reg-catalogue``. Don't hardcode citations in
this app — reference an authority by its stable id (``RL-F25``, ``RL-P08`` …)
and let this module resolve the title / citation / url / domains.

Usage
-----
    from edipipe import reg_catalogue as reg

    reg.by_id("RL-F25")                    # X12/HIPAA transactions authority (835)
    reg.by_domain("edi")                   # every authority tagged `edi`
    reg.authorities_for_artifact("835")    # governing authorities for the 835
    reg.mappings_for_app()                 # this app's rule->artifact map (+ shared)

If the submodule isn't checked out, calls raise ``CatalogueUnavailable`` with a
clear remediation message (``git submodule update --init``) rather than failing
silently — a compliance surface should never invent citations.
"""
from __future__ import annotations

import json
import pathlib
from functools import lru_cache
from typing import Any, Dict, List, Optional

# This app's identity in the catalogue's rule->artifact mappings, and the
# domains it actually cares about (used by callers to filter the full set).
APP = "mmis-835"
DOMAINS = ("edi", "claims", "encounters", "financial")


class CatalogueUnavailable(RuntimeError):
    """Raised when the vendored catalogue can't be located/parsed."""


def _catalogue_dir() -> pathlib.Path:
    """Walk up from this file to find vendor/alpine-reg-catalogue/data."""
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "vendor" / "alpine-reg-catalogue" / "data"
        if (cand / "authorities.json").is_file():
            return cand
    raise CatalogueUnavailable(
        "shared regulatory catalogue not found. Run "
        "`git submodule update --init vendor/alpine-reg-catalogue` "
        "at the repo root."
    )


@lru_cache(maxsize=1)
def _load() -> Dict[str, Any]:
    data = _catalogue_dir()
    try:
        authorities = json.loads(
            (data / "authorities.json").read_text(encoding="utf-8")
        )["authorities"]
        mappings = json.loads(
            (data / "mappings.json").read_text(encoding="utf-8")
        )["mappings"]
    except (OSError, ValueError, KeyError) as exc:  # pragma: no cover
        raise CatalogueUnavailable(f"catalogue is present but unreadable: {exc}") from exc
    return {
        "authorities": authorities,
        "mappings": mappings,
        "by_id": {a["id"]: a for a in authorities},
    }


def all_authorities() -> List[Dict[str, Any]]:
    return list(_load()["authorities"])


def by_id(authority_id: str) -> Optional[Dict[str, Any]]:
    """Resolve one authority by its stable id, or None if unknown."""
    return _load()["by_id"].get(authority_id)


def by_ids(ids: List[str]) -> List[Dict[str, Any]]:
    lut = _load()["by_id"]
    return [lut[i] for i in ids if i in lut]


def by_domain(domain: str) -> List[Dict[str, Any]]:
    return [a for a in _load()["authorities"] if domain in a.get("domains", [])]


def by_jurisdiction(jurisdiction: str) -> List[Dict[str, Any]]:
    return [a for a in _load()["authorities"] if a.get("jurisdiction") == jurisdiction]


def mappings_for_app(app: str = APP) -> List[Dict[str, Any]]:
    """Rule->artifact mappings scoped to this app plus the shared set."""
    return [m for m in _load()["mappings"] if m.get("app") in (app, "shared")]


def authorities_for_artifact(artifact: str, app: str = APP) -> List[Dict[str, Any]]:
    """The governing authorities for a concrete artifact (e.g. '835', 'CARC').

    Matches the mapping whose ``artifact`` equals or contains the query
    (case-insensitive), then resolves its authority ids.
    """
    q = artifact.lower()
    ids: List[str] = []
    for m in mappings_for_app(app):
        if q == m.get("artifact", "").lower() or q in m.get("artifact", "").lower():
            ids.extend(m.get("authorities", []))
    # de-dup preserving order
    seen, ordered = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            ordered.append(i)
    return by_ids(ordered)


def cite(authority_id: str) -> str:
    """Short human string for logs / UI: 'RL-F25 — <citation>'."""
    a = by_id(authority_id)
    return f"{authority_id} — {a['citation']}" if a else authority_id
