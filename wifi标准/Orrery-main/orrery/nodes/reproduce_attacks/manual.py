"""Reproductions a person asks for after the run, and the summary rewritten
over them.

The step reproduces up to ``attacks.auto_cells`` false cells on its own; the
rest wait (``targets.json`` says ``pending``) until someone asks for them in the
console. A cell asked for runs through the same two functions the step uses —
``reproduce_cell`` and ``explain_cell`` — into ``_attacks/<scenario>/<goal>/``
beside the run's own tree (``RunLayout.attack_dir``): evidence made for a
question, not an artifact of the pipeline.

**Which cells can be asked for.** A false cell the step left waiting. A cell
the step reproduced itself is redone by re-running the step, and a cell it left
out (the corpus disagrees, or never compared it) stays out.

**Out of date.** Each reproduction records the solver file it was made from.
When the pipeline redoes a scenario, that cell's current solver file is a
different one, and a reproduction made from the old one no longer says anything
about the run: it is reported ``stale`` and can be asked for again. So can one
that failed, or whose explanation did not get written. Asking again moves the
earlier attempt aside into ``superseded-<k>/`` rather than deleting it.

**Stopped part-way.** A cell whose work is stopped goes back to waiting, so
what it had written is set aside the same way: a reproduction without its
explanation would otherwise read as done.

**Language.** The explanations follow the run's own ``prompt_lang``, not the
console's, so one run's panel reads in one language.

**The summary.** Rewritten on request over every reproduced cell whose
explanation stands — the step's and the ones asked for — into
``_attacks/summary/``. The console shows whichever summary is newer, the
step's or this one.
"""

from __future__ import annotations

import json
from pathlib import Path

from orrery.infra.proverif.runner import ProVerifRunner
from orrery.modules.attacks.locate import LocateError, solver_source
from orrery.modules.attacks.targets import AUTO, PENDING
from orrery.nodes.reproduce_attacks.explain import (
    EXPLANATION, NODE, SUMMARY, explain_cell, summarize,
)
from orrery.nodes.reproduce_attacks.node import (
    ATTACKS, REPRODUCTION, TARGETS, budgets, read_cells, reproduce_cell,
)
from orrery.services.store.atomic import write_json
from orrery.services.store.layout import RunLayout

#: Where the summary asked for after the run lives, under ``_attacks/``.
SUMMARY_DIR = "summary"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def targets(layout: RunLayout) -> dict[tuple[str, str], dict]:
    """The step's decision for every false cell, by ``(scenario, goal)``;
    empty when the step has not decided anything."""
    home = layout.find_node_dir(NODE)
    if home is None or not (home / TARGETS).is_file():
        return {}
    return {(t["label"], t["goal"]): t
            for t in _read(home / TARGETS)["targets"]}


def is_stale(layout: RunLayout, outcome: dict) -> bool:
    """Was this reproduction made from a solver file the run no longer
    stands on?"""
    label, goal = outcome["label"], outcome["goal"]
    try:
        now = solver_source(layout.inject_family_dirs(label), goal, label=label)
    except LocateError:
        return True
    return layout.rel(now) != outcome["source"]


def manual_outcome(layout: RunLayout, label: str, goal: str) -> dict | None:
    """The reproduction asked for on one cell, with ``manual``, ``stale`` and
    the explanation's path when there is one; None when nobody asked."""
    home = layout.attack_dir(label, goal, manual=True)
    if not (home / REPRODUCTION).is_file():
        return None
    out = {**_read(home / REPRODUCTION), "manual": True}
    out["stale"] = is_stale(layout, out)
    if (home / EXPLANATION).is_file():
        out["explanation"] = layout.rel(home / EXPLANATION)
    return out


