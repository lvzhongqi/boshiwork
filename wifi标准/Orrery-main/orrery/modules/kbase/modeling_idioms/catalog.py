"""The identity-modelling material library under ``kb/modeling_idioms``.

A lookup returns up to three mutually exclusive curated abstractions for one
free-text description of a deployment mechanism. The flow model picks one with
the document still in context; the marker and the flow checks make that choice
durable and testable. The entries are loaded and validated at import time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

import orrery
from orrery.modules.kbase.modeling_idioms.lead import load_lead
from orrery.modules.kbase.modeling_idioms.retrieval import score

_PATH = (Path(orrery.__file__).parent / "kb" / "modeling_idioms" /
         "IDENTITY_MODELING.yaml")
_ID = re.compile(r"^identity\.[a-z][a-z0-9_]*$")
_VALIDATORS = {
    "identity_registry_v1", "identity_private_provisioning_v1",
    "identity_signed_certificate_v1",
}
_MACHINERIES = {"registry", "private_provisioning", "certificate"}


@dataclass(frozen=True)
class IdentityIdiom:
    """One curated way to model identity deployment: its cue phrases for
    retrieval, the prompt card handed to the model, and the machinery and
    validator name the flow checks use to verify the choice."""

    id: str
    version: int
    machinery: str
    validator: str
    aliases: tuple[str, ...]
    positive: tuple[str, ...]
    negative: tuple[str, ...]
    prompt: str

    @property
    def key(self) -> tuple[str, int]:
        return self.id, self.version


def _load(raw: dict) -> tuple[IdentityIdiom, ...]:
    """The library's entries, in YAML order. Raises RuntimeError on a bad id,
    version, prompt, machinery or validator, on a duplicate entry, on an alias
    claimed by two entries, or on an empty library."""
    if raw.get("schema_version") != 1:
        raise RuntimeError("[identity modeling] schema_version must be 1")
    out: list[IdentityIdiom] = []
    seen: set[tuple[str, int]] = set()
    aliases: dict[str, str] = {}
    for entry in raw.get("idioms", []):
        ident = entry.get("id")
        version = entry.get("version")
        if not isinstance(ident, str) or not _ID.fullmatch(ident):
            raise RuntimeError(f"[identity modeling] invalid id {ident!r}")
        if not isinstance(version, int) or version < 1:
            raise RuntimeError(f"[identity modeling] {ident}: version must be a positive integer")
        key = ident, version
        if key in seen:
            raise RuntimeError(f"[identity modeling] duplicate entry {ident}/v{version}")
        seen.add(key)
        prompt = entry.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise RuntimeError(f"[identity modeling] {ident}: prompt is required")
        item = IdentityIdiom(
            id=ident, version=version,
            machinery=str(entry.get("machinery", "")),
            validator=str(entry.get("validator", "")),
            aliases=tuple(entry.get("aliases", [])),
            positive=tuple(entry.get("positive", [])),
            negative=tuple(entry.get("negative", [])),
            prompt=prompt.strip(),
        )
        if not item.validator or not item.machinery:
            raise RuntimeError(f"[identity modeling] {ident}: validator and machinery are required")
        if item.validator not in _VALIDATORS:
            raise RuntimeError(
                f"[identity modeling] {ident}: unknown validator {item.validator!r}; "
                f"known: {sorted(_VALIDATORS)}")
        if item.machinery not in _MACHINERIES:
            raise RuntimeError(
                f"[identity modeling] {ident}: unknown machinery {item.machinery!r}; "
                f"known: {sorted(_MACHINERIES)}")
        for alias in item.aliases:
            normal = alias.strip().lower()
            if normal in aliases and aliases[normal] != ident:
                raise RuntimeError(
                    f"[identity modeling] alias {alias!r} belongs to both "
                    f"{aliases[normal]} and {ident}")
            aliases[normal] = ident
        out.append(item)
    if not out:
        raise RuntimeError("[identity modeling] the library is empty")
    return tuple(out)


_RAW = yaml.safe_load(_PATH.read_text(encoding="utf-8"))
_IDIOMS = _load(_RAW)
_LEAD = load_lead(_RAW, "identity modeling")
_BY_KEY = {x.key: x for x in _IDIOMS}


def identity_idioms() -> tuple[IdentityIdiom, ...]:
    """Every entry in the library, in YAML order."""
    return _IDIOMS


def identity_idiom(ident: str, version: int) -> IdentityIdiom | None:
    """One entry by (id, version), or None when there is no such entry."""
    return _BY_KEY.get((ident, version))


def search_identity_idioms(query: str, *, limit: int = 3) -> list[IdentityIdiom]:
    """The best-scoring entries for a free-text description, at most ``limit``
    (1 to 3) of them, strongest first. Entries that score nothing are dropped,
    so a query about an unknown mechanism gets an empty list. Raises
    ValueError on a blank query or a limit out of range."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("identity modeling query must be a non-empty string")
    if not 1 <= limit <= 3:
        raise ValueError("identity modeling result limit must be between 1 and 3")
    ranked = sorted(((score(query, x), x) for x in _IDIOMS),
                    key=lambda pair: (-pair[0], pair[1].id, pair[1].version))
    positive = [x for points, x in ranked if points > 0]
    return positive[:limit]


def identity_lead() -> str:
    """The sentence that introduces what a lookup returns."""
    return _LEAD
