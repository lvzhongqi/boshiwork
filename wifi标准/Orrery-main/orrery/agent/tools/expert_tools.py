"""propose_fix: the terminal tool of the expert's long session, shaped like
report_gap. The handler packs the arguments into a FixPlan; execution goes
through the host for user confirmation, never through the model."""

from __future__ import annotations

from dataclasses import dataclass

from orrery.agent.tools.context import ToolContext
from orrery.agent.tools.registry import ToolDef
from orrery.infra.llm.client import FunctionParameter


@dataclass(frozen=True)
class FixPlan:
    step: str                      # the step to re-work, by directory path
    mode: str                      # resume = continue the session, redo = re-run the step
    message: str                   # delivered verbatim to that step
    directive: bool = False        # the user gave a definite value to copy, not re-decide
    rationale: str = ""            # one line of reasoning, shown to the user


def _propose_fix(ctx: ToolContext, step: str, mode: str, message: str,
                 directive: bool = False, rationale: str = "") -> FixPlan:
    if mode not in ("resume", "redo"):
        raise RuntimeError("mode must be resume (continue the session, the default) or redo (re-run the whole step)")
    if not step or not str(step).strip():
        raise RuntimeError("step is required: the path of the step to re-work, "
                           "as read_transcript and list_artifacts show it")
    return FixPlan(step=str(step).strip(), mode=mode, message=message,
                   directive=directive, rationale=rationale)


EXPERT_TOOLS = [
    ToolDef(
        name="propose_fix",
        description="Propose a fix plan for one step of this run, so the framework can re-run it. Proposing one ends this reply: the framework prices the work, asks the user to confirm, and runs it -- you cannot run it yourself. The target is a step, addressed by the same directory path list_artifacts and read_transcript show, and it must belong to a model-run part of the pipeline; the pure-code steps read no messages and the framework refuses them. The message goes to that step verbatim and is filed in its directory, so it has to stand on its own.",
        parameters=FunctionParameter(type="object", properties={
            "step": FunctionParameter(type="string", description="path of the step to re-work, as shown by list_artifacts / read_transcript (a node name alone is also accepted)"),
            "mode": FunctionParameter(type="string", enum=["resume", "redo"],
                                      description="resume = continue the original session (default); redo = rerun the whole step. Consulted only for a whole pipeline step: scenarios, apply points and inject families always rebuild from fresh sessions"),
            "message": FunctionParameter(type="string",
                                         description="the message delivered to that step — into the resumed session, or into the prompt when the step starts fresh"),
            "directive": FunctionParameter(type=["boolean", "null"],
                                           description="is this a directive the user specified?"),
            "rationale": FunctionParameter(type=["string", "null"],
                                           description="one line on why this is where the problem is"),
        }, required=["step", "mode", "message", "directive", "rationale"]),
        handler=_propose_fix,
        terminal=True,
    ),
]