def refusal(layout: RunLayout, label: str, goal: str) -> str | None:
    """Why this cell cannot be asked for, or None when it can."""
    target = targets(layout).get((label, goal))
    if target is None:
        return "not a false cell of this run's attack step"
    if target["decision"] == AUTO:
        return ("the attack step reproduces this cell itself; re-run the step "
                "to redo it")
    if target["decision"] != PENDING:
        return f"left out by the attack step ({target['reason']})"
    done = manual_outcome(layout, label, goal)
    if (done is not None and not done["stale"] and done["status"] == "ok"
            and "explanation" in done):
        return "already reproduced"
    return None


def set_aside(layout: RunLayout, label: str, goal: str) -> None:
    """Move an earlier attempt at one asked-for cell into
    ``superseded-<k>/``, leaving the cell with nothing reproduced: before it is
    asked for again, and when its attempt was stopped part-way."""
    home = layout.attack_dir(label, goal, manual=True)
    if not home.is_dir():
        return
    old = [p for p in home.iterdir() if not p.name.startswith("superseded-")]
    if not old:
        return
    k = 1
    while (home / f"superseded-{k}").exists():
        k += 1
    aside = home / f"superseded-{k}"
    aside.mkdir()
    for p in old:
        p.rename(aside / p.name)


async def reproduce_asked(env, runner: ProVerifRunner, *, label: str,
                          goal: str, emit) -> dict:
    """Reproduce and explain one cell somebody asked for. Raises NodeError
    for a cell the run's files cannot account for, like the step does; a
    failed explanation is recorded on the cell and does not raise."""
    layout = env.layout
    home = layout.attack_dir(label, goal, manual=True)
    set_aside(layout, label, goal)
    outcome = await reproduce_cell(
        layout, runner, label=label, goal=goal,
        **budgets(env.config), manual=True, emit=emit)
    if outcome["status"] != "ok":
        return outcome
    _, _, context = read_cells(layout)
    try:
        await explain_cell(
            env, home=home, scenario=label, goal=goal,
            assumptions=context["assumptions"][label],
            goal_text=context["goals"][goal], replay=outcome["replay"])
    except Exception as e:                            # noqa: BLE001
        outcome["explain_error"] = f"{type(e).__name__}: {e}"
        write_json(home / REPRODUCTION, outcome)
    return outcome


def summary_input(layout: RunLayout) -> tuple[list[tuple[str, dict]], int]:
    """What a rewritten summary covers: every reproduced cell whose
    explanation stands, as ``(scenario/goal, explanation)`` in the step's own
    order, and how many false cells still wait."""
    home = layout.find_node_dir(NODE)
    step = {}
    if home is not None and (home / ATTACKS).is_file():
        step = {(c["label"], c["goal"]): c for c in _read(home / ATTACKS)["cells"]}
    cells, waiting = [], 0
    for (label, goal), target in targets(layout).items():
        done = None
        if target["decision"] == AUTO:
            row = step.get((label, goal), {})
            if row.get("status") == "ok" and row.get("explanation"):
                done = layout.run_dir / row["explanation"]
        elif target["decision"] == PENDING:
            m = manual_outcome(layout, label, goal)
            if m is not None and not m["stale"] and m.get("explanation"):
                done = layout.run_dir / m["explanation"]
            else:
                waiting += 1
        if done is not None:
            cells.append((f"{label}/{goal}", _read(done)))
    return cells, waiting


async def resummarize(env) -> dict:
    """Rewrite the summary over every reproduced cell into
    ``_attacks/summary/``. Raises ValueError when nothing is explained."""
    cells, waiting = summary_input(env.layout)
    if not cells:
        raise ValueError("no reproduced cell has an explanation to summarise")
    home = env.layout.run_dir / env.layout.MANUAL_ATTACKS / SUMMARY_DIR
    return await summarize(env, home=home, cells=cells, pending=waiting)


def manual_summary(layout: RunLayout) -> Path | None:
    """The summary asked for after the run, if there is one."""
    p = layout.run_dir / layout.MANUAL_ATTACKS / SUMMARY_DIR / SUMMARY
    return p if p.is_file() else None
