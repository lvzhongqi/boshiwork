"""Node 13, reproduce_attacks: replay the attack behind each false cell as a
step-by-step script a person can watch.

A false verdict already comes with a concrete execution — ProVerif
reconstructed one before it said false — so nothing here re-decides anything.
The step finds the goal-only solver file that answered, runs it once more for
its attack graph, and turns the graph into lanes and steps
(``modules/attacks``). Its products are for reading: no verdict changes, no
model is rewritten, no fix is proposed; fixing stays with the expert.

**Which cells.** Every false cell when the run has no ground truth. With one,
only the cells the comparison reached and the corpus also calls false: a cell
the corpus calls true is most likely a false positive, and one the comparison
never reached has nothing to vouch for it. Past ``attacks.auto_cells`` the
step goes round the broken goals first, and the cells left over wait for
someone to ask for them in the console (``modules/attacks/targets``).

**Why after a failed check too** (``runs_after_check_failure``): a run whose
comparison disagreed somewhere still has cells that agreed, and those are the
attacks worth showing.

**The explanations** (``explain``). Each reproduced cell gets one session
that writes an opening, a note per step and a conclusion; then one session
groups the conclusions by the problem behind them. The script is written before
its explanation, so a cell whose explanation failed can still be watched.

**What is written.** ``targets.json``, every false cell and what was decided
for it; per reproduced cell, ``<scenario>/<goal>/`` with the re-run
(``trace.pv``, ``trace.txt``, ``trace.dot``), its outcome
(``reproduction.json``), the script (``msc.json``) and the explanation
(``explanation.json``); ``summary/summary.json``; and ``attacks.json``, which
the console reads. ``attacks.json`` is written even when an explanation failed,
marked incomplete, so the console shows what exists; ``is_done`` asks for it
complete. A carried-on step reads back every file already there.

**What fails the step.** A cell the run's own files cannot account for — no
goal-only solver file behind a false verdict, a file that does not say false,
a syntax error on a file that solved before — is a bug and raised at once. A
session that ends without an explanation fails the step too, once every other
cell has had its turn. Everything else is an outcome recorded on its cell: a
re-run out of time falls back to the default display, a graph this reader
cannot read is named, and the other cells go on. A weak-secret cell is
reproduced like any other: its graph is the messages the attacker collects,
closed by the offline test on a guess (``modules/attacks/script``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from orrery.infra.llm.client import Effort
from orrery.infra.proverif.runner import ProVerifRunner
from orrery.modules.attacks.graph import GraphError, read
from orrery.modules.attacks.locate import (
    LocateError, solver_source,
)
from orrery.modules.attacks.reproduce import ReproductionError, rerun
from orrery.modules.attacks.script import ScriptError, build
from orrery.modules.attacks.targets import (
    AUTO, Cell, compared_cells, plan, weakened,
)
from orrery.modules.libschema.io import (
    load_assumptions, load_claims, load_properties,
)
from orrery.modules.libschema.resolve import expand_assignments
from orrery.nodes.apply.realizers import VOCAB, subtype_is_noop
from orrery.nodes.base import Node, NodeError, RunEnv
from orrery.nodes.inject.injectors import INJECTORS
from orrery.nodes.inject.node import grid_subtype
from orrery.nodes.reproduce_attacks.explain import (
    EFFORT, explain_cell, summarize,
)
from orrery.services.concurrency import at, run_capped
from orrery.services.events import AttackStatus, NodeProgress
from orrery.services.store.atomic import write_json
from orrery.services.store.layout import RunLayout

TARGETS = "targets.json"
ATTACKS = "attacks.json"
SCRIPT = "msc.json"
REPRODUCTION = "reproduction.json"
#: The solver said nothing within its budget: worth one more try without the
#: long display, which is the part that grows with the model.
_NO_ANSWER = ("timeout", "solver_limit", "resource_limit")
_BUT = re.compile(r"^RESULT \(but .* is true\.\)\s*$", re.M)
class ReproduceAttacksNode(Node):
    name = "reproduce_attacks"
    short = "attacks"
    task = ("Replay the attack behind each false verdict as a step-by-step "
            "script")
    model_driven = True
    runs_after_check_failure = True
    needs_solver = True
    depends_on = ("scenarios", "cross_check")
    # Explaining a script already built is reading, not construction.
    effort: Effort = EFFORT

    def is_done(self, env: RunEnv) -> bool:
        if not env.layout.has(self.name, ATTACKS):
            return False
        doc = json.loads((env.layout.node_dir(self.name) / ATTACKS)
                         .read_text(encoding="utf-8"))
        return bool(doc.get("complete"))

    def artifacts(self, env: RunEnv) -> list[str]:
        d = env.layout.find_node_dir(self.name)
        if d is None:
            return []
        return [n for n in (TARGETS, ATTACKS) if (d / n).exists()]

    async def run(self, env: RunEnv) -> None:
        layout = env.layout
        out = layout.node_dir(self.name)
        cfg = env.config["attacks"]
        if not cfg["enabled"]:
            _say(env, self.name, "attack replay is off (attacks.enabled); "
                                 "nothing to do")
            write_json(out / ATTACKS, {"enabled": False, "complete": True,
                                       "cells": []})
            return

        cells, variables, context = read_cells(layout)
        compared = None
        if env.ground_truth is not None:
            if not layout.cross_check_json.is_file():
                raise NodeError(
                    "reproduce_attacks: the run has a ground truth but no "
                    "cross_check.json, so it cannot tell which false cells the "
                    "corpus agrees with")
            compared = compared_cells(
                json.loads(layout.cross_check_json.read_text(encoding="utf-8")))

        def weak(cell: Cell) -> list[str]:
            return weakened(cell.assignment, variables, VOCAB.compare)

        targets = plan(cells, compared=compared, limit=cfg["auto_cells"],
                       weakened_of=weak)
        write_json(out / TARGETS, {
            "limit": cfg["auto_cells"], "ground_truth": compared is not None,
            "targets": [t.to_json() for t in targets]})
        auto = [t for t in targets if t.decision == AUTO]
        pending = sum(1 for t in targets if t.decision == "pending")
        _say(env, self.name, _counts(targets))
        if not auto:
            write_json(out / ATTACKS, _attacks_doc(targets, {}, compared))
            return

        runner = make_runner(env.config)
        emit = env.emitter(self.name)
        outcomes: dict[tuple[str, str], dict] = {}

        async def one(t) -> None:
            outcomes[(t.label, t.goal)] = await reproduce_cell(
                layout, runner, label=t.label, goal=t.goal,
                **budgets(env.config), manual=False, emit=emit)

        limit = env.config["pipeline"]["max_scenarios_concurrency"]
        await run_capped(
            [(lambda t=t: at(f"{self.name}/{t.label}/{t.goal}", one(t)))
             for t in auto],
            limit=limit)

        failures: list[str] = []
        explained: dict[tuple[str, str], dict] = {}

        async def tell(t) -> None:
            o = outcomes[(t.label, t.goal)]
            if o["status"] != "ok":
                return
            _say(env, self.name, f"explaining {t.label}/{t.goal}")
            try:
                explained[(t.label, t.goal)] = await explain_cell(
                    env, home=layout.run_dir / o["home"], scenario=t.label,
                    goal=t.goal, assumptions=context["assumptions"][t.label],
                    goal_text=context["goals"][t.goal], replay=o["replay"])
                o["explanation"] = f"{o['home']}/explanation.json"
            except Exception as e:                    # noqa: BLE001
                o["explain_error"] = f"{type(e).__name__}: {e}"
                failures.append(f"{t.label}/{t.goal}: {o['explain_error']}")

        await run_capped(
            [(lambda t=t: at(f"{self.name}/{t.label}/{t.goal}/explain", tell(t)))
             for t in auto],
            limit=limit)

        doc = _attacks_doc(targets, outcomes, compared)
        ordered = [(f"{t.label}/{t.goal}", explained[(t.label, t.goal)])
                   for t in auto if (t.label, t.goal) in explained]
        if ordered:
            _say(env, self.name, f"summarising {len(ordered)} explained cell(s)")
            try:
                await summarize(env, home=out / "summary", cells=ordered,
                                pending=pending)
                doc["summary"] = layout.rel(out / "summary" / "summary.json")
            except Exception as e:                    # noqa: BLE001
                failures.append(f"summary: {type(e).__name__}: {e}")
        doc["complete"] = not failures
        write_json(out / ATTACKS, doc)
        if failures:
            raise NodeError(
                f"reproduce_attacks: {len(failures)} explanation(s) failed; "
                f"the scripts are written and can be watched. "
                + " | ".join(failures))


def make_runner(config: dict) -> ProVerifRunner:
    """The solver the step re-runs cells with, from the run's configuration."""
    pv = config["proverif"]
    return ProVerifRunner(executable=pv["executable"], timeout_s=pv["timeout_s"])


