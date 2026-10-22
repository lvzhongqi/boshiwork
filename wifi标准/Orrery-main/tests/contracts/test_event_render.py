"""Every event type must render into a sentence.

The bus mirrors each event into the log through services/events/render.py. A
type with no renderer still emits, but as a bare type name: the run keeps
working while the terminal fills with lines nobody can read. These tests turn
that silent degradation into a failure, so a new event class needs a _RENDER
entry.
"""

import dataclasses
import logging

from orrery.services.events import KNOWN
from orrery.services.events.render import _RENDER, render


def test_every_known_event_has_a_renderer():
    """Every class in the KNOWN registry must have a _RENDER entry."""
    missing = sorted(c.__name__ for c in KNOWN.values() if c not in _RENDER)
    assert not missing, (
        "event types with no renderer in services/events/render.py: "
        + ", ".join(missing))


def test_no_renderer_for_a_type_that_no_longer_exists():
    """The other direction: a renderer left behind after its event class went
    away."""
    stale = sorted(c.__name__ for c in _RENDER if c not in set(KNOWN.values()))
    assert not stale, "renderers for unknown event types: " + ", ".join(stale)


def test_each_renderer_produces_one_nonempty_line_at_a_sane_level():
    """Each event is built from its dataclass defaults, so this covers every
    type without naming any of them."""
    for cls in KNOWN.values():
        event = cls(run="R01", node="extract_flow", scenario=None)
        level, text = render(event)
        assert level in (logging.DEBUG, logging.INFO), \
            f"{cls.__name__}: level {level} is neither debug nor info"
        assert text and "\n" not in text, \
            f"{cls.__name__}: rendered to {text!r}, which is empty or multi-line"


def test_payload_fields_reach_the_text():
    """A spot check that renderers read their payload rather than print a fixed
    string: the fields carrying the answer must show up in the text."""
    from orrery.services.events import (
        CheckReport, NodeFinished, RunFailed, ScenarioFinished,
    )

    _, failed = render(RunFailed(run="R01", reason="proverif exploded"))
    assert "proverif exploded" in failed

    _, done = render(NodeFinished(run="R01", node="claims", status="ok",
                                  artifacts=["claims.json"]))
    assert "claims.json" in done and "✔" in done

    _, repair = render(CheckReport(run="R01", node="extract_flow",
                                   passed=False, attempt=2,
                                   findings=["query has no matching event"]))
    assert "2" in repair and "query has no matching event" in repair

    _, scn = render(ScenarioFinished(run="R01", scenario="lowe", status="ok",
                                     verdicts={"g1": "false"}))
    assert "g1=false" in scn


def test_long_lists_are_counted_rather_than_named():
    """A node with twenty artifacts must not produce a twenty-item line."""
    from orrery.services.events import NodeFinished

    arts = [f"file{i}.pv" for i in range(20)]
    _, text = render(NodeFinished(run="R01", node="scenarios", artifacts=arts))
    assert "+17 more" in text
    assert "file19.pv" not in text


def test_renderers_cover_every_payload_field_shape():
    """Every payload field needs a default, which is what lets the tests above
    build one event of each class without knowing its fields."""
    for cls in KNOWN.values():
        for f in dataclasses.fields(cls):
            if f.name in ("run",):
                continue
            assert f.default is not dataclasses.MISSING \
                or f.default_factory is not dataclasses.MISSING, \
                f"{cls.__name__}.{f.name} has no default"
