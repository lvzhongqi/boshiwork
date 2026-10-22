"""Checks for the semantic value inventory in ``principals.json``.

The artifact holds ``principals`` and ``values``; a value carries a name, a
``derived_from`` list and a description. The checks enforce unique names,
non-empty descriptions, and an acyclic ``derived_from`` graph over the values.
"""

from __future__ import annotations

import re

from orrery.checks.registry import CheckResult, register

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _shape(payload) -> CheckResult:
    findings: list[str] = []
    if not isinstance(payload, dict):
        return CheckResult("ik_shape", "must", False,
                           ["principals submission must be an object"])
    extras = set(payload) - {"principals", "values"}
    missing = {"principals", "values"} - set(payload)
    if extras:
        findings.append(f"principals submission has unsupported top-level "
                        f"fields: {sorted(extras)}")
    if missing:
        findings.append(f"principals submission is missing top-level fields: "
                        f"{sorted(missing)}")

    raw = payload.get("values")
    if not isinstance(raw, list):
        return CheckResult("ik_shape", "must", False,
                           ["values must be an array"])
    if not raw:
        findings.append("values is empty; extract the protocol identities and "
                        "other important pre-run values")

    names: list[str] = []
    rows: dict[str, dict] = {}
    for index, value in enumerate(raw):
        if not isinstance(value, dict):
            findings.append(f"values[{index}] must be an object")
            continue
        extras = set(value) - {"name", "derived_from", "description"}
        missing = {"name", "derived_from", "description"} - set(value)
        if extras:
            findings.append(f"values[{index}] has unsupported fields: "
                            f"{sorted(extras)}")
        if missing:
            findings.append(f"values[{index}] is missing fields: "
                            f"{sorted(missing)}")
        name = value.get("name")
        where = f"values[{name!r}]"
        if not isinstance(name, str) or not _NAME_RE.match(name):
            findings.append(f"{where}: name may use only letters, digits and "
                            "underscores, and may not start with a digit")
        elif name in rows:
            findings.append(f"{where}: the name is already defined; every "
                            "semantic value has exactly one record")
        else:
            names.append(name)
            rows[name] = value

        description = value.get("description")
        if not isinstance(description, str) or not description.strip():
            findings.append(f"{where}: description must be a non-empty string")
        dependencies = value.get("derived_from")
        if not isinstance(dependencies, list):
            findings.append(f"{where}: derived_from must be an array of value "
                            "names (an empty array for an independent value)")
        elif any(not isinstance(source, str) for source in dependencies):
            findings.append(f"{where}: every derived_from entry must be a string")
        elif len(dependencies) != len(set(dependencies)):
            findings.append(f"{where}: derived_from repeats a source value")

    declared = set(names)
    graph: dict[str, list[str]] = {}
    for name, value in rows.items():
        dependencies = value.get("derived_from")
        if not isinstance(dependencies, list) or any(
                not isinstance(source, str) for source in dependencies):
            continue
        graph[name] = dependencies
        for source in dependencies:
            if source == name:
                findings.append(f"values[{name!r}]: a value cannot derive from itself")
            elif source not in declared:
                findings.append(f"values[{name!r}]: derived_from names {source!r}, "
                                "which is not another declared value")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str, path: list[str]) -> None:
        if name in visited:
            return
        if name in visiting:
            start = path.index(name) if name in path else 0
            cycle = path[start:] + [name]
            findings.append("derived_from contains a cycle: " + " -> ".join(cycle))
            return
        visiting.add(name)
        path.append(name)
        for source in graph.get(name, []):
            if source in graph:
                visit(source, path)
        path.pop()
        visiting.remove(name)
        visited.add(name)

    for name in graph:
        visit(name, [])

    return CheckResult("ik_shape", "must", not findings, findings)


register("ik_shape", "must", _shape)

IK_CHECK_NAMES = ["ik_shape"]
