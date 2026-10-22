"""Read the semantic principals artifact without turning it into ProVerif.

``principals.json`` holds document-level actors, stable value names,
descriptions, and deterministic dependencies. Types, holder sets, role
signatures, declarations, and the main process are the flow model's choices,
so nothing here manufactures them.
"""

from __future__ import annotations


def template_roles(data: dict) -> list[str]:
    """The principal names whose role markers and honest probes are rendered."""
    return [p["name"] for p in data.get("principals") or []]


def value_names(data: dict) -> list[str]:
    """Stable semantic value names, preserving extraction order."""
    return [v["name"] for v in data.get("values") or []]


def dependency_map(data: dict) -> dict[str, tuple[str, ...]]:
    """Every value's deterministic source names, verbatim from the artifact.

    Checking that the references exist and form a DAG belongs to the principals
    checks; flow checks compare these dependencies with the generated ProVerif
    bindings.
    """
    return {
        value["name"]: tuple(value.get("derived_from") or [])
        for value in data.get("values") or []
    }
