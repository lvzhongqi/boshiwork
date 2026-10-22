"""build_root: the fixed assumption layer, applied once, onto the world model.

``root model = world model + assumptions.json's fixed section``, run exactly
once. The layer is commutative (realizer write sets are disjoint), so folding it
into one shared base changes no scenario's world; every scenario starts from its
text.

Artifacts: ``root.pv`` and the notes file recording what each fixed point did.
Encoding-compatible data points share one model call, every other point is its
own unit, and flow-state (noop) entries are only recorded.

Both files are written even when no fixed assumption changes the text — the
root model is then the world model verbatim, so no downstream reader tests for
a missing layer. A scenario condition may only assign a variable dimension (the
claims gate guarantees it), so no scenario delta rewrites the root model.
"""

from __future__ import annotations

from orrery.infra.proverif.runner import ProVerifRunner
from orrery.modules.libschema.io import load_assumptions
from orrery.nodes.apply.node import apply_fixed_data_points, apply_points
from orrery.nodes.apply.order import apply_order, fixed_points
from orrery.nodes.apply.realizers import realizer_for, subtype_is_noop
from orrery.nodes.base import Node, NodeError, RunEnv
from orrery.services.events import NodeProgress
from orrery.services.store.atomic import write_text

#: The identity the root model's apply sessions run under; the claims gate
#: keeps the scenario namespace clear of it.
ROOT_IDENT = "root"


class BuildRootNode(Node):
    needs_solver = True
    name = "build_root"
    short = "root"
    task = (
        "Apply the fixed section's commutative assumptions onto the world "
        "model, once, into the root model each scenario then starts from")
    model_driven = True

    def is_done(self, env: RunEnv) -> bool:
        return env.layout.has(self.name, "apply", "root.pv")

    async def run(self, env: RunEnv) -> None:
        world = env.layout.world_pv
        if not world.exists():
            raise NodeError("build_root failed: the upstream world model does not exist")
        world_pv = world.read_text(encoding="utf-8")
        assumptions = load_assumptions(
            env.layout.node_dir("extract_claims") / "assumptions.json")

        # The whole fixed section in canonical order: flow-state entries change
        # no text and are only recorded, the rest are applied onto the world
        # model.
        commutative = apply_order(fixed_points(assumptions))
        notes: list[str] = []
        live = []
        for p in commutative:
            rid = p.ref_id or realizer_for(p.axis, p.subtype).id
            if subtype_is_noop(p.axis, p.subtype):
                notes.append(f"-- {rid} = {p.subtype}: flow state, unchanged")
            else:
                live.append(p)

        n_noop = len(notes)      # counted before apply_points appends its own
        if live:
            pv_cfg = env.config["proverif"]
            runner = ProVerifRunner(executable=pv_cfg["executable"],
                                    timeout_s=pv_cfg["timeout_s"])
            # Non-data points first, then data points batched by subtype and
            # lifetime-selected writing: fixed data facts are numerous, and the
            # layer is commutative, so the regrouping changes cost, not
            # semantics. Scenario conditions stay one point per session.
            non_data = [point for point in live if point.axis != "data"]
            data = [point for point in live if point.axis == "data"]
            pv = world_pv
            if non_data:
                pv = await apply_points(
                    env, non_data, runner, pv, notes, ident=ROOT_IDENT,
                    home=env.layout.node_dir(self.name), step_path=self.name,
                    step_messages=env.facts(self.name))
            if data:
                pv = await apply_fixed_data_points(
                    env, data, runner, pv, notes,
                    home=env.layout.node_dir(self.name), step_path=self.name,
                    step_messages=env.facts(self.name))
        else:
            pv = world_pv
            notes.append("-- no commutative fixed assumption changes the "
                         "text: the root model is the world model verbatim")

        write_text(env.layout.root_pv, pv.rstrip("\n") + "\n")
        write_text(env.layout.root_notes, "\n".join(notes) + "\n")
        if env.bus is not None:
            env.bus.emit(NodeProgress(
                run=env.layout.run_name, node=self.name,
                text=f"root model built: {len(live)} commutative fixed "
                     f"point(s) applied, {n_noop} already the flow model's "
                     f"state"))
