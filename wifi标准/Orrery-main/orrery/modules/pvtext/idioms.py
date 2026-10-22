"""Durable modelling-idiom markers carried by the ProVerif text itself, saying
which curated method the text implements.

Two grammars share the ``@orrery-idiom`` keyword. An identity method applies to
a scope (``scope=``, one registration table or trust relation) and several
scopes may each choose their own; a structure method applies to the role body it
sits in and names the entries that body composes in parallel (``entries=``),
which is the list the acceptance check counts against the text. The marker has
to survive into ``flow.pv``, where a supplied mother model and the assumption
layer read it without the session that chose it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MARKER = re.compile(
    r"\(\*\s*@orrery-idiom\s+"
    r"(?P<id>identity\.[a-z][a-z0-9_]*)/v(?P<version>[1-9][0-9]*)\s+"
    r"scope=(?P<scope>[a-z][a-z0-9_]*)\s*\*\)")

_STRUCTURE_MARKER = re.compile(
    r"\(\*\s*@orrery-idiom\s+"
    r"(?P<id>structure\.[a-z][a-z0-9_]*)/v(?P<version>[1-9][0-9]*)\s+"
    r"entries=(?P<entries>[a-z][a-z0-9_]*(?:\s*,\s*[a-z][a-z0-9_]*)*)\s*\*\)")

#: ``(* @ENTRY <name> *)`` — one per independent entry, opening its branch.
_ENTRY = re.compile(r"\(\*\s*@ENTRY\s+(?P<name>[a-z][a-z0-9_]*)\s*\*\)")


@dataclass(frozen=True)
class IdiomMarker:
    """One identity-idiom marker: which method, at which version, on which
    scope."""

    id: str
    version: int
    scope: str

    @property
    def key(self) -> tuple[str, int]:
        return self.id, self.version


@dataclass(frozen=True)
class StructureMarker:
    """One structure-idiom marker: which method, at which version, the entry
    names it declares, and the offset it sits at."""

    id: str
    version: int
    entries: tuple[str, ...]
    start: int

    @property
    def key(self) -> tuple[str, int]:
        return self.id, self.version


def identity_idiom_markers(pv: str) -> list[IdiomMarker]:
    """Every identity-idiom marker in the text, in occurrence order."""
    return [IdiomMarker(m.group("id"), int(m.group("version")), m.group("scope"))
            for m in _MARKER.finditer(pv)]


def structure_idiom_markers(pv: str) -> list[StructureMarker]:
    """Every structure marker, with the offset it sits at — the offset is how
    the check tells which role body the marker belongs to."""
    return [StructureMarker(m.group("id"), int(m.group("version")),
                            tuple(x.strip() for x in m.group("entries").split(",")),
                            m.start())
            for m in _STRUCTURE_MARKER.finditer(pv)]


def entry_markers(pv: str) -> list[tuple[int, int, str]]:
    """``(start, end, name)`` for every ``(* @ENTRY <name> *)`` in the text."""
    return [(m.start(), m.end(), m.group("name")) for m in _ENTRY.finditer(pv)]


def malformed_idiom_marker_lines(pv: str) -> list[str]:
    """Lines that tried to declare an idiom but matched neither grammar.

    An unrecognised ``@orrery-idiom`` line leaves the text looking unmarked, so
    the checks after it would report a missing marker the model can see right
    there in its own file.
    """
    return [line.strip() for line in pv.splitlines()
            if "@orrery-idiom" in line
            and _MARKER.fullmatch(line.strip()) is None
            and _STRUCTURE_MARKER.fullmatch(line.strip()) is None]
