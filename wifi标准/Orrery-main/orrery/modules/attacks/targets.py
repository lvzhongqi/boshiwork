"""Which false cells are reproduced, and in what order.

**The gate.** Every false cell enters when the run has no ground truth. With
one, a cell enters only when the comparison reached it and the corpus says
false too: a cell the corpus calls true is most likely a false positive, and a
cell the comparison never reached has nothing to vouch for it.

**The choice.** Up to ``limit`` cells are reproduced on their own; the rest
wait for someone to ask. The ones done first go round the goals — every broken
goal gets one cell before any gets a second, so the first ``limit`` cover as
many goals as they can — and within a goal the scenario that weakens the
fewest assumptions goes first: it is the closest to the protocol failing in
the strongest setting it was asked about. A variable counts as weakened when
another value its declaration offers is stronger than the one assigned, which
is also what makes a channel left at its weakest value count. Ties keep the
results matrix's order.

Everything here is data in, data out: the caller reads the run's files and
hands over the strength comparison of the assumption vocabulary.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field

AUTO, PENDING, SKIPPED = "auto", "pending", "skipped"
#: Why a cell is not reproduced now. Facts, not sentences: the console words them.
GROUND_TRUTH_DIFFERS = "ground_truth_differs"
NOT_COMPARED = "not_compared"
OVER_LIMIT = "over_limit"

Assignment = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Cell:
    goal: str
    label: str
    column: int                 #: the scenario's place in the goal's row
    assignment: Assignment      #: (assumption id, subtype), sorted
    verdict: str


@dataclass
class Target:
    goal: str
    label: str
    decision: str               #: auto | pending | skipped
    reason: str = ""
    expected: str = ""          #: the corpus's verdict, when it was compared
    weakened: list[str] = field(default_factory=list)
    round: int = 0              #: which pass over the goals picked it (1-based)

    def to_json(self) -> dict:
        return asdict(self)


def compared_cells(cross_check: dict) -> dict[tuple[str, frozenset], str]:
    """``cross_check.json`` cells as ``(goal, assignment) → expected``."""
    return {
        (c["id"], frozenset((p["id"], p["subtype"]) for p in c["scenario"])):
            c["expected"]
        for c in cross_check["cells"]
    }


def weakened(assignment: Assignment, variables: dict[str, tuple[str, tuple[str, ...]]],
             compare: Callable[[str, str, str], int]) -> list[str]:
    """``id = subtype`` for every variable assigned a value weaker than
    another its declaration offers. ``variables`` maps a variable's id to its
    axis and declared subtypes; ``compare(axis, a, b)`` is 1 when a is the
    stronger. Fixed assumptions are not in ``variables``: every scenario
    carries them, so they weaken none relative to another."""
    out = []
    for ident, subtype in assignment:
        if ident not in variables:
            continue
        axis, offered = variables[ident]
        if any(compare(axis, other, subtype) > 0 for other in offered):
            out.append(f"{ident} = {subtype}")
    return out


def plan(cells: Iterable[Cell], *, compared: dict | None, limit: int,
         weakened_of: Callable[[Cell], list[str]]) -> list[Target]:
    """A decision for every false cell, in results-matrix order."""
    if limit < 0:
        raise ValueError(f"limit must not be negative, got {limit}")
    false = [c for c in cells if c.verdict == "false"]
    decided: dict[tuple[str, str], Target] = {}
    entering: list[Cell] = []
    for c in false:
        if compared is None:
            entering.append(c)
            continue
        expected = compared.get((c.goal, frozenset(c.assignment)))
        if expected is None:
            decided[(c.goal, c.label)] = Target(
                c.goal, c.label, SKIPPED, NOT_COMPARED, weakened=weakened_of(c))
        elif expected != "false":
            decided[(c.goal, c.label)] = Target(
                c.goal, c.label, SKIPPED, GROUND_TRUTH_DIFFERS, expected=expected,
                weakened=weakened_of(c))
        else:
            entering.append(c)

    rows: dict[str, list[tuple[list[str], Cell]]] = {}
    for c in entering:
        rows.setdefault(c.goal, []).append((weakened_of(c), c))
    for row in rows.values():
        row.sort(key=lambda wc: (len(wc[0]), wc[1].column))
    taken = 0
    depth = max((len(r) for r in rows.values()), default=0)
    for rnd in range(depth):
        for goal, row in rows.items():
            if rnd >= len(row):
                continue
            weak, c = row[rnd]
            expected = "false" if compared is not None else ""
            if taken < limit:
                decided[(c.goal, c.label)] = Target(
                    c.goal, c.label, AUTO, expected=expected, weakened=weak,
                    round=rnd + 1)
                taken += 1
            else:
                decided[(c.goal, c.label)] = Target(
                    c.goal, c.label, PENDING, OVER_LIMIT, expected=expected,
                    weakened=weak, round=rnd + 1)
    return [decided[(c.goal, c.label)] for c in false]
