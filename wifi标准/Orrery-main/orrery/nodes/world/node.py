"""build_world: applies the world assumptions to the flow model, exactly once.

``world model = flow + assumptions.json.world``. That section says how many
principals exist, which seats each may take, and how sessions are laid out —
constraints on the whole analysis rather than on one object in it, so they land
before every object-level assumption and may never be a scenario condition
(``Point.from_ref`` refuses a world-assumption id by name).

Products: ``world.pv``, the world model, and ``world.notes``, one line per axis
saying what was applied or left at its flow state. The build is a total order,
population -> role_binding -> session_multiplicity. ``world.pv`` is the
classification base: every multi-writing assumption point in build_root and in
the scenarios classifies against it. It is written even when the world section
is empty, where it is the flow model verbatim.
"""

from __future__ import annotations

import json

from orrery.infra.proverif.runner import ProVerifRunner
from orrery.modules.libschema import load_assumptions
from orrery.nodes.world.builders import WORLD_VOCAB
from orrery.nodes.base import Node, NodeError, RunEnv
from orrery.nodes.world.build import build_steps, builder_steps
from orrery.services.events import NodeProgress
from orrery.services.store.atomic import write_text

#: The identity the world model's build sessions run under, and what a
#: session's own record says it was building. The claims gate keeps the
#: scenario namespace clear of this name.
WORLD_IDENT = "world"


class BuildWorldNode(Node):
    needs_solver = True
    name = "build_world"
    short = "world"
    task = (
        "Apply the declared world assumptions (assumptions.json's world section) to "
        "the flow model, "
        "once, in order, producing the world model every object-level assumption classifies "
        "against")
    model_driven = True

    def is_done(self, env: RunEnv) -> bool:
        return env.layout.has(self.name, "apply", "world.pv")

    async def run(self, env: RunEnv) -> None:
        flow = env.layout.flow_pv
        if not flow.exists():
            raise NodeError("build_world failed: the upstream flow model does not exist")
        flow_pv = flow.read_text(encoding="utf-8")
        assumptions = load_assumptions(
            env.layout.node_dir("extract_claims") / "assumptions.json")
        stated = {e.axis for e in assumptions.world}
        notes = [f"-- {axis} = {WORLD_VOCAB.flow_state(axis)}: flow state, unchanged"
                 for axis in WORLD_VOCAB.axes() if axis not in stated]
        steps = builder_steps(assumptions.world)

        if steps:
            pv_cfg = env.config["proverif"]
            runner = ProVerifRunner(executable=pv_cfg["executable"],
                                    timeout_s=pv_cfg["timeout_s"])
            pv = await build_steps(
                env, steps, runner, flow_pv, notes,
                home=env.layout.node_dir(self.name),
                step_messages=env.facts(self.name))
        else:
            pv = flow_pv
            notes.append("-- every world-assumption axis is at its default: the world "
                         "model is the flow model verbatim")

        write_text(env.layout.world_pv, pv.rstrip("\n") + "\n")
        write_text(env.layout.world_notes, "\n".join(notes) + "\n")
        if env.bus is not None:
            env.bus.emit(NodeProgress(
                run=env.layout.run_name, node=self.name,
                text=f"world model built: {len(steps)} world-assumption axis/axes applied, "
                     f"{len(notes)} already the flow model's state"))
