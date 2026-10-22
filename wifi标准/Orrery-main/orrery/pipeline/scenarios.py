"""Scenario-stage orchestration: assignment expansion (pure code) plus the
concurrent apply → inject → solve scheduling, once per scenario.

Every scenario starts from the run's root model (flow plus every fixed
assumption, written by build_root) and applies only its own conditions on top.
A condition may only assign a variable dimension, which the claims gate
guarantees, so no scenario can rewrite what the root model carries.

The stage is one node table row that runs N times internally, and re-entry is
at the whole stage: a scenario with a verdict is skipped, a finished apply
point is reused off applied.pv when the chain's numbering says it is still
current (services/store/stages), and a finished inject cell is frozen off its
model.pv.
"""

from __future__ import annotations

from orrery.infra.proverif.runner import ProVerifRunner
from orrery.modules.libschema.io import (
    load_assumptions, load_claims, load_properties,
)
from orrery.modules.libschema.resolve import expand_assignments
from orrery.nodes.apply.node import apply_scenario
from orrery.nodes.apply.order import (
    apply_order, fixed_points,
)
from orrery.nodes.apply.realizers import subtype_is_noop
from orrery.nodes.root.node import ROOT_IDENT
from orrery.nodes.base import Node, NodeError, RunEnv
from orrery.nodes.inject.injectors import injector_for
from orrery.nodes.inject.node import grid_subtype, inject_family
from orrery.nodes.solve.node import solve_grid
from orrery.services.concurrency import at, run_all, run_capped
from orrery.services.events import (
    NodeProgress, ScenarioFinished, ScenarioStarted,
)
from orrery.services.store.layout import unit_name
from orrery.services.store.atomic import write_json
from orrery.services.transcript.writer import TranscriptWriter  # noqa: F401


def goals_by_grid(properties, claims) -> dict[tuple[str, str], list]:
    """Group the goals the claims name into (type, subtype) cells. A vocabulary
    goal that no claim names never enters a cell."""
    grids: dict[tuple[str, str], list] = {}
    for c in claims.claims:
        g = properties.by_id(c.property)
        grids.setdefault((g.type, grid_subtype(g)), []).append(g)
    return grids


def assignment_rows(points, fixed_ids: set, condition_ids: set) -> list[dict]:
    """One assignment → ledger rows: each dimension, the value it takes, and
    where that value came from (a fixed assumption, this scenario's own
    condition, or the flow default for a dimension nobody mentioned). Sorted by
    id so two scenarios read against each other."""
    rows = []
    for p in sorted(points, key=lambda p: (p.ref_id or p.axis, p.subtype)):
        src = ("fixed" if p.ref_id in fixed_ids else
               "condition" if p.ref_id in condition_ids else "default")
        rows.append({"id": p.ref_id, "axis": p.axis, "subtype": p.subtype,
                     "target": p.target, "from": src})
    return rows


def batch_name(cells: list[tuple[str, str, list]]) -> str:
    """What a batch is called, as both its directory and its display label.

    A batch of non-perturbing subtypes is named for the goal type they share; a
    perturbing subtype is alone in its batch and is named ``<type>.<subtype>``.
    Raises ValueError if the cells span more than one goal type."""
    gtypes = {gt for gt, _, _ in cells}
    if len(gtypes) != 1:
        raise ValueError(f"a batch spans more than one goal type: {sorted(gtypes)}")
    gt = gtypes.pop()
    return gt if len(cells) > 1 or not injector_for(*cells[0][:2]).perturbs_model \
        else f"{gt}.{cells[0][1]}"


