"""Pure-logic unit tests for the scenario stage: world expansion, the apply
order, the naming-anchor check, and how solve handles unknown."""

import asyncio
from pathlib import Path

import pytest

import orrery.checks.rules.goals  # noqa: F401
from orrery.checks.registry import run_checks
from orrery.infra.proverif.runner import ProVerifRunner, RawRun
from orrery.modules.libschema.io import load_assumptions, load_claims
from orrery.modules.libschema.resolve import expand_assignments
from orrery.nodes.apply.realizers import subtype_is_noop
from orrery.nodes.solve.node import solve_grid
from orrery.nodes.apply.order import apply_order
from tests.fixtures import CLAIMS


def test_expand_dedup_on_fixture_claims():
    a = load_assumptions(CLAIMS / "assumptions.json")
    q = load_claims(CLAIMS / "claims.json", a)
    worlds, alias = expand_assignments(q, a, subtype_is_noop)
    # 4 goals over 3 scenario names → 3 distinct worlds, named by the claims table
    names = [n for n, _ in worlds]
    assert names == ["baseline", "peer_key_attacker_supplied", "shared_key_leaked"]
    assert alias == {n: n for n in names}
    # every world is a complete assignment over the declared assumptions
    assert all(len(w) == len(a.entries()) for _, w in worlds)
    # expansion is deterministic
    assert names == [n for n, _ in expand_assignments(q, a, subtype_is_noop)[0]]


def test_apply_order_structural_first_then_by_id():
    """Realizer write sets are disjoint, so apply order carries no meaning and
    is fixed only for determinism: structural-form points first, then the
    (id, subtype) sort."""
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class P:
        ref_id: str
        axis: str
        subtype: str

    # zz_admission sorts last by id, but its form is structural (admission.open
    # reshapes the main-process group), so it leads, as does
    # data.leaked_after_session; the light leaks follow by id.
    pts = [P("ltk_reveal_B", "data", "disclosed"),
           P("zz_admission", "admission", "open"),
           P("ltk_reveal_A", "data", "disclosed"),
           P("window_S", "data", "leaked_after_session")]
    ordered = apply_order(pts)
    assert [p.ref_id for p in ordered] == [
        "window_S", "zz_admission", "ltk_reveal_A", "ltk_reveal_B"]


def test_goals_naming_anchor():
    pv = ("query attacker(w_secrecy_i_a[]).\n"
          "query x: bitstring; inj-event(end_auth_b_to_a(x)) ==> "
          "inj-event(begin_auth_b_to_a(x)).\n")
    rs = asyncio.run(run_checks(["goals_naming_anchor"], {
        "pv": pv, "goal_ids": ["secrecy_i_a", "auth_b_to_a"]}))
    assert rs[0].passed
    rs2 = asyncio.run(run_checks(["goals_naming_anchor"], {
        "pv": pv, "goal_ids": ["secrecy_i_a", "auth_b_to_a", "missing_goal"]}))
    assert not rs2[0].passed and any("missing_goal" in f for f in rs2[0].findings)
    rs3 = asyncio.run(run_checks(["goals_naming_anchor"], {
        "pv": "query attacker(secret[]).\n", "goal_ids": ["g1"]}))
    assert not rs3[0].passed          # the query's owner cannot be identified

    rs4 = asyncio.run(run_checks(["goals_naming_anchor"], {
        "pv": "query attacker(new secret). (* g1 *)\n",
        "goal_ids": ["g1"]}))
    assert rs4[0].passed


def test_solve_grid_records_timeout_not_unknown(tmp_path):
    """A timeout is not "unknown": "unknown" is ProVerif saying it cannot prove
    the goal, an answer about the model, while a timeout is the solver never
    finishing."""
    class FakeRunner(ProVerifRunner):
        def __init__(self):
            super().__init__(executable="/bin/true", timeout_s=1)

        async def run(self, pv, log_to):
            return RawRun(stdout="", stderr="", returncode=-1,
                          duration_s=1.0, timed_out=True)

    vs, note = asyncio.run(solve_grid(FakeRunner(), "pv", ["a", "b"],
                                      name="t", cell_dir=tmp_path,
                                      precise_retry=True))
    assert vs == {"a": "timeout", "b": "timeout"} and "timeout" in note


