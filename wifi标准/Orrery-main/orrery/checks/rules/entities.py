"""Checks on the extracted principals — who takes part. Only the shape is
checked at must level.

payload is the submission read as it stands, ``{"principals": [...], ...}``,
so a finding can name the entry the model actually wrote.
"""

from __future__ import annotations

import re

from orrery.checks.registry import CheckResult, register

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _principals(payload) -> list:
    raw = payload.get("principals") if isinstance(payload, dict) else None
    return raw if isinstance(raw, list) else []


def _shape(payload) -> CheckResult:
    findings: list[str] = []
    if not isinstance(payload, dict) or not isinstance(payload.get("principals"), list):
        return CheckResult("entities_shape", "must", False,
                           ["principals must be an array"])
    principals = _principals(payload)
    if not principals:
        findings.append("principals is empty; extract at least one principal, each with a name and a description")
    for index, p in enumerate(principals):
        if not isinstance(p, dict):
            findings.append(f"principals[{index}] must be an object")
            continue
        extras = set(p) - {"name", "description"}
        missing = {"name", "description"} - set(p)
        if extras:
            findings.append(f"principals[{index}] has unsupported fields: "
                            f"{sorted(extras)}")
        if missing:
            findings.append(f"principals[{index}] is missing fields: "
                            f"{sorted(missing)}")
        name = p.get("name")
        if not isinstance(name, str) or not _NAME_RE.match(name):
            findings.append(
                f"principal name {name!r} has the wrong shape: must start with a letter and use only letters, digits and underscores"
            )
        desc = p.get("description")
        if not isinstance(desc, str) or not desc.strip():
            findings.append(f"principal {name!r}: the description must be a non-empty string")
    return CheckResult("entities_shape", "must", not findings, findings)


def _unique(payload) -> CheckResult:
    """Two principals under one name. Duplicate value names belong to
    init_knowledge.py::_shape, which can say which of the four lists each
    definition came from.
    """
    f: list[str] = []
    seen: set[str] = set()
    for p in _principals(payload):
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        if name in seen:
            f.append(f"principal {name!r} appears more than once; give each "
                     f"principal one entry")
        seen.add(name)
    return CheckResult("entities_unique", "must", not f, f)


def _count(payload) -> CheckResult:
    n = len(_principals(payload))
    ok = n >= 2
    return CheckResult(
        "entities_count", "warn", ok,
        [] if ok else [f"only {n} principal extracted; a cryptographic protocol usually has at least two parties, so check nothing was missed"],
    )


register("entities_shape", "must", _shape)
register("entities_unique", "must", _unique)
register("entities_count", "warn", _count)

ENTITY_CHECK_NAMES = ["entities_shape", "entities_unique", "entities_count"]
