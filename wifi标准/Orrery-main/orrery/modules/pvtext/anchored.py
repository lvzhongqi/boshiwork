"""Anchored edits: the model quotes a span of the current text verbatim (the
anchor) and gives a fragment to insert before or after it, or to replace it
with (an empty replacement deletes). The framework only matches and splices.

Edits apply in submission order, each matching against the result of the
previous one, so colliding regions surface as a missed anchor. An anchor must
match exactly once; zero or several raise :class:`EditError`. When the exact
match fails a whitespace-normalised line match is tried and a unique hit
accepted. Deletions quote what they remove — there is no line-range form.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Literal

POSITIONS = ("before", "after", "replace")


@dataclass(frozen=True)
class Edit:
    anchor: str                                     # verbatim quote, may span lines
    position: Literal["before", "after", "replace"]
    text: str                                       # the model's fragment; empty + replace = delete


class EditError(RuntimeError):
    """One edit could not be applied. The message is written for the model's
    repair round: which edit, what went wrong, and the nearest real line when
    the anchor missed."""

    #: Prefix on every message, so the ledger distinguishes an assembly failure
    #: from a check that did not pass or a solver rejection.
    KIND = "edits did not apply"

    def __init__(self, index: int, edit: Edit, reason: str):
        self.index = index
        self.edit = edit
        super().__init__(
            f"{self.KIND} — edit {index + 1} "
            f"({edit.position} {_shorten(edit.anchor)!r}): {reason}")


def apply_edits(text: str, edits: list[Edit]) -> str:
    """Apply ``edits`` in order and return the resulting text. Raises
    :class:`EditError` on the first edit that cannot be applied; no per-edit
    position bookkeeping is kept."""
    for i, e in enumerate(edits):
        if e.position not in POSITIONS:
            raise EditError(i, e, f"unknown position {e.position!r}; use before / after / replace")
        if not e.anchor.strip():
            raise EditError(i, e, "anchor is empty; quote the line(s) the edit attaches to")
        start, end = _locate(text, i, e)
        if e.position == "replace":
            ins_start, cut_end = start, end
            fragment = e.text
        elif e.position == "before":
            ins_start = cut_end = _line_start(text, start)
            fragment = e.text + "\n" if e.text and not e.text.endswith("\n") else e.text
        else:                                       # after
            ins_start = cut_end = _line_end(text, end)
            fragment = "\n" + e.text if e.text and not e.text.startswith("\n") else e.text
        text = text[:ins_start] + fragment + text[cut_end:]
    return text


def _locate(text: str, index: int, e: Edit) -> tuple[int, int]:
    """The anchor's span in ``text``. Exact match first; a unique
    whitespace-normalised line match second; everything else raises."""
    hits = [m.start() for m in re.finditer(re.escape(e.anchor), text)]
    if len(hits) == 1:
        return hits[0], hits[0] + len(e.anchor)
    if len(hits) > 1:
        raise EditError(
            index, e,
            f"anchor occurs {len(hits)} times; extend the quote with an adjacent "
            f"line until it is unique",
        )
    span = _normalised_match(text, index, e)
    if span is not None:
        return span
    near = _closest_line(text, e.anchor)
    # The nearest real line leads and the standing advice trails: the ledger
    # keeps only a 160-char digest of each finding, so a trailing hint is the
    # part that gets cut.
    lead = (f"anchor not found; closest real line: {near!r}" if near
            else "anchor not found, and nothing in the model is close to it")
    raise EditError(
        index, e,
        f"{lead} — quote the text exactly as it appears in the current model",
    )


def _normalised_match(text: str, index: int, e: Edit) -> tuple[int, int] | None:
    """Whole-line match with per-line whitespace collapsed. Only indentation and
    spacing may differ, so a unique hit is safe to accept; several hits raise."""
    want = [_squash(l) for l in e.anchor.splitlines() if _squash(l)]
    if not want:
        return None
    lines = text.splitlines(keepends=True)
    starts, off = [], 0
    for ln in lines:
        starts.append(off)
        off += len(ln)
    got = [_squash(l) for l in lines]
    hits = [
        i for i in range(len(got) - len(want) + 1)
        if got[i:i + len(want)] == want
    ]
    if len(hits) > 1:
        raise EditError(
            index, e,
            f"anchor matches {len(hits)} places once whitespace is normalised; "
            f"extend the quote with an adjacent line until it is unique",
        )
    if not hits:
        return None
    i = hits[0]
    last = i + len(want) - 1
    end = starts[last] + len(lines[last].rstrip("\n"))
    return starts[i], end


def _squash(line: str) -> str:
    return " ".join(line.split())


def _closest_line(text: str, anchor: str) -> str | None:
    first = next((l for l in anchor.splitlines() if l.strip()), "")
    candidates = [l.strip() for l in text.splitlines() if l.strip()]
    close = difflib.get_close_matches(first.strip(), candidates, n=1, cutoff=0.5)
    return close[0] if close else None


def _line_start(text: str, pos: int) -> int:
    return text.rfind("\n", 0, pos) + 1


def _line_end(text: str, pos: int) -> int:
    nl = text.find("\n", pos)
    return len(text) if nl < 0 else nl


def _shorten(s: str, limit: int = 60) -> str:
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 1] + "…"