def test_solve_announces_its_answer(tmp_path):
    """solve_grid emits progress events through `emit`, not just the evidence
    files, so a watcher can follow the longest wait in the pipeline."""
    class FakeRunner(ProVerifRunner):
        def __init__(self):
            super().__init__(executable="/bin/true", timeout_s=10)

        async def run(self, pv, log_to):
            return RawRun(stdout="RESULT q_a is true.\nRESULT q_b is false.\n",
                          stderr="", returncode=0, duration_s=2.5, timed_out=False)

    seen = []
    vs, _ = asyncio.run(solve_grid(
        FakeRunner(), "pv", ["q_a", "q_b"], name="sc_Secrecy_basic",
        cell_dir=tmp_path, precise_retry=False,
        cell="basic", emit=seen.append))

    # three events, and the order is the point: starting, the vacuity pass,
    # then the answer
    start, vac, ev = seen
    assert "handed to ProVerif" in start.text and "2 goal(s)" in start.text
    assert "observation points are reachable" in vac.text
    assert ev.cell == "basic" and ev.kind == "ok" and ev.seconds == 2.5
    assert ev.verdicts == vs and not ev.retried


def test_solve_says_so_when_it_reached_no_verdict(tmp_path):
    """A timeout is neither a failed run nor a verdict, so the event carries
    the distinction; without it the page shows an empty cell with no reason."""
    class FakeRunner(ProVerifRunner):
        def __init__(self):
            super().__init__(executable="/bin/true", timeout_s=1)

        async def run(self, pv, log_to):
            return RawRun(stdout="", stderr="", returncode=-1,
                          duration_s=1.0, timed_out=True)

    seen = []
    asyncio.run(solve_grid(FakeRunner(), "pv", ["a"], name="t",
                           cell_dir=tmp_path, cell="basic", emit=seen.append))
    _, ev = seen
    assert ev.kind == "timeout" and ev.verdicts == {"a": "timeout"}


def test_solve_stays_silent_without_a_sink(tmp_path):
    """No emitter is the headless path: the verdicts and the note come back
    unchanged."""
    class FakeRunner(ProVerifRunner):
        def __init__(self):
            super().__init__(executable="/bin/true", timeout_s=1)

        async def run(self, pv, log_to):
            return RawRun(stdout="RESULT q is true.\n", stderr="",
                          returncode=0, duration_s=0.2, timed_out=False)

    vs, note = asyncio.run(solve_grid(FakeRunner(), "pv", ["q"], name="t",
                                      cell_dir=tmp_path))
    # the model text is a stub with no observation point, so the vacuity pass
    # has nothing to ask and says so in the note
    assert vs == {"q": "true"}
    assert note == "ok; vacuity check: no observation point to ask about"


# ── the stage's own bookkeeping, which needs no model and no solver ────────
# Every path in the stage resolves through the run's index, so asking for a
# scenario's file before that scenario has a directory raises. "Has this
# scenario answered" is asked the other way round: find the directory first,
# then test the file.

def _staged(tmp_path, *scenarios):
    from orrery.nodes.base import RunEnv
    from orrery.services.store.layout import RunLayout
    lay = RunLayout(tmp_path / "wr", "P", "r1")
    lay.run_dir.mkdir(parents=True)
    for n in ("extract_claims", "scenarios"):
        lay.open_node(n)
    for s in scenarios:
        lay.open_scenario(s)
    return RunEnv(protocol_dir=tmp_path, layout=lay, config={})


def test_a_scenario_with_no_directory_is_simply_not_finished(tmp_path):
    """The state every scenario is in before the stage runs: no directory yet,
    so _finished answers no instead of raising on the missing path."""
    from orrery.pipeline.scenarios import _finished
    env = _staged(tmp_path)
    assert _finished(env, "baseline") is False


def test_finished_reads_the_directory_that_currently_holds_the_scenario(tmp_path):
    from orrery.pipeline.scenarios import _finished
    env = _staged(tmp_path, "baseline")
    assert _finished(env, "baseline") is False          # opened, not answered
    (env.layout.scenario_dir("baseline") / "verdict.json").write_text("{}")
    assert _finished(env, "baseline") is True
    # a re-worked scenario answers for its newest generation, not its first
    env.layout.open_scenario("baseline", cause="fix", by="user")
    assert _finished(env, "baseline") is False


def test_is_done_survives_a_stage_whose_scenarios_have_not_run(tmp_path):
    """is_done is asked before the stage has produced anything, and every
    scenario it names is still without a directory, so it answers no rather
    than raising."""
    import shutil
    from orrery.pipeline.scenarios import ScenariosNode

    env = _staged(tmp_path)
    d = env.layout.node_dir("extract_claims")
    for f in ("assumptions.json", "properties.json", "claims.json"):
        shutil.copy(CLAIMS / f, d / f)      # so it gets past reading the claims

    node = ScenariosNode()
    assert node.is_done(env) is False
    # …and says yes once every scenario it names has answered
    for name, _ in expand_assignments(
            load_claims(d / "claims.json", load_assumptions(d / "assumptions.json")),
            load_assumptions(d / "assumptions.json"), subtype_is_noop)[0]:
        (env.layout.open_scenario(name) / "verdict.json").write_text("{}")
    assert node.is_done(env) is True
