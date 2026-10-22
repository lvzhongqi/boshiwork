"""The time-variant-parameter material library under ``kb/modeling_idioms``.

Timestamps, ticket lifetimes and sequence numbers, and the two ways the
corpus's ground truth encodes them. A lookup returns a single method: the two
entries are a default and one narrowly gated exception, the gate being three
conditions the model reads off the document. The exception is an epoch/lifetime
state machine, which can cost ProVerif its verdict entirely.
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
         "TIME_VARIANT_MODELING.yaml")
_ID = re.compile(r"^time\.[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class TimeVariantIdiom:
    """One curated way to model a time-variant parameter: its cue phrases for
    retrieval and the prompt card handed to the model."""

    id: str
    version: int
    aliases: tuple[str, ...]
    positive: tuple[str, ...]
    negative: tuple[str, ...]
    prompt: str

    @property
    def key(self) -> tuple[str, int]:
        return self.id, self.version


def _load(raw: dict) -> tuple[TimeVariantIdiom, ...]:
    """The library's entries, in YAML order. Raises RuntimeError on a bad id,
    version or prompt, on a missing cue list, on a duplicate entry, on an alias
    claimed by two entries, on an empty library, or when the fallback entry
    ``_DEFAULT`` is absent."""
    if raw.get("schema_version") != 1:
        raise RuntimeError("[time-variant modeling] schema_version must be 1")
    out: list[TimeVariantIdiom] = []
    seen: set[tuple[str, int]] = set()
    aliases: dict[str, str] = {}
    for entry in raw.get("idioms", []):
        ident = entry.get("id")
        version = entry.get("version")
        if not isinstance(ident, str) or not _ID.fullmatch(ident):
            raise RuntimeError(f"[time-variant modeling] invalid id {ident!r}")
        if not isinstance(version, int) or version < 1:
            raise RuntimeError(
                f"[time-variant modeling] {ident}: version must be a positive integer")
        key = ident, version
        if key in seen:
            raise RuntimeError(f"[time-variant modeling] duplicate entry {ident}/v{version}")
        seen.add(key)
        prompt = entry.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise RuntimeError(f"[time-variant modeling] {ident}: prompt is required")
        item = TimeVariantIdiom(
            id=ident, version=version,
            aliases=tuple(entry.get("aliases", [])),
            positive=tuple(entry.get("positive", [])),
            negative=tuple(entry.get("negative", [])),
            prompt=prompt.strip(),
        )
        if not item.aliases or not item.positive:
            raise RuntimeError(
                f"[time-variant modeling] {ident}: aliases and positive cues are required, "
                f"they are the whole of how retrieval reaches this entry")
        for alias in item.aliases:
            normal = alias.strip().lower()
            if normal in aliases and aliases[normal] != ident:
                raise RuntimeError(
                    f"[time-variant modeling] alias {alias!r} belongs to both "
                    f"{aliases[normal]} and {ident}")
            aliases[normal] = ident
        out.append(item)
    if not out:
        raise RuntimeError("[time-variant modeling] the library is empty")
    if not any(x.id == _DEFAULT for x in out):
        raise RuntimeError(
            f"[time-variant modeling] {_DEFAULT} is the fallback this library "
            f"returns when nothing scores, so it has to exist")
    return tuple(out)


# The entry that is safe whatever the document says, an opaque fresh value, and
# the fallback when nothing scores. A miss here is not a coverage gap.
_DEFAULT = "time.opaque_fresh_value"

_RAW = yaml.safe_load(_PATH.read_text(encoding="utf-8"))
_IDIOMS = _load(_RAW)
_LEAD = load_lead(_RAW, "time-variant modeling")
_BY_KEY = {x.key: x for x in _IDIOMS}


def time_variant_idioms() -> tuple[TimeVariantIdiom, ...]:
    """Every entry in the library, in YAML order."""
    return _IDIOMS


def time_variant_idiom(ident: str, version: int) -> TimeVariantIdiom | None:
    """One entry by (id, version), or None when there is no such entry."""
    return _BY_KEY.get((ident, version))


def select_time_variant_idiom(query: str) -> TimeVariantIdiom:
    """The one method for this description: always an entry, never a menu.

    Scoring only decides whether the narrow exception outscores the default;
    with nothing matching, the latest ``_DEFAULT`` version is the answer.
    Raises ValueError on a blank query.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("time-variant modeling query must be a non-empty string")
    ranked = sorted(((score(query, x), x) for x in _IDIOMS),
                    key=lambda pair: (-pair[0], pair[1].id, pair[1].version))
    points, best = ranked[0]
    if points <= 0:
        return _BY_KEY[(_DEFAULT, max(v for i, v in _BY_KEY if i == _DEFAULT))]
    return best


def time_variant_lead() -> str:
    """The sentence that introduces what a lookup returns."""
    return _LEAD
