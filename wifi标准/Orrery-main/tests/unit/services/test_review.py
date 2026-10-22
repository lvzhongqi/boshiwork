"""Tests for the review marker and for the readings a person files against a
run. Neither is a pipeline step: they record whether a reader has been through
the run, and what they concluded about one cell.
"""
import pytest

from orrery.agent.tools.review_tools import _record_finding, READINGS, STEPS
from orrery.agent.tools.context import ToolContext
from orrery.services.review import REVIEW_JSON, review_state


def test_a_run_nobody_marked_reads_as_open(tmp_path):
    """Absent means open; nothing has to be written to say so."""
    assert review_state(tmp_path)["state"] == "open"


def test_review_state_is_invisible_to_agents(tmp_path):
    """A review is a fact about the run added afterwards, not one of its
    artifacts, so no step can read its own review."""
    (tmp_path / REVIEW_JSON).write_text("{}")
    (tmp_path / "_review").mkdir()
    (tmp_path / "_review" / "trace.txt").write_text("x")
    (tmp_path / "ordinary.pv").write_text("x")
    ctx = ToolContext(node="expert", artifacts_root=tmp_path)
    assert ctx.visible_artifacts() == ["ordinary.pv"]


class _Emitter:
    def __init__(self):
        self.events = []

    def __call__(self, event):
        self.events.append(event)


def test_a_finding_goes_on_the_ledger_and_does_not_end_the_reply(tmp_path):
    emitter = _Emitter()
    ctx = ToolContext(node="expert", artifacts_root=tmp_path, emitter=emitter)
    out = _record_finding(ctx, goal="auth_b_to_a", scenario="baseline",
                          reading="modelling_gap", responsible_step="inject",
                          why="the event fires before the guard")
    assert isinstance(out, str) and "filed" in out   # a result, not a terminal value
    assert len(emitter.events) == 1
    assert emitter.events[0].reading == "modelling_gap"


@pytest.mark.parametrize("reading,step", [
    ("genuine_attack", "inject"),    # an attack lays no step at fault
    ("modelling_gap", "none"),       # a gap is always something a step wrote
])
def test_incoherent_readings_are_refused(tmp_path, reading, step):
    ctx = ToolContext(node="expert", artifacts_root=tmp_path, emitter=_Emitter())
    with pytest.raises(RuntimeError):
        _record_finding(ctx, goal="g", scenario="s", reading=reading,
                        responsible_step=step, why="because")


def test_vocabularies_are_closed():
    assert set(READINGS) == {"genuine_attack", "modelling_gap", "undecided"}
    assert "none" in STEPS
