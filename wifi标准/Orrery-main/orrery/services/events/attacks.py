"""Events of the attack reproduction step and of the reproductions a person
asks for after the run."""

from __future__ import annotations

from dataclasses import dataclass

from orrery.services.events.types import Event


@dataclass
class AttackStatus(Event):
    """One false cell's reproduction moved on.

    ``running`` is said before the solver is handed the file, so a watcher can
    tell a long reproduction from a stalled one; ``queued`` only ever comes
    from a request made after the run. The cell is named in the payload, never
    in the envelope's ``scenario``: that field routes an event into a
    scenario's own sessions, and this one belongs to the step.
    """

    goal: str = ""
    label: str = ""          #: the scenario, by name
    status: str = ""         #: queued | running | ok | failed | cancelled
    reason: str = ""         #: why it failed, when it did
    manual: bool = False     #: asked for after the run


@dataclass
class AttacksSummarized(Event):
    """A summary over the reproduced cells was rewritten at someone's request.
    The step's own summary needs no event: the step finishing says it is there."""

    covered: int = 0         #: how many reproduced cells the summary covers
