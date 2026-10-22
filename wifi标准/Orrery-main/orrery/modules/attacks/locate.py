"""Which solver file holds the attack behind one false cell.

The solve step's first pass runs with trace reconstruction off, so a goal it
cannot prove comes back ``cannot be proved`` there and is retried alone:
``02_proverif_trace_<goal>`` with reconstruction restored, then, if still
undecided, ``03_proverif_precise_<goal>``. A ``false`` is only ever settled by
one of those two, and the later one is the one that settled it.

A false cell with neither file, or whose file does not say false, means the
run's own record disagrees with itself; that is raised, never worked around.

A weak-secret goal's file declares ``weaksecret`` values instead of queries,
and its verdicts are read the way the solve step reads them
(``goal_verdict``).
"""

from __future__ import annotations

import re
from pathlib import Path

from orrery.infra.proverif.outcome import QueryVerdict, parse_verdicts
from orrery.modules.pvtext.parse import blank_comments
from orrery.modules.verdicts.split import combine, weak_secret_verdict

PRECISE = "03_proverif_precise_{goal}.pv"
TRACE = "02_proverif_trace_{goal}.pv"


_WEAK = re.compile(r"^\s*weaksecret\s", re.M)


class LocateError(RuntimeError):
    """The run's files do not hold the attack its verdict reports."""


def is_weak_secret(source: str) -> bool:
    """Does this goal-only file ask about offline guessing (``weaksecret``)
    rather than ordinary queries?"""
    return bool(_WEAK.search(blank_comments(source)))


def goal_verdict(source: str, verdicts: list[QueryVerdict], goal: str, *,
                 where: str) -> str:
    """``goal``'s verdict among a goal-only file's answers, ``source`` being
    the file's text. The solve step writes that file with ``goal``'s own
    queries and no other (``nodes/solve``), so every answer in it is the
    goal's, whether or not a query still carries the id comment that
    attributed it in the full model — the goal-only copy drops it. Raises
    RuntimeError when there is no answer at all."""
    if is_weak_secret(source):
        return weak_secret_verdict(verdicts, where=where)
    if not verdicts:
        raise RuntimeError(f"[verdicts] {where}: ProVerif produced no verdict")
    # The two answers ProVerif gives without a query: a file of queries that
    # gets one back was not the file that ran.
    stray = [v.query for v in verdicts
             if v.query.strip().lower().startswith("weak secret ")
             or v.query.strip().lower() == "observational equivalence"]
    if stray:
        raise RuntimeError(
            f"[verdicts] {where}: {stray} answer no query of this file, so "
            f"there is no telling which goal they belong to")
    return combine(["unknown" if v.verdict == "cannot_be_proved" else v.verdict
                    for v in verdicts])


def solver_source(families: dict[str, Path], goal: str, *, label: str) -> Path:
    """The goal-only ``.pv`` whose output carries the attack on ``goal``,
    among the current goal-family directories of scenario ``label``
    (``RunLayout.inject_family_dirs``)."""
    hits: list[tuple[str, Path]] = []
    for family, d in sorted(families.items()):
        for pattern in (PRECISE, TRACE):
            f = d / pattern.format(goal=goal)
            if f.is_file():
                hits.append((family, f))
                break
    if not hits:
        raise LocateError(
            f"{label}/{goal} is false but no goal-only solver file exists for "
            f"it ({TRACE.format(goal=goal)} or {PRECISE.format(goal=goal)}); "
            f"a false verdict is only ever settled by one of those")
    if len(hits) > 1:
        raise LocateError(
            f"{label}/{goal} has solver files in more than one goal family: "
            f"{[family for family, _ in hits]}")
    family, source = hits[0]
    where = f"{label}/{family}/{source.with_suffix('.txt').name}"
    output = source.with_suffix(".txt")
    if not output.is_file():
        raise LocateError(f"{where} is missing beside {source.name}")
    try:
        verdict = goal_verdict(
            source.read_text(encoding="utf-8"),
            parse_verdicts(output.read_text(encoding="utf-8")), goal, where=where)
    except RuntimeError as e:
        raise LocateError(str(e)) from None
    if verdict != "false":
        raise LocateError(
            f"{where} answers {verdict} for {goal}, but the scenario's verdict "
            f"is false")
    return source