def family_batches(cells: list[tuple[str, str, list]], cap: int
                   ) -> list[tuple[str, int | None, list[tuple[str, str, list]]]]:
    """Group one scenario's cells into inject batches; one batch is one session
    and one .pv file.

    What decides sharing is ``perturbs_model``: subtypes that only add queries
    batch together under their goal type, so their verdicts compare inside one
    model, while a subtype that changes the model gets a batch of its own.
    Batches are split further at ``cap`` cells, a request-size limit. Cells are
    sorted by (type, subtype), so the grouping is deterministic. Returns
    [(name, chunk, cells)] with chunk None unless the batch was split.
    """
    groups: dict[tuple[str, str], list] = {}
    expanded = []
    for gt, st, goals in cells:
        inj = injector_for(gt, st)
        if inj.one_goal_per_file:
            expanded.extend((gt, st, [goal]) for goal in goals)
        else:
            expanded.append((gt, st, goals))
    for cell in sorted(expanded, key=lambda c: (
            c[0], c[1], getattr(c[2][0], "id", str(c[2][0])))):
        gt, st, _ = cell
        inj = injector_for(gt, st)
        if inj.one_goal_per_file:
            goal = cell[2][0]
            groups[(gt, f"{st}.{goal.id}")] = [cell]
            continue
        # A perturbing subtype keys on itself, so nothing can join it.
        key = (gt, st) if inj.perturbs_model else (gt, "")
        groups.setdefault(key, []).append(cell)
    batches = []
    for key in sorted(groups):
        members = groups[key]
        chunks = [members[i:i + cap] for i in range(0, len(members), cap)]
        for n, ch in enumerate(chunks, start=1):
            name = (f"{key[0]}.{key[1]}" if "." in key[1]
                    else batch_name(ch))
            batches.append((name,
                            None if len(chunks) == 1 else n, ch))
    return batches


def _finished(env: RunEnv, name: str) -> bool:
    """Has this scenario answered, in whichever directory currently holds it?
    Tolerant of a scenario with no directory yet, which is the ordinary state
    of every one of them before the stage runs."""
    d = env.layout.find_scenario_dir(name)
    return d is not None and (d / "verdict.json").exists()


