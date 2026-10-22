"""Event base class and the JSON-line envelope. Concrete event types live next
to the code that emits them, not here.

Replay and filtering depend on the envelope alone, so it is fixed and versioned;
``data`` carries the per-type payload. A reader that meets an unknown ``t``
skips the line (parse_line returns None).
"""

from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass
from typing import ClassVar

SCHEMA_V = 1

_ENVELOPE_FIELDS = ("run", "node", "scenario", "unit", "seq", "ts")


@dataclass
class Event:
    """Envelope fields. Subclasses add only their own payload fields; ``seq``
    and ``ts`` are filled in by the bus at emit time."""

    #: Whether this event belongs on the run's record: written to the ledger,
    #: mirrored into the log, replayed later. False marks a live view of
    #: something already recorded elsewhere (streamed model fragments) —
    #: broadcast to current watchers, then gone.
    durable: ClassVar[bool] = True

    run: str
    node: str | None = None
    scenario: str | None = None
    #: Which of a scenario's concurrent sessions this came from, as its
    #: directory relative to the scenario (``apply/03_lkr_from_start``,
    #: ``inject/Secrecy``). node plus scenario cannot tell them apart: the stage
    #: runs one session per applied assumption and per injected goal family, all
    #: at once and all stamped alike. None elsewhere, where the node is the unit.
    unit: str | None = None
    seq: int = -1
    ts: str = ""

    @classmethod
    def type_name(cls) -> str:
        """Class name CamelCase → snake_case, i.e. the ``t`` value on the wire."""
        return re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()

    def to_line(self) -> str:
        """This event as one ledger line: envelope flat on the outside, the
        subclass's own fields collected into ``data``."""
        payload = {
            f.name: getattr(self, f.name)
            for f in dataclasses.fields(self)
            if f.name not in _ENVELOPE_FIELDS
        }
        return json.dumps(
            {
                "v": SCHEMA_V,
                "seq": self.seq,
                "ts": self.ts,
                "run": self.run,
                "node": self.node,
                "scenario": self.scenario,
                "unit": self.unit,
                "t": self.type_name(),
                "data": payload,
            },
            ensure_ascii=False,
        )


def parse_line(obj: dict, known: dict[str, type[Event]]) -> Event | None:
    """One parsed line → an event object. Returns None when ``t`` is not in
    ``known``, which is the reader's signal to skip it."""
    cls = known.get(obj.get("t"))
    if cls is None:
        return None
    return cls(
        run=obj["run"],
        node=obj.get("node"),
        scenario=obj.get("scenario"),
        # .get, so a ledger written before the field reads back as None.
        unit=obj.get("unit"),
        seq=obj["seq"],
        ts=obj["ts"],
        **obj.get("data", {}),
    )
