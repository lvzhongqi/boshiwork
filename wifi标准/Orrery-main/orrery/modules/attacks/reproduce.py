"""Run one goal's solver file again, for the attack graph.

The same file, with ``set traceDisplay = long.`` in front and ``-graph`` on the
command line. The display setting changes only what is printed, so the solver
finds the same trace; under it the dot file carries each session's bindings and
the outcome of every comparison. ``-commandLineGraph true`` keeps ProVerif from
calling graphviz: the dot file is all that is read, and a machine without
graphviz writes it just the same.

A long display can be slow to print on a large model. ``long=False`` asks for
the same graph under the default display, which the file already solved
within: the steps and the sessions are all there, the comparisons are not.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from orrery.infra.proverif.outcome import OutcomeKind, classify
from orrery.infra.proverif.runner import ProVerifRunner
from orrery.modules.attacks.locate import goal_verdict

LONG = "set traceDisplay = long.\n"
DOT = "trace.dot"


class ReproductionError(RuntimeError):
    """The re-run failed in a way only a bug here can cause."""


@dataclass
class Reproduction:
    #: ok | timeout | solver_limit | resource_limit | not_false | no_graph
    status: str
    verdict: str = ""
    dot: Path | None = None
    traces: int = 0             #: how many attack graphs the run drew
    seconds: float = 0.0


async def rerun(runner: ProVerifRunner, source: Path, home: Path, goal: str,
                *, timeout_s: int, long: bool = True) -> Reproduction:
    """Re-run ``source`` into ``home`` (``trace.pv``, ``trace.txt``,
    ``trace.dot``, and ``graph/`` for any further graphs)."""
    home.mkdir(parents=True, exist_ok=True)
    graphs = home / "graph"
    if graphs.exists():
        shutil.rmtree(graphs)
    graphs.mkdir()
    text = source.read_text(encoding="utf-8")
    raw = await runner.run(
        (LONG if long else "") + text, log_to=home / "trace",
        extra_args=("-graph", str(graphs), "-commandLineGraph", "true"),
        timeout_s=timeout_s)
    out = classify(raw)
    seconds = round(raw.duration_s, 1)
    if out.kind is OutcomeKind.SYNTAX_ERROR:
        raise ReproductionError(
            f"re-running {source.name} for its graph gave a syntax error, "
            f"though the file solved before: {out.errors[:3]}")
    if out.kind is not OutcomeKind.OK:
        return Reproduction(out.kind.value, seconds=seconds)
    try:
        verdict = goal_verdict(text, out.verdicts, goal, where=source.name)
    except RuntimeError as e:
        raise ReproductionError(
            f"re-running {source.name} gave answers that cannot be read as "
            f"{goal}'s, though the file solved before: {e}") from None
    if verdict != "false":
        return Reproduction("not_false", verdict=verdict, seconds=seconds)
    dots = sorted(graphs.glob("trace*.dot"),
                  key=lambda p: int(p.stem.removeprefix("trace") or 0))
    if not dots:
        return Reproduction("no_graph", verdict=verdict, seconds=seconds)
    target = home / DOT
    shutil.move(str(dots[0]), target)
    return Reproduction("ok", verdict=verdict, dot=target,
                        traces=len(dots), seconds=seconds)
