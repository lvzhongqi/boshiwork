"""The two tools the expert can use on one verdict cell, both on request.

deepen_trace hands over the long ProVerif trace behind a false cell when the
stored short one does not settle the question; record_finding files the reading
so the console can show it back on the cell it is about.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from orrery.agent.tools.context import ToolContext
from orrery.agent.tools.registry import ToolDef, page
from orrery.infra.llm.client import FunctionParameter

#: The three readings a counter-example can be given, shared with the automatic
#: step so old and new findings speak one vocabulary.
READINGS = ("genuine_attack", "modelling_gap", "undecided")
#: The steps a modelling gap can be laid at. ``none`` is for a genuine attack,
#: where nothing in this pipeline is what would have to change.
STEPS = ("extract_flow", "build_world", "build_root", "apply", "inject", "none")

_SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class Finding:
    """One reading of one cell, on its way to the ledger as a plain value."""
    goal: str
    scenario: str
    reading: str
    responsible_step: str
    why: str


def _layout(ctx: ToolContext):
    from orrery.services.store.layout import RunLayout
    root = ctx.artifacts_root
    if root is None:
        raise RuntimeError("no run directory to read from")
    run_dir = Path(root)
    return RunLayout(run_dir.parent.parent, run_dir.parent.name, run_dir.name)


async def _deepen_trace(ctx: ToolContext, scenario: str, goal: str,
                        from_line: int | None = None,
                        to_line: int | None = None) -> str:
    """The long-display trace behind one false cell, paged. A reproduction the
    run or an earlier question already made is read back; otherwise the
    goal's own solver file is run again once and kept under ``_attacks/``, so
    a second call and the console's reproduction share it. Raises
    RuntimeError with no solver, on a cell that is not false, or when the
    re-run does not finish."""
    from orrery.modules.attacks.locate import LocateError, solver_source
    from orrery.modules.attacks.reproduce import rerun
    if not (_SAFE.match(scenario) and _SAFE.match(goal)):
        raise RuntimeError(
            f"scenario and goal must be plain names as the run spells them; "
            f"got {scenario!r} and {goal!r}")
    layout = _layout(ctx)
    for home in layout.attack_dirs(scenario, goal):
        if (home / "trace.txt").is_file():
            text = (home / "trace.txt").read_text(encoding="utf-8")
            break
    else:
        if ctx.proverif is None:
            raise RuntimeError(
                "no solver is configured for this session, so a longer trace "
                "cannot be produced; the stored solver output is what there is")
        try:
            source = solver_source(layout.inject_family_dirs(scenario), goal,
                                   label=scenario)
        except LocateError as e:
            raise RuntimeError(
                f"{e}. list_artifacts shows which scenarios exist, and only a "
                f"goal whose verdict is false has a counter-example") from None
        runner, timeout = ctx.proverif
        home = layout.attack_dir(scenario, goal, manual=True)
        rep = await rerun(runner, source, home, goal, timeout_s=timeout)
        if rep.status != "ok":
            raise RuntimeError(
                f"the long-trace run ended {rep.status}"
                + (f" (the goal came back {rep.verdict})" if rep.verdict else "")
                + "; the stored numbered solver trace is what there is")
        text = (home / "trace.txt").read_text(encoding="utf-8")
    return page(text.strip(), from_line=from_line, to_line=to_line,
                budget=ctx.tool_return_chars,
                label=f"{scenario}/{goal} long trace")


def _record_finding(ctx: ToolContext, goal: str, scenario: str, reading: str,
                    responsible_step: str, why: str) -> str:
    if reading not in READINGS:
        raise RuntimeError(f"reading must be one of {list(READINGS)}")
    if responsible_step not in STEPS:
        raise RuntimeError(f"responsible_step must be one of {list(STEPS)}")
    if reading == "genuine_attack" and responsible_step != "none":
        raise RuntimeError(
            "a genuine_attack lays no step at fault — the protocol is what "
            "breaks, not a step of this pipeline; use none")
    if reading == "modelling_gap" and responsible_step == "none":
        raise RuntimeError(
            "a modelling_gap is something one step wrote; name the step that "
            "would have to change")
    if not why.strip():
        raise RuntimeError("why is required: the reasoning, tying quoted lines "
                           "of the material to the reading")
    finding = Finding(goal=goal.strip(), scenario=scenario.strip(),
                      reading=reading, responsible_step=responsible_step, why=why)
    if ctx.emitter is None:
        raise RuntimeError("this session cannot file findings")
    # Filed as an event, not returned as a result: the tool is not terminal, and
    # the finding has to outlive the conversation.
    from orrery.services.events import FindingRecorded
    ctx.emitter(FindingRecorded(
        run="", node="expert", goal=finding.goal, scenario=finding.scenario,
        reading=finding.reading, responsible_step=finding.responsible_step,
        why=finding.why))
    return (f"filed: {finding.goal} @ {finding.scenario} read as "
            f"{finding.reading}"
            + (f", on {finding.responsible_step}"
               if finding.responsible_step != "none" else "")
            + ". It is on the record and shown on that cell. Carry on answering.")


REVIEW_TOOLS = [
    ToolDef(
        name="deepen_trace",
        description=(
            "Return the long ProVerif trace behind one false cell. The stored "
            "numbered solver output carries the derivation and a short trace; "
            "the long display prints the execution itself — every comparison "
            "that succeeded and with what values, every destructuring, and the "
            "attacker's knowledge as it grows. Ask for it when the short trace "
            "does not settle which party was the honest role's peer, or why a "
            "guard let a run through. When the run has not reproduced this "
            "cell yet it costs one solver run. Only a cell whose goal came back "
            "false has a counter-example at all."),
        parameters=FunctionParameter(type="object", properties={
            "scenario": FunctionParameter(type="string", description="the scenario's name, as the run spells it without its number, e.g. baseline"),
            "goal": FunctionParameter(type="string", description="the goal id whose verdict is false in that scenario"),
            "from_line": FunctionParameter(type=["integer", "null"], description="first line, 1-based and inclusive; default 1"),
            "to_line": FunctionParameter(type=["integer", "null"], description="last line, inclusive; default as much as fits"),
        }, required=["scenario", "goal", "from_line", "to_line"]),
        handler=_deepen_trace,
    ),
    ToolDef(
        name="record_finding",
        description=(
            "File your reading of one cell, so the console can show it on that "
            "cell and the record keeps it. Call it once you have concluded, "
            "and keep answering the user afterwards — this does not end the "
            "reply. A security goal here is a claim about honest sessions: an "
            "honest party may legitimately run the protocol with the attacker, "
            "and in such a run the attacker legitimately learns that session's "
            "secrets. Read modelling_gap when the honest party's peer in the "
            "trace is an identity the attacker supplied or registered and the "
            "observation point fired anyway; genuine_attack when every party "
            "was one the goal was meant to protect and the attacker still got "
            "what the goal says it cannot; undecided when the material does "
            "not settle it, and say what is missing. An undecided costs a "
            "person one look; a wrong genuine_attack sends them hunting an "
            "attack that is not there, and a wrong modelling_gap buries a real "
            "one."),
        parameters=FunctionParameter(type="object", properties={
            "goal": FunctionParameter(type="string", description="the goal id this reading is about"),
            "scenario": FunctionParameter(type="string", description="the scenario's directory name the reading is about"),
            "reading": FunctionParameter(type="string", enum=list(READINGS), description="which of the three this counter-example is"),
            "responsible_step": FunctionParameter(type="string", enum=list(STEPS), description="the step that would have to change; none for a genuine attack"),
            "why": FunctionParameter(type="string", description="one paragraph tying quoted lines of the material to the reading"),
        }, required=["goal", "scenario", "reading", "responsible_step", "why"]),
        handler=_record_finding,
    ),
]
