"""Alpha-renaming primitives for semantic principals inventories.

The model's only job is to pair names that denote the same formal value in two
independently written ``principals.json`` files. Pure code validates the proposed
bijection and rewrites the candidate; the ordinary exact scorer then compares.
"""

from __future__ import annotations

from dataclasses import dataclass


_MAPPING = {
    "type": "object",
    "properties": {
        "candidate": {"type": "string"},
        "gold": {"type": "string"},
        "evidence": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["candidate", "gold", "evidence"],
    "additionalProperties": False,
}

ALIGNMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "principal_mappings": {"type": "array", "items": _MAPPING},
        "symbol_mappings": {"type": "array", "items": _MAPPING},
    },
    "required": ["principal_mappings", "symbol_mappings"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class _Symbol:
    sources: tuple[str, ...] = ()


def _principals(doc: dict) -> set[str]:
    return {str(p.get("name")) for p in doc.get("principals", [])}


def _symbols(doc: dict) -> dict[str, _Symbol]:
    out: dict[str, _Symbol] = {}

    def put(name, spec: _Symbol) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("initial-knowledge symbol names must be non-empty strings")
        if name in out:
            raise ValueError(f"initial-knowledge symbol {name!r} is declared twice")
        out[name] = spec

    for value in doc.get("values", []):
        sources = value.get("derived_from") or []
        if not isinstance(sources, list) or any(
                not isinstance(source, str) for source in sources):
            raise ValueError("derived_from must be a list of symbol names")
        put(value.get("name"), _Symbol(tuple(sources)))
    return out


def _pairs(rows: list[dict], *, label: str, candidates: set[str],
           golds: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    reverse: dict[str, str] = {}
    for i, row in enumerate(rows):
        c, g = row.get("candidate"), row.get("gold")
        if c not in candidates:
            raise ValueError(f"{label}[{i}] names unknown candidate {c!r}")
        if g not in golds:
            raise ValueError(f"{label}[{i}] names unknown gold symbol {g!r}")
        if c in out:
            raise ValueError(f"{label} maps candidate {c!r} more than once")
        if g in reverse:
            raise ValueError(
                f"{label} maps gold symbol {g!r} from both {reverse[g]!r} and {c!r}")
        out[c], reverse[g] = g, c
    return out


def validate_alignment(candidate: dict, gold: dict, alignment: dict) -> dict:
    """Validate and return the two bijections proposed by the model, as
    ``{"principals": ..., "symbols": ...}``.

    Raises ValueError when a row names an unknown symbol, when either side is
    mapped twice, or when a derived value is renamed without its sources being
    renamed to match. Descriptions are semantic evidence rather than comparable
    labels, so they are not constrained here.
    """
    cp, gp = _principals(candidate), _principals(gold)
    cs, gs = _symbols(candidate), _symbols(gold)
    pmap = _pairs(alignment.get("principal_mappings", []), label="principal_mappings",
                  candidates=cp, golds=gp)
    smap = _pairs(alignment.get("symbol_mappings", []), label="symbol_mappings",
                  candidates=set(cs), golds=set(gs))

    for c, g in smap.items():
        candidate_sources = cs[c].sources
        gold_sources = gs[g].sources
        if bool(candidate_sources) != bool(gold_sources):
            raise ValueError(
                f"symbol mapping {c!r} -> {g!r} crosses dependency categories")
        if candidate_sources:
            missing = [source for source in candidate_sources if source not in smap]
            mapped = tuple(smap[source] for source in candidate_sources
                           if source in smap)
            if missing or set(mapped) != set(gold_sources):
                raise ValueError(
                    f"dependency mapping {c!r} -> {g!r} must also map its "
                    f"sources {candidate_sources!r} to {gold_sources!r}")
    return {"principals": pmap, "symbols": smap}


def apply_alignment(candidate: dict, maps: dict) -> dict:
    """Return the candidate alpha-renamed into the gold vocabulary."""
    pmap, smap = maps["principals"], maps["symbols"]
    principal = lambda name: pmap.get(name, name)  # noqa: E731
    symbol = lambda name: smap.get(name, name)     # noqa: E731
    out = {
        "principals": [
            {**p, "name": principal(p.get("name"))}
            for p in candidate.get("principals", [])
        ],
        "values": [],
    }
    out["values"] = [{
        **value,
        "name": symbol(value.get("name")),
        "derived_from": [symbol(x) for x in value.get("derived_from", [])],
    } for value in candidate.get("values", [])]
    return out
