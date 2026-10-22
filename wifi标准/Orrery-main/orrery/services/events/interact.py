"""Interaction-domain events: waiting for confirmation. Emitted from the api
layer, when the host hands a plan to the user."""

from __future__ import annotations

from dataclasses import dataclass, field

from orrery.services.events.types import Event


@dataclass
class AwaitingConfirm(Event):
    """The run is parked on a user decision: a digest of the plan on offer and
    of what it would cost."""

    plan_digest: str = ""
    cost_digest: str = ""


@dataclass
class ExpertAsked(Event):
    """What was asked. On the ledger beside the answer, so reloading the page
    shows a conversation and not a monologue, and so the record says who steered
    this run and how."""

    text: str = ""
    # Which cell the question was asked from, when it was asked from one, and
    # what material went with it: a question with a model in front of it and the
    # same question without one are not the same question.
    goal: str = ""
    scenario: str = ""
    stage: str = ""
    attached: list = field(default_factory=list)


@dataclass
class FindingRecorded(Event):
    """A reading of one cell, filed by the expert when a reader asked for one.

    It is somebody's judgement added after the run directory was written, so it
    lives on the ledger, which keeps its order, time and conversation. A cell
    may collect several readings over time; they all stay and the newest is the
    one shown.
    """

    goal: str = ""
    scenario: str = ""
    reading: str = ""            # genuine_attack | modelling_gap | undecided
    responsible_step: str = ""   # the step that would have to change, or none
    why: str = ""


@dataclass
class ReviewClosed(Event):
    """A person marked this run reviewed, or opened it again. ``state`` is
    ``archived`` or ``open``. The run's own status is untouched: what the
    pipeline concluded and what a reader concluded about it are two separate
    facts.
    """

    state: str = "archived"
    note: str = ""


@dataclass
class ExpertReplied(Event):
    """What the expert said, once a turn is over.

    An event rather than an HTTP response because a turn takes minutes: the
    caller is only told the question was accepted, and the rounds, tool calls
    and reply all arrive on the stream. A front end that reconnected halfway
    still receives this.
    """

    text: str = ""
