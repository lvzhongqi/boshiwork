"""Tests for the event bus: emit → disk → read back → subscriber, unknown
types skipped, and seq monotonic across bus instances. The event types used
here are defined in this file only; the bus itself knows no concrete types."""

from dataclasses import dataclass

from orrery.services.events.bus import EventBus
from orrery.services.events.types import Event, parse_line
from orrery.services.store.atomic import read_jsonl_tolerant


@dataclass
class DummyEvent(Event):
    detail: str = ""


@dataclass
class DummyView(Event):
    """A non-durable event: watchers see it while it happens, the run does not
    record it."""

    durable = False
    detail: str = ""


def test_emit_persists_and_dispatches(tmp_path):
    path = tmp_path / "events.jsonl"
    bus = EventBus(path)
    got = []
    unsub = bus.subscribe(got.append)
    bus.emit(DummyEvent(run="r1", node="flow", detail="x"))
    bus.emit(DummyEvent(run="r1", detail="y"))
    assert [e.detail for e in got] == ["x", "y"]
    assert [e["seq"] for e in read_jsonl_tolerant(path)] == [0, 1]
    assert read_jsonl_tolerant(path)[0]["t"] == "dummy_event"
    unsub()
    bus.emit(DummyEvent(run="r1", detail="z"))   # no subscriber: written only
    assert len(read_jsonl_tolerant(path)) == 3


def test_unknown_type_skipped_and_roundtrip(tmp_path):
    path = tmp_path / "events.jsonl"
    bus = EventBus(path)
    bus.emit(DummyEvent(run="r1", node="a", detail="x"))
    lines = read_jsonl_tolerant(path)
    known = {"dummy_event": DummyEvent}
    e = parse_line(lines[0], known)
    assert isinstance(e, DummyEvent) and e.detail == "x" and e.node == "a"
    assert parse_line({**lines[0], "t": "future_type"}, known) is None


def test_seq_continues_across_instances(tmp_path):
    path = tmp_path / "events.jsonl"
    EventBus(path).emit(DummyEvent(run="r1"))
    bus2 = EventBus(path)                        # as a re-entry or recovery would
    bus2.emit(DummyEvent(run="r1"))
    assert [e["seq"] for e in read_jsonl_tolerant(path)] == [0, 1]


def test_bad_subscriber_does_not_break_emit(tmp_path):
    bus = EventBus(tmp_path / "events.jsonl")
    bus.subscribe(lambda e: 1 / 0)
    bus.emit(DummyEvent(run="r1"))               # a failing subscriber cannot stop emit


def test_a_non_durable_event_reaches_watchers_but_not_the_ledger(tmp_path):
    path = tmp_path / "events.jsonl"
    bus = EventBus(path)
    got = []
    bus.subscribe(got.append)
    bus.emit(DummyView(run="r1", node="flow", detail="fragment"))
    assert [e.detail for e in got] == ["fragment"]      # watchers see it
    assert read_jsonl_tolerant(path) == []              # the record does not


def test_a_non_durable_event_does_not_consume_a_seq(tmp_path):
    """seq numbers the record, and re-entry resumes from the highest one on
    disk. Letting a fragment take a number would leave permanent gaps."""
    path = tmp_path / "events.jsonl"
    bus = EventBus(path)
    bus.emit(DummyEvent(run="r1"))
    for _ in range(50):
        bus.emit(DummyView(run="r1", detail="."))
    bus.emit(DummyEvent(run="r1"))
    assert [e["seq"] for e in read_jsonl_tolerant(path)] == [0, 1]


def test_a_view_needs_no_ledger_at_all():
    """A bus with no ledger path records nothing and still broadcasts."""
    bus = EventBus()
    got = []
    bus.subscribe(got.append)
    bus.emit(DummyView(run="r1", detail="early"))
    assert [e.detail for e in got] == ["early"]


def test_unit_rides_the_envelope_and_survives_an_old_ledger(tmp_path):
    """`unit` addresses one of a scenario's concurrent sessions. It rides the
    envelope rather than the payload, and is read back with .get so a ledger
    lacking the field yields None instead of failing."""
    import json

    from orrery.services.events import KNOWN, RoundStarted, parse_line

    line = json.loads(RoundStarted(run="r", node="inject", scenario="sc_a",
                                   unit="inject/Secrecy", round_no=2).to_line())
    assert line["unit"] == "inject/Secrecy"
    assert "unit" not in line["data"]              # envelope, not payload
    assert parse_line(line, KNOWN).unit == "inject/Secrecy"

    line.pop("unit")                               # a ledger from before the field
    assert parse_line(line, KNOWN).unit is None
