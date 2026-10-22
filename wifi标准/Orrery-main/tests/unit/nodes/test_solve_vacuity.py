"""The vacuity pass: was the goal's observation point ever reachable?

An unreachable observation point leaves no trace to search, so ProVerif proves
the goal on nothing and the verdict text reads like a real proof. The pass asks
reachability separately and marks such goals vacuous.
"""
from __future__ import annotations

import asyncio

from orrery.infra.proverif.runner import ProVerifRunner, RawRun
from orrery.nodes.solve.node import solve_grid

PV = """\
free c: channel.
event begin_g_auth(bitstring).
event end_g_auth(bitstring).
query x: bitstring; event(end_g_auth(x)) ==> event(begin_g_auth(x)).

free witness_g_sec_A: bitstring [private].
fun wenc_g_sec(bitstring, nonce): bitstring.
query attacker(witness_g_sec_A).

let processA(k: nonce) =
  event begin_g_auth(k);
  out(c, wenc_g_sec(witness_g_sec_A, k));
  event end_g_auth(k).

process 0
"""

#: both goals proved; vacuity only ever runs on proved goals
SOLVED = ("RESULT event(end_g_auth(x)) ==> event(begin_g_auth(x)) is true.\n"
          "RESULT not attacker(witness_g_sec_A[]) is true.\n")


class Fake(ProVerifRunner):
    def __init__(self, vacuity: RawRun):
        super().__init__(executable="/bin/true", timeout_s=999)
        self.vacuity = vacuity
        self.calls: list[tuple[str, str, int | None]] = []

    async def run(self, pv, log_to, extra_args=(), timeout_s=None):
        self.calls.append((pv, str(log_to), timeout_s))
        if len(self.calls) == 1:
            return RawRun(stdout=SOLVED, stderr="", returncode=0,
                          duration_s=1.0, timed_out=False)
        return self.vacuity


def _solve(runner, tmp_path, **kw):
    return asyncio.run(solve_grid(runner, PV, ["g_auth", "g_sec"], name="t",
                                  cell_dir=tmp_path, precise_retry=False,
                                  vacuity_timeout_s=120, **kw))


def _vac(stdout):
    return RawRun(stdout=stdout, stderr="", returncode=0, duration_s=0.5,
                  timed_out=False)


REACHABLE = ("RESULT not event(end_g_auth(x)) is false.\n"
             "RESULT not attacker(wenc_g_sec(witness_g_sec_A[],x)) is false.\n")
DEAD_AUTH = ("RESULT not event(end_g_auth(x)) is true.\n"
             "RESULT not attacker(wenc_g_sec(witness_g_sec_A[],x)) is false.\n")


def test_a_goal_nothing_can_reach_is_recorded_vacuous(tmp_path):
    r = Fake(_vac(DEAD_AUTH))
    vs, note = _solve(r, tmp_path)
    assert vs == {"g_auth": "vacuous", "g_sec": "true"}
    assert "vacuous: g_auth" in note


def test_a_goal_whose_point_is_reachable_keeps_its_proof(tmp_path):
    r = Fake(_vac(REACHABLE))
    vs, note = _solve(r, tmp_path)
    assert vs == {"g_auth": "true", "g_sec": "true"}
    assert "reachable" in note


def test_no_answer_from_the_pass_changes_nothing(tmp_path):
    """A timed-out pass keeps the original proof: a solver limit is not a
    finding about the protocol."""
    r = Fake(RawRun(stdout="", stderr="", returncode=-1, duration_s=120.0,
                    timed_out=True))
    vs, note = _solve(r, tmp_path)
    assert vs == {"g_auth": "true", "g_sec": "true"}
    assert "reached no verdict" in note


def test_only_proved_goals_are_asked_about(tmp_path):
    """false means a counterexample trace reached the point, unknown means the
    solver settled nothing; neither can be vacuous."""
    class Refuted(Fake):
        async def run(self, pv, log_to, extra_args=(), timeout_s=None):
            self.calls.append((pv, str(log_to), timeout_s))
            if len(self.calls) == 1:
                return RawRun(
                    stdout="RESULT event(end_g_auth(x)) ==> event(begin_g_auth(x)) is false.\n"
                           "RESULT not attacker(witness_g_sec_A[]) cannot be proved.\n",
                    stderr="", returncode=0, duration_s=1.0, timed_out=False)
            # The provisional secrecy result still gets its trace retry; a
            # timeout there keeps unknown and never reaches vacuity.
            return RawRun(stdout="", stderr="", returncode=-1,
                          duration_s=100.0, timed_out=True)

    r = Refuted(_vac(DEAD_AUTH))
    vs, note = _solve(r, tmp_path)
    assert vs == {"g_auth": "false", "g_sec": "unknown"}
    assert len(r.calls) == 2                       # trace retry, no vacuity pass
    assert "vacuity" not in note


def test_the_pass_asks_reachability_under_its_own_budget(tmp_path):
    r = Fake(_vac(REACHABLE))
    _solve(r, tmp_path)
    src, log_to, budget = r.calls[1]
    assert budget == 120
    assert src.startswith("set reconstructTrace = false.")   # a derivation, not a trace
    assert "event(end_g_auth(x0))." in src                   # a plain reachability query
    assert "==>" not in src                                  # no correspondence left
    assert "attacker(wenc_g_sec(witness_g_sec_A, x))." in src
    assert log_to.endswith("proverif_vacuity")


def test_the_pass_can_be_turned_off(tmp_path):
    r = Fake(_vac(DEAD_AUTH))
    vs, note = _solve(r, tmp_path, vacuity_check=False)
    assert vs == {"g_auth": "true", "g_sec": "true"}
    assert len(r.calls) == 1 and "vacuity" not in note