class ScenariosNode(Node):
    """The scenario stage as one table row: for each named scenario, apply its
    conditions on the root model, inject the goals it was claimed under, and
    solve. Scenarios run concurrently under a configured cap."""
    needs_solver = True

    name = "scenarios"
    short = "scenarios"
    task = (
        "Scenario stage: per scenario, apply its own conditions on the root "
        "model, inject the goals, and run ProVerif")
    model_driven = True

    def _claims(self, env: RunEnv):
        d = env.layout.node_dir("extract_claims")
        assumptions = load_assumptions(d / "assumptions.json")
        properties = load_properties(d / "properties.json")
        claims = load_claims(d / "claims.json", assumptions)
        return assumptions, properties, claims

    def is_done(self, env: RunEnv) -> bool:
        try:
            assumptions, _, claims = self._claims(env)
        except FileNotFoundError:
            return False
        assignments, _ = expand_assignments(claims, assumptions, subtype_is_noop)
        return all(_finished(env, name) for name, _ in assignments)

    # The chain a reader follows per scenario: scenario model → cell models →
    # verdict. Round files and transcripts stay off the ledger line.
    _CANONICAL = ("scenario.pv", "notes.md", "model.pv", "verdict.json")

    def artifacts(self, env: RunEnv) -> list[str]:
        root = env.layout.find_node_dir(self.name)
        if root is None:
            return []
        return sorted(str(p.relative_to(root)) for p in root.rglob("*")
                      if p.is_file() and p.name in self._CANONICAL)

    async def run(self, env: RunEnv) -> None:
        assumptions, properties, claims = self._claims(env)
        root = env.layout.root_pv
        if not root.exists():
            raise NodeError(
                "scenarios failed: the upstream root model does not exist "
                "(build_root writes it; re-enter at that step)")
        root_pv = root.read_text(encoding="utf-8")
        pv_cfg = env.config["proverif"]
        runner = ProVerifRunner(executable=pv_cfg["executable"],
                                timeout_s=pv_cfg["timeout_s"])
        grids = goals_by_grid(properties, claims)
        assignments, alias = expand_assignments(claims, assumptions, subtype_is_noop)
        # goal → canonical names of the scenarios it is asserted under, which
        # decides the cells each scenario has to verify
        named = {c.property: {alias[n] for n in c.scenarios}
                 for c in claims.claims}

        # The fixed layer is already inside root_pv; all that is needed here is
        # the record of which points it carries, so a scenario's notes can name
        # them without applying them again.
        all_fixed = fixed_points(assumptions)
        fixed_live = apply_order(
            [p for p in all_fixed if not subtype_is_noop(p.axis, p.subtype)])
        shared_keys = frozenset(p._key() for p in fixed_live)
        # Where each assignment's values come from, for the ledger's rows.
        fixed_ids = {p.ref_id for p in all_fixed}
        cond_ids = {ns.name: {p.ref_id for p in ns.conditions}
                    for ns in claims.scenarios}

        async def one(name: str, assignment) -> None:
            # Which directory this scenario's work goes to, by the same rule
            # the runner applies one level up: a finished scenario nobody is
            # re-working is skipped, one that is unfinished or is itself the
            # target carries on in the directory it has (keeping the apply
            # points it already finished), and anything else opens a new
            # generation.
            prev = env.layout.find_scenario_dir(name)
            what = env.plan(f"{self.name}/{name}", prev,
                            prev is not None and (prev / "verdict.json").exists())
            if what == "skip":
                return                                # still the answer
            where = prev if what == "carry" else env.layout.open_scenario(name)
            if env.bus is not None:
                env.bus.emit(NodeProgress(
                    run=env.layout.run_name, node=self.name, scenario=name,
                    text=f"scenario {name}: {where.name}"))
                env.bus.emit(ScenarioStarted(
                    run=env.layout.run_name, node=self.name, scenario=name,
                    assignment=assignment_rows(assignment.points, fixed_ids,
                                     cond_ids.get(name, set()))))
            pv = await apply_scenario(
                env, name, apply_order(assignment.points), runner,
                root_pv, shared_keys=shared_keys,
                base_label=ROOT_IDENT if fixed_live else None)
            # the cells to verify are the goals claimed under this scenario
            verdicts: dict[str, str] = {}
            notes: dict[str, str] = {}
            cells = [(gt, st, mine) for (gt, st), gs in grids.items()
                     if (mine := [g for g in gs if name in named[g.id]])]
            batches = family_batches(
                cells, cap=env.config["scenarios"]["inject_cells_per_call"])

            async def one_batch(family: str, chunk: int | None,
                                batch_cells) -> None:
                # A chunk of a family the per-call cap split is a family
                # directory of its own: its own session, model.pv and solver
                # logs. Two chunks under one directory wrote the same
                # model.pv, and on re-entry one chunk's goals were read off
                # the other's file.
                family = family if chunk is None else f"{family}_c{chunk}"
                model_pv = await inject_family(env, name, pv, family,
                                               batch_cells, runner)
                # One batch is one file, so one solve. Ordinary queries carry
                # goal ids and split_by_goal attributes them by naming anchor.
                # ProVerif's observational-equivalence and weaksecret verdicts
                # carry no goal id, so their injectors give each goal a file of
                # its own and the owner named below attributes the verdict.
                goals = [g for _, _, gs in batch_cells for g in gs]
                equivalence_goal = (
                    goals[0].id if len(goals) == 1
                    and goals[0].type == "Privacy"
                    and goals[0].subtype == "unlinkability" else None)
                weaksecret_goal = (
                    goals[0].id if len(goals) == 1
                    and goals[0].type == "Secrecy"
                    and goals[0].subtype
                    == "weak_secret_guessing_resistance" else None)
                vs, note = await solve_grid(
                    runner, model_pv, [g.id for g in goals],
                    name=f"{name}_{family}",
                    cell_dir=env.layout.inject_family_dir(name, family),
                    trace_retry_timeout_s=env.config["solve"]["trace_retry_timeout_s"],
                    precise_retry=env.config["solve"]["precise_actions_retry"],
                    precise_retry_timeout_s=env.config["solve"]["precise_retry_timeout_s"],
                    vacuity_check=env.config["solve"]["vacuity_check"],
                    vacuity_timeout_s=env.config["solve"]["vacuity_timeout_s"],
                    cell=family,
                    equivalence_goal=equivalence_goal,
                    weaksecret_goal=weaksecret_goal,
                    emit=env.emitter(
                        "solve", scenario=name,
                        unit=unit_name(env.layout.scenario_dir(name),
                                       env.layout.inject_family_dir(name, family))))
                verdicts.update(vs)
                notes[family] = note

            await run_all(
                [(lambda f=f, ck=ck, bc=bc: at(
                    f"{self.name}/{name}/inject/{f}", one_batch(f, ck, bc)))
                 for f, ck, bc in batches])
            write_json(env.layout.scenario_verdict(name),
                       {"verdicts": verdicts, "solver_notes": notes})
            if env.bus is not None:
                env.bus.emit(ScenarioFinished(
                    run=env.layout.run_name, node=self.name, scenario=name,
                    verdicts=dict(verdicts)))
                done = sum(1 for n, _ in assignments if _finished(env, n))
                env.bus.emit(NodeProgress(
                    run=env.layout.run_name, node=self.name,
                    text=f"scenario {done}/{len(assignments)} done ({name})"))

        await run_capped([(lambda n=n, w=w: at(f"{self.name}/{n}", one(n, w)))
                          for n, w in assignments],
                         limit=env.config["pipeline"][
                             "max_scenarios_concurrency"])
