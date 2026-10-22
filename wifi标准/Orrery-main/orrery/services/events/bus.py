"""Event bus: emit writes to disk first, then dispatches. With no subscribers an
event is only written, which is what a headless run looks like.

Only events that belong to the run's record (``Event.durable``) reach the ledger
and the log; the rest go straight to the subscribers, who see both kinds alike.
A bus can be created before its path is known — the host subscribes before the
run starts, the engine binds the ledger file once the run directory is decided.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from orrery.services.events.render import render
from orrery.services.events.types import Event
from orrery.services.store.atomic import append_line, read_jsonl_tolerant

# Parent of the per-node loggers the mirror writes through. Under the package's
# own logger, so one setup_logger call configures these too.
_EVENT_LOGGER = "orrery.events"


class EventBus:
    """The meeting point between the engine, which only calls emit, and the
    host, which only calls subscribe. Owns the ledger file and its seq counter.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path: Path | None = None
        self._subs: list[Callable[[Event], None]] = []
        self._logger = logging.getLogger(__name__)
        self._seq = 0
        if path is not None:
            self.bind(path)

    def bind(self, path: Path) -> None:
        """Bind the ledger file. An existing file is continued (re-entry or
        recovery): seq resumes from the highest value on disk plus one."""
        self._path = path
        existing = read_jsonl_tolerant(path)
        self._seq = (existing[-1]["seq"] + 1) if existing else 0

    @property
    def path(self) -> Path | None:
        """The ledger this bus writes to, or None before bind(). Two buses on
        one events.jsonl each keep their own ``_seq``, so this is how a caller
        decides whether an existing bus is this run's."""
        return self._path

    @property
    def has_subscribers(self) -> bool:
        return bool(self._subs)

    def emit(self, event: Event) -> None:
        """Stamp the event, append it to the ledger when it is durable, then
        hand it to every subscriber. A subscriber that raises is logged and
        skipped. Raises RuntimeError if a durable event arrives before bind().
        """
        if self._path is None and event.durable:
            raise RuntimeError("EventBus has no ledger path bound; call bind() before emit()")
        # Milliseconds, not seconds: a node that starts and finishes inside one
        # second would otherwise read as instantaneous, and the gap between two
        # rounds is what says where a run's time went.
        event.ts = datetime.now().isoformat(timespec="milliseconds")
        if event.durable:
            # Only recorded events take a seq. A non-durable one borrowing
            # numbers would leave holes in the sequence re-entry resumes from.
            event.seq = self._seq
            self._seq += 1
            line = event.to_line()
            append_line(self._path, line)
            # Log mirror, always on, so the log is a superset of the ledger. It
            # is written after the ledger, so a broken handler cannot cost the
            # record. Two forms of the same event: a sentence to read, and the
            # raw line one level below, which makes the log replayable. Logged
            # under the event's own node, so the name column locates the line
            # and the log is greppable by node.
            log = logging.getLogger(f"{_EVENT_LOGGER}.{event.node or 'run'}")
            level, text = render(event)
            log.log(level, "%s", text)
            log.debug("event %s", line)
        # Subscribers get both kinds: durability is about what survives the run,
        # not about who may see it.
        for fn in list(self._subs):
            try:
                fn(event)
            except Exception:
                # A subscriber (the UI side) must never interrupt the pipeline;
                # a durable event is already on disk and a fragment is
                # droppable, so nothing is lost either way.
                self._logger.warning("event subscriber failed", exc_info=True)

    def subscribe(self, fn: Callable[[Event], None]) -> Callable[[], None]:
        """Register a callback for every event, durable or not, and return the
        function that unregisters it."""
        self._subs.append(fn)

        def unsubscribe() -> None:
            self._subs.remove(fn)

        return unsubscribe
