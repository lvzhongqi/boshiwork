"""Pricing and executing a fix plan: expert proposes it as FixPlan data, the
host confirms, execution happens here.

A plan targets a step by its directory path (pipeline/steps) — a node, one
scenario, one apply point, one inject family. Executing it files the message as
a fact in the step's current directory and returns the node to re-enter at;
nothing is moved or deleted, and ``open_*`` carries the fact into whatever
directory the re-work lands in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orrery.agent.tools.expert_tools import FixPlan
from orrery.pipeline import steps
from orrery.pipeline.table import build_table, index_of
from orrery.services import facts
from orrery.services.store.layout import RunLayout
from orrery.services.transcript.writer import TranscriptWriter


def _resolve(layout: RunLayout, table: list, plan: FixPlan) -> steps.StepRef:
    """Resolve the plan to a step reference, raising ValueError when the target
    is a pure-code node. Both estimate and execute call it before writing
    anything, so a plan that points at nothing files no fact."""
    ref = steps.resolve(layout, table, plan.step)
    if not table[index_of(table, ref.node)].model_driven:
        legal = ", ".join(n.name for n in table if n.model_driven)
        raise ValueError(
            f"step {ref.node!r} is pure code and reads no messages: its "
            f"artifact is a function of its inputs, so a fix aimed at it would "
            f"re-run it to the same result. Target one of the model-driven "
            f"steps ({legal}); to simply re-run from {ref.node!r}, re-enter "
            f"the run with --from-node instead.")
    return ref


@dataclass
class FixCost:
    """What a fix plan costs: where the run re-enters, what stops being current,
    and which steps the re-entry executes."""

    from_node: str
    superseded: list[str] = field(default_factory=list)   # dirs no longer current
    reruns: list[str] = field(default_factory=list)       # steps the re-entry runs
    note: str = ""

    @property
    def heavy(self) -> bool:
        """True when the fix is worth stopping the host to ask about: work
        already on disk stops being the run's answer, or the re-entry buys the
        expensive part of the run back. A run that stopped before the scenario
        stage supersedes nothing, yet re-running it is every scenario, every
        model and every ProVerif call."""
        return bool(self.superseded) or "scenarios" in self.reruns


def _reruns(table: list, from_node: str) -> list[str]:
    """The steps a re-entry at ``from_node`` will execute, in table order. A
    composite step reuses whatever is still current inside it (an untouched
    scenario's verdict, an apply point the change is upstream of), so this is
    the ceiling rather than the bill."""
    return [n.name for n in table[index_of(table, from_node):]]


def estimate(layout: RunLayout, plan: FixPlan) -> FixCost:
    """Price a plan without writing anything, so the host can ask before it
    executes. Raises ValueError on a plan that resolves to nothing usable."""
    table = build_table()
    ref = _resolve(layout, table, plan)
    return FixCost(from_node=ref.node,
                   superseded=steps.superseded_by(layout, table, ref),
                   reruns=_reruns(table, ref.node),
                   note=f"{plan.mode}: re-work {ref.kind} {ref.rel} and "
                        f"re-enter at {ref.node}")


def execute(layout: RunLayout, plan: FixPlan) -> str:
    """File the fact at the step's current directory and return the node to
    re-enter at. The re-run itself is the host calling run(), since the
    interrupt handle and the event subscription are the host's to manage.

    The fact goes to the directory the step is working in now, not the one it is
    about to get: ``open_*`` copies a step's facts into the next execution, so
    the message is filed once and arrives wherever the work lands.
    """
    table = build_table()
    ref = _resolve(layout, table, plan)
    prefix = ("[user instruction, directive] The user gave a definite value; write it as "
        "given rather than deciding for yourself.\n"
              if plan.directive else "[user instruction]\n")
    # A step that has not run yet has no directory to hold the fact, so it gets
    # an empty one now; the runner finds it unfinished and carries on inside it.
    rel = ref.rel or layout.rel(layout.open_node(ref.node, cause="fix",
                                                 by="user"))
    facts.append(layout.run_dir / rel, source="user",
                 text=prefix + plan.message)
    # A resumed session replays its transcript, not the fact file, so the message
    # also goes there when a node-level session exists. Composite steps keep
    # their sessions deeper down and re-run fresh, reading the fact instead.
    tp = layout.run_dir / rel / "transcript.jsonl"
    if ref.kind == "node" and plan.mode == "resume" and tp.exists():
        TranscriptWriter(tp).user(prefix + plan.message)
    return ref.node
