"""Check-domain events: the verification result, which is what makes a repair
round visible. Emitted where the agent submits its answer in agent/runner."""

from __future__ import annotations

from dataclasses import dataclass, field

from orrery.services.events.types import Event


@dataclass
class CheckReport(Event):
    """The verdict of one submission: whether every check passed, and the
    findings a repair round works from."""

    passed: bool = True
    findings: list[str] = field(default_factory=list)   # summary: the truncated problem list
    attempt: int = 1                                     # which submission this is


@dataclass
class CheckRan(Event):
    """One named check, reported on its own so a round is not silent while a
    slow check runs. CheckReport only arrives once every check is done, and two
    of them run a ProVerif subprocess.

    ``state`` is ``running`` for a check about to await, then ``passed`` or
    ``failed``. ``note`` carries what happened when passing does not mean the
    check verified anything, such as a typecheck that timed out.
    """

    check: str = ""
    state: str = "passed"                               # running | passed | failed
    seconds: float | None = None                        # None while running
    findings: list[str] = field(default_factory=list)
    note: str = ""


def check_sink(emit):
    """Wrap an emitter into the callback ``run_checks`` reports through, or
    return None when there is nowhere to report. Lives here because the event
    vocabulary does: the check layer says what happened, this layer turns it
    into a CheckRan."""
    if emit is None:
        return None

    def on(name, state, seconds, findings, note):
        emit(CheckRan(run="", check=name, state=state,
                      seconds=None if seconds is None else round(seconds, 1),
                      findings=list(findings or []), note=note or ""))
    return on


@dataclass
class FrameworkAction(Event):
    """What the framework did with a submission before checking it — splicing
    the model's fragments into the file it never sees. Emitted by the node that
    assembles (apply / inject), so the ledger records both halves of the
    exchange."""

    text: str = ""
