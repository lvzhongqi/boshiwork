"""Node 9, aggregate: pure code, run once globally.

Gathers every scenario's verdict.json into two artifacts:
- cases_results.json: one row per claim, holding each scenario's complete
  assignment (fixed ∪ conditions ∪ flow-state defaults) and its verdict, in
  the encoding the corpus uses, so cross_check compares key by key.
- results.json: one answer per goal by conjunction — true only when true in
  every scenario; otherwise false, vacuous, no-answer or unknown wins in that
  order and names the scenarios responsible.

Scenarios sharing a world are deduplicated first. A claimed scenario with no
verdict.json, or one whose verdicts omit the goal, raises NodeError.
"""

from __future__ import annotations

import json

from orrery.modules.libschema.io import load_assumptions, load_claims
from orrery.modules.libschema.model import NO_ANSWER, VACUOUS
from orrery.modules.libschema.resolve import expand_assignments
from orrery.version import VOCAB_VERSION
from orrery.nodes.apply.realizers import subtype_is_noop
from orrery.nodes.base import Node, NodeError, RunEnv
from orrery.services.events import Aggregated
from orrery.services.store.atomic import write_json


class AggregateNode(Node):
    name = "aggregate"
    short = "aggregate"
    task = (
        "Combine the per-scenario verdicts by conjunction into one answer per "
        "goal")

    def is_done(self, env: RunEnv) -> bool:
        return env.layout.has(self.name, "results.json")

    def artifacts(self, env: RunEnv) -> list[str]:
        d = env.layout.find_node_dir(self.name)
        if d is None:
            return []
        return [p.name for p in (env.layout.cases_results_json,
                                 env.layout.results_json) if p.exists()]

    async def run(self, env: RunEnv) -> None:
        d = env.layout.node_dir("extract_claims")
        assumptions = load_assumptions(d / "assumptions.json")
        claims = load_claims(d / "claims.json", assumptions)

        worlds, alias = expand_assignments(claims, assumptions, subtype_is_noop)
        world_by_name = dict(worlds)
        by_name: dict[str, dict] = {}
        for name, _world in worlds:
            d = env.layout.find_scenario_dir(name)
            p = d / "verdict.json" if d is not None else None
            if p is None or not p.exists():
                raise NodeError(f"aggregate failed: scenario {name} has no verdict.json")
            by_name[name] = json.loads(p.read_text(encoding="utf-8"))

        cases, results = [], []
        for c in claims.claims:
            by_scenario, verdicts = [], []
            # Two names with the same conditions are one world; deduplicating
            # keeps the conjunction from counting a cell twice.
            seen: set[str] = set()
            for ref in c.scenarios:
                name = alias[ref]
                if name in seen:
                    continue
                seen.add(name)
                v = by_name[name]["verdicts"].get(c.property)
                if v is None:
                    raise NodeError(f"aggregate failed: goal {c.property} has no verdict in scenario {name}")
                by_scenario.append({
                    "scenario": [{"id": p.ref_id, "subtype": p.subtype}
                                 for p in world_by_name[name].points],
                    "verdict": v,
                })
                verdicts.append((name, v))
            cases.append({"id": c.property, "by_scenario": by_scenario})

            if all(v == "true" for _, v in verdicts):
                results.append({"id": c.property, "verdict": "true"})
            elif any(v == "false" for _, v in verdicts):
                bad = [n for n, v in verdicts if v == "false"]
                results.append({"id": c.property, "verdict": "false",
                                "description": f"does not hold in scenarios: {bad}"})
            elif any(v == VACUOUS for _, v in verdicts):
                # Checked before no-answer: a vacuous scenario points at what
                # the flow model left out, and a goal never tested there has
                # no answer, so it cannot read "true".
                dead = [n for n, v in verdicts if v == VACUOUS]
                results.append({
                    "id": c.property, "verdict": VACUOUS,
                    "description": f"never tested in scenarios {dead}: the goal's "
                                   f"observation point is unreachable there, so it was "
                                   f"proved on no traces at all",
                })
            elif any(v in NO_ANSWER for _, v in verdicts):
                # The solver never finished somewhere, so the goal has no
                # answer rather than an undecided one. Reported under the first
                # such kind, since a timeout and a solver_limit are fixed
                # differently.
                out = next(v for _, v in verdicts if v in NO_ANSWER)
                none = [n for n, v in verdicts if v in NO_ANSWER]
                unk = [n for n, v in verdicts if v == "unknown"]
                results.append({
                    "id": c.property, "verdict": out,
                    "description": f"no answer: the solver did not finish on scenarios {none}"
                                   + (f", and reported cannot-be-proved on {unk}" if unk else "")
                                   + " (see solver_notes in each scenario verdict.json)",
                })
            else:
                unk = [n for n, v in verdicts if v == "unknown"]
                results.append({
                    "id": c.property, "verdict": "unknown",
                    "description": f"undecided: no verdict for scenarios {unk} "
                                   f"(see solver_notes in each scenario verdict.json)",
                })

        write_json(env.layout.cases_results_json,
                   {"vocab_version": VOCAB_VERSION, "cases": cases})
        write_json(env.layout.results_json,
                   {"vocab_version": VOCAB_VERSION,
                    "protocol_id": env.protocol_id,
                    "results": results})
        if env.bus is not None:
            # The answers also go on the ledger, so a stream reader never has
            # to re-apply the conjunction rule itself.
            env.bus.emit(Aggregated(run=env.layout.run_name, node=self.name,
                                    results=results))