def budgets(config: dict) -> dict[str, int]:
    """The two re-runs' time budgets: the long display prints far more, so it
    has its own and a larger one; the default display falls back to the
    solve step's own budget for a goal-only file."""
    return {"long_timeout_s": config["attacks"]["long_timeout_s"],
            "timeout_s": config["solve"]["trace_retry_timeout_s"]}


async def reproduce_cell(layout: RunLayout, runner: ProVerifRunner, *,
                         label: str, goal: str, long_timeout_s: int,
                         timeout_s: int, manual: bool, emit) -> dict:
    """Reproduce one false cell into its directory and return its outcome.
    Shared by the step and by a reproduction asked for after the run.

    Raises NodeError for a cell the run's own files cannot account for."""
    def say(status: str, reason: str = "") -> None:
        if emit is not None:
            emit(AttackStatus(run="", goal=goal, label=label, status=status,
                              reason=reason, manual=manual))

    home = layout.attack_dir(label, goal, manual=manual)
    done = home / REPRODUCTION
    if done.is_file():
        outcome = json.loads(done.read_text(encoding="utf-8"))
        say(outcome["status"], outcome.get("reason", ""))
        return outcome
    say("running")
    try:
        source = solver_source(layout.inject_family_dirs(label), goal,
                               label=label)
        rep = await rerun(runner, source, home, goal, timeout_s=long_timeout_s)
        display = "long"
        if rep.status in _NO_ANSWER:
            rep = await rerun(runner, source, home, goal, timeout_s=timeout_s,
                              long=False)
            display = "default"
    except (LocateError, ReproductionError) as e:
        say("failed", str(e))
        raise NodeError(f"reproduce_attacks: {label}/{goal}: {e}") from None
    outcome = {
        "goal": goal, "label": label,
        "source": layout.rel(source), "home": layout.rel(home),
        "display": display, "seconds": rep.seconds, "traces": rep.traces,
        "replay": bool(_BUT.search(
            source.with_suffix(".txt").read_text(encoding="utf-8"))),
    }
    if rep.status != "ok":
        reason = (f"the re-run answered {rep.verdict}" if rep.status == "not_false"
                  else f"the re-run ended {rep.status}")
        outcome.update(status="failed", reason=reason)
    else:
        try:
            script = build(read(rep.dot), goal=goal,
                           model=source.read_text(encoding="utf-8"))
        except (GraphError, ScriptError) as e:
            outcome.update(status="failed",
                           reason=f"the attack graph could not be read: {e}")
        else:
            write_json(home / SCRIPT, script.to_json())
            outcome.update(status="ok", script=layout.rel(home / SCRIPT),
                           steps=len(script.steps))
    write_json(done, outcome)
    say(outcome["status"], outcome.get("reason", ""))
    return outcome


