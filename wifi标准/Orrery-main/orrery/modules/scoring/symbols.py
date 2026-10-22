"""Symbol collection, validation and alpha-renaming for comparisons against the
corpus, and the one reader of the alignments a run files under ``eval/``."""

from __future__ import annotations

import json
from pathlib import Path


def scalars(value) -> set[str]:
    """Every scalar leaf inside a JSON value, as a set of strings."""
    if isinstance(value, dict):
        return set().union(*(scalars(v) for v in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(scalars(v) for v in value)) if value else set()
    return {str(value)}


def validate_symbol_mappings(rows: list[dict], candidate: set[str],
                             gold: set[str]) -> dict[str, str]:
    """A one-to-one map over the exact names offered to the model.

    Raises ValueError when a row names a symbol outside ``candidate`` or ``gold``,
    or when either side of the map is used twice.
    """
    out, reverse = {}, {}
    for i, row in enumerate(rows):
        c, g = row.get("candidate"), row.get("gold")
        if c not in candidate:
            raise ValueError(f"mappings[{i}] names unknown candidate {c!r}")
        if g not in gold:
            raise ValueError(f"mappings[{i}] names unknown gold symbol {g!r}")
        if c in out:
            raise ValueError(f"candidate symbol {c!r} is mapped more than once")
        if g in reverse:
            raise ValueError(
                f"gold symbol {g!r} is mapped from both {reverse[g]!r} and {c!r}")
        out[c], reverse[g] = g, c
    return out


def rename(value, mapping: dict[str, str]):
    """Rename scalar leaves while preserving the artifact's JSON shape."""
    if isinstance(value, dict):
        return {k: rename(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [rename(v, mapping) for v in value]
    if isinstance(value, tuple):
        return tuple(rename(v, mapping) for v in value)
    return mapping.get(str(value), value)


def assumption_symbols(doc: dict) -> set[str]:
    """Every symbol named by an assumption ``target``, across all three sections."""
    return set().union(*(scalars(e.get("target", {}))
                         for section in ("world", "fixed", "variable")
                         for e in doc.get(section, [])))


def property_symbols(doc: dict) -> set[str]:
    """Every symbol named by a property's ``values`` or ``parties``."""
    return set().union(*(scalars(p.get("values", [])) | scalars(p.get("parties", []))
                         for p in doc.get("properties", [])))


def rename_assumptions(doc: dict, mapping: dict[str, str]) -> dict:
    """The assumptions document with every ``target`` renamed through ``mapping``."""
    out = {**doc}
    for section in ("world", "fixed", "variable"):
        out[section] = [
            {**e, "target": rename(e.get("target", {}), mapping)}
            for e in doc.get(section, [])
        ]
    return out


def rename_properties(doc: dict, mapping: dict[str, str]) -> dict:
    """The properties document with ``values`` and ``parties`` renamed."""
    out = {**doc}
    out["properties"] = [{
        **p,
        "values": rename(p.get("values", []), mapping),
        "parties": rename(p.get("parties", []), mapping),
    } for p in doc.get("properties", [])]
    return out


def latest_alignment(eval_dir: Path, slug: str) -> tuple[dict[str, str], Path]:
    """The newest ``*_<slug>_alignment.json`` under ``eval_dir`` as a
    ``candidate → gold`` map, with the file it came from. Raises ValueError when
    there is none or the newest one records a failed alignment."""
    paths = sorted(eval_dir.glob(f"*_{slug}_alignment.json"))
    if not paths:
        raise ValueError(f"no {slug} symbol alignment is available")
    data = json.loads(paths[-1].read_text(encoding="utf-8"))
    if data.get("status") != "ok":
        raise ValueError(f"{slug} symbol alignment failed: {data.get('error', '')}")
    rows = data.get("mappings")
    if rows is None:  # principals has two typed mapping lists; not used here.
        rows = data.get("principal_mappings", []) + data.get("symbol_mappings", [])
    return {row["candidate"]: row["gold"] for row in rows}, paths[-1]
