"""The one retrieval function the modelling-idiom libraries share.

Deterministic hybrid scoring over phrases and semantic cue cards: a phrase hit
carries most of the score, token overlap lets a paraphrase reach the right
card, and negative cues demote a candidate without vetoing it, since a query
may quote a distinction precisely to say it is absent.
"""

from __future__ import annotations

import re
from typing import Protocol

_WORD = re.compile(r"[a-z0-9_]+|[\u3400-\u9fff]+", re.I)


class CuedIdiom(Protocol):
    """What scoring needs from an entry: three phrase lists."""

    aliases: tuple[str, ...]
    positive: tuple[str, ...]
    negative: tuple[str, ...]


def terms(text: str) -> set[str]:
    """The lowercased tokens of a text: word runs and CJK runs."""
    return {x.lower() for x in _WORD.findall(text)}


def score(query: str, item: CuedIdiom) -> int:
    """One entry's points against a query. Aliases weigh most, then positive
    cues; a negative cue phrase found verbatim subtracts. A whole-phrase hit
    outweighs token overlap, and the result may be zero or negative."""
    q = query.casefold()
    qterms = terms(q)
    total = 0
    for phrase in item.aliases:
        p = phrase.casefold()
        total += 12 if p in q else 2 * len(qterms & terms(p))
    for phrase in item.positive:
        p = phrase.casefold()
        total += 8 if p in q else len(qterms & terms(p))
    for phrase in item.negative:
        p = phrase.casefold()
        total -= 5 if p in q else 0
    return total
