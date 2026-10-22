"""The apply chain's reuse rule, which is the directory numbering rule.

A point is current when its directory is the newest of its identity and it ran
after the point before it, so a re-worked point lands at a higher number and
makes every later point stale. Staleness comes from the index's time order, not
from a stored hash of the point's input. Reuse is decided before any LLM or
ProVerif object is touched, which is why the stubs here are unusable.
"""

import asyncio

import pytest

from orrery.modules.libschema.model import Point
from orrery.nodes.apply.node import apply_points
from orrery.nodes.base import NodeError, RunEnv
from orrery.services.store.atomic import write_text
from orrery.services.store.layout import RunLayout

POINTS = [Point(axis="key_reuse", subtype="observed",
                target={"of": "kAS"}, ref_id="k1"),
          Point(axis="data", subtype="assumed_secure",
                target={"of": "kBS"}, ref_id="k2")]

START = "process 0\n"
MID = "process 0 (* leaked *)\n"
END = "process 0 (* leaked, guessed *)\n"


def _env(tmp_path):
    lay = RunLayout(tmp_path / "wr", "P", "r1")
    lay.run_dir.mkdir(parents=True)
    lay.open_node("scenarios")
    lay.open_scenario("s1")
    return RunEnv(protocol_dir=tmp_path, layout=lay, config={})


def _done(env, home, rid, out_pv):
    d = env.layout.open_apply_point(home, rid)
    write_text(d / "applied.pv", out_pv)
    write_text(d / "transcript.jsonl", "{}")
    return d


def test_finished_points_are_reused_without_a_session(tmp_path):
    env = _env(tmp_path)
    home = env.layout.scenario_dir("s1")
    _done(env, home, "k1", MID)
    _done(env, home, "k2", END)

    notes: list[str] = []
    # runner=None: a point that was not reused would crash on it
    pv = asyncio.run(apply_points(env, POINTS, None, START, notes,
                                  ident="s1", home=home,
                                  step_path="scenarios/s1"))
    assert pv == END
    assert all("reused" in n for n in notes) and len(notes) == 2


def test_a_reworked_point_makes_the_points_after_it_stale(tmp_path):
    """Invalidation with nothing marked: the re-work lands at a higher number,
    so the point after it now ran before its own input and stops being current.
    The crash on the stub runner says a real session would have started."""
    env = _env(tmp_path)
    home = env.layout.scenario_dir("s1")
    _done(env, home, "k1", "old mid\n")
    second = _done(env, home, "k2", "old end\n")
    assert env.layout.find_apply_point_dir(home, "k2") == second

    # k1 is re-worked — a user fix aimed at that point
    _done(env, home, "k1", MID)
    assert env.layout.find_apply_point_dir(home, "k2") is None   # nothing said so

    with pytest.raises(Exception):
        asyncio.run(apply_points(env, POINTS, None, START, [],
                                 ident="s1", home=home,
                                 step_path="scenarios/s1"))
    # the stale attempt stays where it was: nothing is renamed or written over
    assert (second / "applied.pv").read_text() == "old end\n"
    assert (second / "transcript.jsonl").exists()


def test_the_point_the_fix_aimed_at_runs_even_though_it_is_current(tmp_path):
    """Reuse asks two questions: is this point's work current, and was the
    re-entry aimed at it. A fix aimed at an otherwise current point still
    runs."""
    env = _env(tmp_path)
    home = env.layout.scenario_dir("s1")
    _done(env, home, "k1", MID)
    _done(env, home, "k2", END)
    env.aim = "scenarios/s1/apply/k1"     # a fix addressed to that one point

    with pytest.raises(Exception):
        asyncio.run(apply_points(env, POINTS, None, START, [],
                                 ident="s1", home=home,
                                 step_path="scenarios/s1"))


def test_two_points_that_cannot_be_told_apart_are_refused(tmp_path):
    """A point is addressed by the assumption it came from, so two points
    sharing a ref_id would read as two attempts at one point."""
    env = _env(tmp_path)
    home = env.layout.scenario_dir("s1")
    same = [Point(axis="key_reuse", subtype="observed",
                  target={"of": "kAS"}, ref_id="dup"),
            Point(axis="key_reuse", subtype="observed",
                  target={"of": "kBS"}, ref_id="dup")]
    with pytest.raises(NodeError, match="both called 'dup'"):
        asyncio.run(apply_points(env, same, None, START, [],
                                 ident="s1", home=home,
                                 step_path="scenarios/s1"))
