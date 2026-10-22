"""One event → one line a person can read, and the level it deserves. The bus
calls this to mirror every event into the log; a contract test catches an event
type that has no renderer here.

INFO is the run's skeleton (nodes, scenarios, anything abnormal), DEBUG is the
traffic inside a node (rounds, tool calls, token counts). The text is for eyes
only — programs read events.jsonl.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from orrery.services.events.agent import (
    PromptFiled, RoundStarted, SessionUsage, ToolCalled, ToolReturned,
)
from orrery.services.events.attacks import AttacksSummarized, AttackStatus
from orrery.services.events.checks import (
    CheckRan, CheckReport, FrameworkAction,
)
from orrery.services.events.gaps import GapReported, GapVerdict
from orrery.services.events.interact import (
    AwaitingConfirm, ExpertAsked, ExpertReplied, FindingRecorded,
    ReviewClosed,
)
from orrery.services.events.pipeline import (
    Aggregated, AwaitingApproval, CrossChecked, Interrupted, Invalidated,
    NodeFinished,
    NodeScored,
    NodeProgress, NodeStarted, RunFailed, RunFinished, RunStarted,
    ScenarioFinished, ScenarioStarted, SolveFinished,
)
from orrery.services.events.types import Event

INFO = logging.INFO
DEBUG = logging.DEBUG

_MAX_ITEMS = 3          # how many list members a line names before it says "+N more"


def _at(e: Event) -> str:
    """Which corner of the run this came from: node, scenario/node, or
    scenario/node/unit. The unit matters because a scenario runs several
    sessions at once, and without it they all log the same address."""
    return "/".join(p for p in (e.scenario, e.node, e.unit) if p)


def _some(items: list[str]) -> str:
    """The first few members of a list, with the rest counted rather than
    named, so the line stays short enough to read."""
    head = ", ".join(str(x) for x in items[:_MAX_ITEMS])
    rest = len(items) - _MAX_ITEMS
    return f"{head}, +{rest} more" if rest > 0 else head


def _run_started(e: RunStarted) -> tuple[int, str]:
    where = f" (re-entering at {e.from_node})" if e.from_node else ""
    return INFO, f"▶ run {e.run}{where}"


def _node_finished(e: NodeFinished) -> tuple[int, str]:
    if e.status == "skipped":
        return INFO, f"— {_at(e)} skipped (artifacts already present)"
    arts = f" ({_some(e.artifacts)})" if e.artifacts else ""
    if e.status == "check_failed":
        # The node ran; its check is what did not pass. Said in words, since a
        # cross next to a node name reads as "the node broke".
        return INFO, f"≠ {_at(e)} differs from the corpus{arts}"
    if e.status != "ok":
        return INFO, f"✘ {_at(e)} did not complete"
    return INFO, f"✔ {_at(e)}{arts}"


def _node_scored(e: NodeScored) -> tuple[int, str]:
    over = f", +{e.extra} beyond the corpus" if e.extra else ""
    return INFO, f"  {e.slug}: {e.num}/{e.den} against the corpus{over}"


def _scenario_started(e: ScenarioStarted) -> tuple[int, str]:
    # The assignment carries every dimension; only the conditions make this
    # scenario differ from the base, so only they get named.
    conds = [f"{r.get('axis')}.{r.get('subtype')}" for r in e.assignment
             if r.get("from") == "condition"]
    return INFO, (f"▶ scenario {e.scenario}"
                  + (f": {_some(conds)}" if conds else " (the base scenario)"))


def _scenario_finished(e: ScenarioFinished) -> tuple[int, str]:
    mark = "✔" if e.status == "ok" else "✘"
    got = _some([f"{g}={v}" for g, v in sorted(e.verdicts.items())])
    return INFO, f"{mark} scenario {e.scenario}" + (f": {got}" if got else "")


def _solve_finished(e: SolveFinished) -> tuple[int, str]:
    got = _some([f"{g}={v}" for g, v in sorted(e.verdicts.items())])
    tail = "" if e.kind == "ok" else f" [{e.kind}]"
    retry = " (after a preciseActions retry)" if e.retried else ""
    return INFO, (f"⊢ {_at(e)} {e.cell}: {got or 'no verdict'}{tail} "
                  f"in {e.seconds:.1f}s{retry}")


def _aggregated(e: Aggregated) -> tuple[int, str]:
    got = _some([f"{r['id']}={r['verdict']}" for r in e.results])
    return INFO, f"answers: {got or 'none'}"


def _cross_checked(e: CrossChecked) -> tuple[int, str]:
    matched = sum(1 for c in e.cells if c.get("match"))
    return INFO, f"cross-check: {matched}/{len(e.cells)} cells match the ground truth"


def _check_ran(e: CheckRan) -> tuple[int, str]:
    """One check, on its own line, at DEBUG — the round's verdict is the INFO
    line, and a dozen checks per round would bury it."""
    took = "" if e.seconds is None else f" ({e.seconds:g}s)"
    if e.state == "running":
        return DEBUG, f"[{_at(e)}] {e.check}: running{took}"
    mark = "✓" if e.state == "passed" else "✗"
    tail = f" — {e.note}" if e.note else ""
    if e.state != "passed" and e.findings:
        tail = f" — {_some(e.findings)}"
    return DEBUG, f"[{_at(e)}] {mark} {e.check}{took}{tail}"


def _check_report(e: CheckReport) -> tuple[int, str]:
    if e.passed:
        return DEBUG, f"[{_at(e)}] checks passed on submission {e.attempt}"
    return INFO, (f"↻ {_at(e)} not accepted, repair round {e.attempt}: "
                  f"{_some(e.findings)}")


_RENDER: dict[type[Event], Callable[..., tuple[int, str]]] = {
    RunStarted: _run_started,
    NodeStarted: lambda e: (INFO, f"▶ {_at(e)}"),
    NodeProgress: lambda e: (INFO, f"  · {_at(e)}: {e.text}"),
    NodeFinished: _node_finished,
    NodeScored: _node_scored,
    AwaitingApproval: lambda e: (INFO, f"⏸ waiting for approval before {e.node}"),
    ScenarioStarted: _scenario_started,
    ScenarioFinished: _scenario_finished,
    SolveFinished: _solve_finished,
    Aggregated: _aggregated,
    CrossChecked: _cross_checked,
    Invalidated: lambda e: (INFO, f"↺ {e.node}: {len(e.targets)} artifact(s) "
                                  f"superseded, sealed into their slot bands"),
    Interrupted: lambda e: (INFO, f"■ interrupted ({e.scope}); the run is resumable"),
    RunFinished: lambda e: (INFO, f"✔ run {e.run} finished"),
    RunFailed: lambda e: (INFO, ("≠ run " if e.kind == "check" else "✘ run ")
                                + f"{e.run} "
                                + ("differs from the corpus" if e.kind == "check"
                                   else "failed")
                                + (f" at {e.where}" if e.where else "")
                                + f": {e.reason}"),
    RoundStarted: lambda e: (DEBUG, f"[{_at(e)}] round {e.round_no}"
                             + (f" ({e.duration_ms / 1000:.1f}s)" if e.duration_ms else "")),
    PromptFiled: lambda e: (DEBUG, f"[{_at(e)}] prompt filed: {e.path} "
                                   f"({e.chars} chars)"),
    ToolCalled: lambda e: (DEBUG, f"[{_at(e)}] → {e.tool}({e.args_digest})"),
    ToolReturned: lambda e: (DEBUG, f"[{_at(e)}] ← {e.tool} "
                                    f"{'ok' if e.ok else 'failed'}: {e.result_digest}"),
    SessionUsage: lambda e: (DEBUG, f"[{_at(e)}] {e.rounds} round(s), tokens "
                                    f"in={e.input_tokens} (cached {e.cached_tokens}) "
                                    f"out={e.output_tokens}"),
    CheckRan: _check_ran,
    CheckReport: _check_report,
    FrameworkAction: lambda e: (DEBUG, f"[{_at(e)}] framework: {e.text}"),
    GapReported: lambda e: (INFO, f"⚠ {_at(e)} reported a gap: {e.target} is "
                                  f"missing {e.missing!r}"),
    GapVerdict: lambda e: (INFO, f"⚠ gap {'accepted, rolling back' if e.accepted else 'rejected'}"
                                 f": {e.reason}"),
    AwaitingConfirm: lambda e: (INFO, f"⏸ awaiting confirmation: {e.plan_digest} "
                                      f"| {e.cost_digest}"),
    ExpertAsked: lambda e: (INFO, f"💬 asked: {e.text[:80]}"),
    ExpertReplied: lambda e: (INFO, f"💬 expert answered ({len(e.text)} chars)"),
    FindingRecorded: lambda e: (INFO, f"🔎 {e.goal} @ {e.scenario}: {e.reading}"
                                      + (f" → {e.responsible_step}"
                                         if e.responsible_step not in ("", "none")
                                         else "")),
    ReviewClosed: lambda e: (INFO, f"📕 review {e.state}"
                                   + (f": {e.note}" if e.note else "")),
    AttackStatus: lambda e: (INFO, f"⚔ {e.goal} @ {e.label}: {e.status}"
                                   + (" (asked for)" if e.manual else "")
                                   + (f" — {e.reason}" if e.reason else "")),
    AttacksSummarized: lambda e: (INFO, f"⚔ attack summary rewritten over "
                                        f"{e.covered} cell(s)"),
}


def render(event: Event) -> tuple[int, str]:
    """(log level, one line of text). An unknown type falls back to a generic
    line rather than raising, since the bus must not fail on the way to the
    log; the contract test keeps that fallback unreachable for KNOWN types."""
    fn = _RENDER.get(type(event))
    if fn is None:
        return DEBUG, f"{event.type_name()} {_at(event)}".strip()
    return fn(event)
