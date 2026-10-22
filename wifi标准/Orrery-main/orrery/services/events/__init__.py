"""Every event type. One file per emitting domain; adding an event means adding
a class, which KNOWN aggregates for readers to replay against.

KNOWN is the ledger's vocabulary, not the bus's: it is what ``parse_line`` maps
a stored ``t`` back to. A non-durable event (``Event.durable``) never reaches a
file, so it stays out of KNOWN and out of the renderer contract. ModelDelta is
the only one, and is exported by hand below.
"""

from orrery.services.events.agent import (
    ModelDelta, PromptFiled, RoundStarted, SessionUsage, ToolCalled,
    ToolReturned,
)
from orrery.services.events.attacks import AttacksSummarized, AttackStatus
from orrery.services.events.bus import EventBus
from orrery.services.events.checks import (
    CheckRan, CheckReport, FrameworkAction, check_sink,
)
from orrery.services.events.gaps import GapReported, GapVerdict
from orrery.services.events.interact import (
    AwaitingConfirm, ExpertAsked, ExpertReplied, FindingRecorded,
    ReviewClosed,
)
from orrery.services.events.pipeline import (
    Aggregated, AwaitingApproval, CrossChecked, Interrupted, Invalidated,
    NodeFinished,
    NodeProgress, NodeScored, NodeStarted, RunFailed, RunFinished, RunStarted,
    ScenarioFinished, ScenarioStarted, SolveFinished,
)
from orrery.services.events.types import Event, parse_line

_ALL = [
    RunStarted, AwaitingApproval,
    NodeStarted, NodeProgress, NodeFinished, NodeScored, Interrupted,
    RunFinished, RunFailed,
    ScenarioStarted, SolveFinished, ScenarioFinished, Aggregated, CrossChecked,
    Invalidated,
    PromptFiled, RoundStarted, ToolCalled, ToolReturned, SessionUsage,
    CheckRan, CheckReport, FrameworkAction,
    GapReported, GapVerdict, AwaitingConfirm, ExpertAsked, ExpertReplied,
    FindingRecorded, ReviewClosed,
    AttackStatus, AttacksSummarized,
]
KNOWN = {c.type_name(): c for c in _ALL}

__all__ = ["Event", "EventBus", "KNOWN", "ModelDelta", "check_sink",
           "parse_line",
           *[c.__name__ for c in _ALL]]