def read_cells(layout: RunLayout):
    """Every (goal, scenario) the claims ask about, with its assignment and its
    verdict, in the results matrix's order; the variable assumptions as
    ``id → (axis, subtypes)``; and the texts an explanation is given: each
    scenario's assumptions and each goal, by name."""
    d = layout.node_dir("extract_claims")
    assumptions = load_assumptions(d / "assumptions.json")
    claims = load_claims(d / "claims.json", assumptions)
    properties = load_properties(d / "properties.json")
    worlds, alias = expand_assignments(claims, assumptions, subtype_is_noop)
    world_by_name = dict(worlds)
    verdicts: dict[str, dict] = {}
    cells: list[Cell] = []
    for c in claims.claims:
        seen: set[str] = set()
        for ref in c.scenarios:
            name = alias[ref]
            if name in seen:
                continue
            seen.add(name)
            if name not in verdicts:
                path = layout.scenario_verdict(name)
                if not path.is_file():
                    raise NodeError(f"reproduce_attacks: scenario {name} has "
                                    f"no verdict.json")
                verdicts[name] = json.loads(path.read_text(encoding="utf-8"))["verdicts"]
            if c.property not in verdicts[name]:
                raise NodeError(f"reproduce_attacks: {c.property} has no "
                                f"verdict in scenario {name}")
            cells.append(Cell(
                c.property, name, len(seen) - 1,
                tuple(sorted((p.ref_id, p.subtype)
                             for p in world_by_name[name].points)),
                verdicts[name][c.property]))
    variables = {a.id: (a.axis, tuple(a.subtypes)) for a in assumptions.variable}
    fixed = {a.id for a in assumptions.fixed}
    context = {
        "assumptions": {name: _assumptions_text(world, fixed, variables)
                        for name, world in world_by_name.items()},
        "goals": {g.id: _goal_text(g) for g in properties.properties},
    }
    return cells, variables, context


