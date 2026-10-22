"""report_gap: the packer for reporting a structural gap upstream.

The handler packs the arguments into a GapReport, and the runner ends the
session the moment it sees one. ``gap_tool(targets)`` is the tool's only
definition site; each node passes the model-driven nodes before it, declared as
``Node.gap_targets``. Both the enum and a re-check in the handler bound the
target, because a rejected report re-runs the whole node.
"""

from __future__ import annotations

from dataclasses import dataclass

from orrery.agent.tools.context import ToolContext
from orrery.agent.tools.registry import ToolDef
from orrery.infra.llm.client import FunctionParameter


@dataclass(frozen=True)
class GapReport:
    reporter: str          # the node reporting
    scenario: str | None
    target: str            # which upstream node to go back to
    missing: str           # must be a concrete, searchable name
    evidence: str          # section number plus the quoted sentence


def _report_gap(ctx: ToolContext, target: str, missing: str, evidence: str) -> GapReport:
    if target not in ctx.upstream_nodes:
        raise RuntimeError(
            f"{target!r} is not upstream of this node. Nodes you may report "
            f"against: {list(ctx.upstream_nodes)}. Pick one of those, or drop "
            f"the report and handle it at the value level (write the right "
            f"value and give the reason alongside your answer)."
        )
    return GapReport(reporter=ctx.node, scenario=ctx.scenario,
                     target=target, missing=missing, evidence=evidence)


_DESCRIPTION = (
    "Report a structural gap: use it when what you need is simply absent from "
    "the upstream artifacts and this step cannot go on. missing must be a "
    "concrete name that can be verified by search, and evidence must give the "
    "source in the document (section number plus a verbatim quote). Do not "
    "report value-level disagreements -- write the right value in your own "
    "artifact and give the reason alongside it. Reporting ends this task; the "
    "framework verifies it and either accepts or rejects it."
)


def gap_tool(targets: tuple[str, ...]) -> ToolDef:
    """``report_gap`` for one node, with that node's legal targets as the enum.

    Raises ValueError on an empty target set: a node with nothing model-driven
    upstream cannot be repaired by a rollback, so it has no legal answer to give.
    """
    if not targets:
        raise ValueError(
            "gap_tool needs at least one legal target; a node with nothing "
            "model-driven upstream must not mount report_gap at all")
    return ToolDef(
        name="report_gap",
        description=_DESCRIPTION,
        parameters=FunctionParameter(type="object", properties={
            "target": FunctionParameter(
                type="string", enum=list(targets),
                description="the upstream node to go back to; the enum is every node this step may report against"),
            "missing": FunctionParameter(type="string", description="the concrete name that is missing"),
            "evidence": FunctionParameter(type="string", description="the source in the document, with a quote"),
        }, required=["target", "missing", "evidence"]),
        handler=_report_gap,
        terminal=True,
    )
