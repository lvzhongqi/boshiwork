"""Rollback-domain events: a gap being reported and ruled on. Emitted from
pipeline/gaps."""

from __future__ import annotations

from dataclasses import dataclass

from orrery.services.events.types import Event


@dataclass
class GapReported(Event):
    """A node asked to roll back: which upstream node it names, and what it
    found missing there."""

    target: str = ""
    missing: str = ""


@dataclass
class GapVerdict(Event):
    """The ruling on a reported gap: whether the rollback was granted, and
    why."""

    accepted: bool = False
    reason: str = ""
