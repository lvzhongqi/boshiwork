"""The role-body-structure material library under ``kb/modeling_idioms``.

One question: this party has more than one way to be entered — what shape does
its role body take? A principal renders as one process, so the several entries
live in parallel inside that one body, and this library says how.

The lookup returns a single method and never misses. Whether entries are
really independent, rather than an error branch or steps of one run, is a
judgement about the document that phrase scoring cannot make; the card's own
closing paragraph and the acceptance check carry it instead, the latter by
verifying every entry begins with its own ``in(...)``.
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
         "STRUCTURE_MODELING.yaml")
_ID = re.compile(r"^structure\.[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class StructureIdiom:
    """One curated shape for a role body: its cue phrases for retrieval and
    the prompt card handed to the model."""

    id: str
    version: int
    aliases: tuple[str, ...]
    positive: tuple[str, ...]
    negative: tuple[str, ...]
    prompt: str

    @property
    def key(self) -> tuple[str, int]:
        return self.id, self.version


def _load(raw: dict) -> tuple[StructureIdiom, ...]:
    """The library's entries, in YAML order. Raises RuntimeError on a bad id,
    version or prompt, on a missing cue list, on a duplicate entry, on an alias
    claimed by two entries, or on an empty library."""
    if raw.get("schema_version") != 1:
        raise RuntimeError("[structure modeling] schema_version must be 1")
    out: list[StructureIdiom] = []
    seen: set[tuple[str, int]] = set()
    aliases: dict[str, str] = {}
    for entry in raw.get("idioms", []):
        ident = entry.get("id")
        version = entry.get("version")
        if not isinstance(ident, str) or not _ID.fullmatch(ident):
            raise RuntimeError(f"[structure modeling] invalid id {ident!r}")
        if not isinstance(version, int) or version < 1:
            raise RuntimeError(
                f"[structure modeling] {ident}: version must be a positive integer")
        key = ident, version
        if key in seen:
            raise RuntimeError(f"[structure modeling] duplicate entry {ident}/v{version}")
        seen.add(key)
        prompt = entry.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise RuntimeError(f"[structure modeling] {ident}: prompt is required")
        item = StructureIdiom(
            id=ident, version=version,
            aliases=tuple(entry.get("aliases", [])),
            positive=tuple(entry.get("positive", [])),
            negative=tuple(entry.get("negative", [])),
            prompt=prompt.strip(),
        )
        if not item.aliases or not item.positive or not item.negative:
            raise RuntimeError(
                f"[structure modeling] {ident}: aliases, positive and negative cues are "
                f"all required — the negative cues are what separates independent "
                f"entries from the sequential steps this shape must not be used for")
        for alias in item.aliases:
            normal = alias.strip().lower()
            if normal in aliases and aliases[normal] != ident:
                raise RuntimeError(
                    f"[structure modeling] alias {alias!r} belongs to both "
                    f"{aliases[normal]} and {ident}")
            aliases[normal] = ident
        out.append(item)
    if not out:
        raise RuntimeError("[structure modeling] the library is empty")
    return tuple(out)


_RAW = yaml.safe_load(_PATH.read_text(encoding="utf-8"))
_IDIOMS = _load(_RAW)
_LEAD = load_lead(_RAW, "structure modeling")
_BY_KEY = {x.key: x for x in _IDIOMS}


def structure_idioms() -> tuple[StructureIdiom, ...]:
    """Every entry in the library, in YAML order."""
    return _IDIOMS


def structure_idiom(ident: str, version: int) -> StructureIdiom | None:
    """One entry by (id, version), or None when there is no such entry."""
    return _BY_KEY.get((ident, version))


def select_structure_idiom(query: str) -> StructureIdiom:
    """The one method for this description: always an entry, never a menu.

    Scoring only ranks the entries; it is not a gate, so even a query nothing
    matches gets the top-ranked shape back. Raises ValueError on a blank query.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("structure modeling query must be a non-empty string")
    ranked = sorted(((score(query, x), x) for x in _IDIOMS),
                    key=lambda pair: (-pair[0], pair[1].id, pair[1].version))
    return ranked[0][1]


def structure_lead() -> str:
    """The sentence that introduces what a lookup returns."""
    return _LEAD
