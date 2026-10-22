"""File layer for the five LIB JSON files: read, gate on version, deserialise
into the data classes, and dump back out. Semantic checks live in validate.py.

Every read goes through ``require_vocab_version`` first, so a stale file or one
carrying no version number fails on the spot.
"""
from __future__ import annotations

import json
from pathlib import Path

from orrery.modules.libschema.model import (
    AssumptionsDoc,
    CaseMatrix,
    ClaimsDoc,
    PropertiesDoc,
    ResultsDoc,
)
from orrery.modules.libschema.version import require_vocab_version


def _read_json(path):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"[libschema.io] file not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def parse_assumptions(data, *, where="<dict>"):
    """Turn an in-memory dict into an ``AssumptionsDoc``, gating on version
    first. ``where`` only names the source in error messages."""
    return AssumptionsDoc.from_json(
        require_vocab_version(data, kind="assumptions", path=where))


def parse_properties(data, *, where="<dict>"):
    """Turn an in-memory dict into a ``PropertiesDoc``. Properties are a pure
    vocabulary, so parsing one needs no assumptions."""
    return PropertiesDoc.from_json(
        require_vocab_version(data, kind="properties", path=where))


def parse_claims(data, assumptions, *, where="<dict>"):
    """Turn an in-memory dict into a ``ClaimsDoc``. Its ``scenarios`` reference
    assumption ``id`` values, so a parsed ``assumptions`` doc is required."""
    return ClaimsDoc.from_json(
        require_vocab_version(data, kind="claims", path=where), assumptions)


def load_assumptions(path):
    return parse_assumptions(_read_json(path), where=str(path))


def load_properties(path):
    return parse_properties(_read_json(path), where=str(path))


def load_claims(path, assumptions):
    """Load claims.json. Its scenarios carry only {id, subtype}, so they are
    resolved against ``assumptions``; a dangling id raises."""
    return parse_claims(_read_json(path), assumptions, where=str(path))


def load_results(path):
    data = require_vocab_version(_read_json(path), kind="results", path=str(path))
    return ResultsDoc.from_json(data)


def load_cases_results(path, assumptions):
    """Load cases_results.json. Each ``scenario`` carries only {id, subtype}
    and resolves against ``assumptions``, the same as load_claims."""
    data = require_vocab_version(_read_json(path), kind="cases_results", path=str(path))
    return CaseMatrix.from_json(data, assumptions)


def _write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def dump_assumptions(doc, path):
    _write_json(path, doc.to_json())


def dump_properties(doc, path):
    _write_json(path, doc.to_json())


def dump_claims(doc, path):
    _write_json(path, doc.to_json())


def dump_results(doc, path):
    _write_json(path, doc.to_json())


def dump_cases_results(matrix, path):
    _write_json(path, matrix.to_json())