def _target(target) -> str:
    if not target:
        return ""
    if isinstance(target, dict):
        return ", ".join(f"{k} {v}" for k, v in target.items())
    return str(target)


def _assumptions_text(world, fixed: set[str], variables: dict) -> str:
    """One line per assumption in force: its value, what the value means,
    and whether this scenario chose it or every scenario has it."""
    lines = []
    for p in world.points:
        kind = ("fixed in every scenario" if p.ref_id in fixed else
                "chosen by this scenario" if p.ref_id in variables else
                "the default")
        on = _target(p.target)
        lines.append(f"- {p.ref_id} = {p.subtype} ({p.axis}"
                     + (f", {on}" if on else "") + f"; {kind}): "
                     + VOCAB.description(p.axis, p.subtype))
    return "\n".join(lines) or "- none"


def _goal_text(goal) -> str:
    sub = grid_subtype(goal)
    meaning = INJECTORS[(goal.type, sub)].description
    values = ", ".join(str(v) for v in goal.values)
    return (f"{goal.id} ({goal.type}.{sub})"
            + (f" about {values}" if values else "") + f": {meaning}")


def _attacks_doc(targets, outcomes: dict, compared) -> dict:
    return {
        "enabled": True,
        "complete": True,
        "ground_truth": compared is not None,
        "cells": [{**t.to_json(), **outcomes.get((t.label, t.goal), {})}
                  for t in targets],
    }


def _counts(targets) -> str:
    by = {}
    for t in targets:
        by[t.decision] = by.get(t.decision, 0) + 1
    if not targets:
        return "no false verdict; nothing to replay"
    return (f"{len(targets)} false cell(s): {by.get('auto', 0)} to replay now, "
            f"{by.get('pending', 0)} waiting to be asked for, "
            f"{by.get('skipped', 0)} left out")


def _say(env: RunEnv, node: str, text: str) -> None:
    if env.bus is not None:
        env.bus.emit(NodeProgress(run=env.layout.run_name, node=node, text=text))
