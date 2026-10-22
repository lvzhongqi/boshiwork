"""The ordered no-trace -> trace -> preciseActions solve chain."""
from __future__ import annotations

import asyncio

from orrery.infra.proverif.runner import ProVerifRunner, RawRun
from orrery.nodes.solve.node import NodeError, solve_grid

PV = """\
free c: channel.
free w_g_a: bitstring [private].
free w_g_b: bitstring [private].
query attacker(w_g_a).
query attacker(w_g_b).

let processA() = 0.

process 0
"""

FIRST = ("RESULT not attacker(w_g_a[]) cannot be proved.\n"
         "RESULT not attacker(w_g_b[]) is true.\n")


def _raw(stdout: str = "", *, timeout: bool = False) -> RawRun:
    return RawRun(stdout=stdout, stderr="", returncode=-1 if timeout else 0,
                  duration_s=3.0, timed_out=timeout)


class Fake(ProVerifRunner):
    def __init__(self, *replies: RawRun):
        super().__init__(executable="/bin/true", timeout_s=999)
        self.replies = list(replies)
        self.calls: list[tuple[str, str, int | None]] = []

    async def run(self, pv, log_to, extra_args=(), timeout_s=None):
        self.calls.append((pv, str(log_to), timeout_s))
        if len(self.calls) == 1:
            return _raw(FIRST)
        return self.replies.pop(0)


def _solve(runner, tmp_path, **kw):
    return asyncio.run(solve_grid(
        runner, PV, ["g_a", "g_b"], name="t", cell_dir=tmp_path,
        trace_retry_timeout_s=90, precise_retry=True,
        precise_retry_timeout_s=100, **kw))


def test_trace_retry_that_decides_false_is_taken_without_precise(tmp_path):
    runner = Fake(_raw("RESULT not attacker(w_g_a[]) is false.\n"))
    verdicts, note = _solve(runner, tmp_path)
    assert verdicts == {"g_a": "false", "g_b": "true"}
    assert "g_a=false" in note
    assert len(runner.calls) == 2


def test_still_cannot_runs_precise_and_takes_its_answer(tmp_path):
    runner = Fake(
        _raw("RESULT not attacker(w_g_a[]) cannot be proved.\n"),
        _raw("RESULT not attacker(w_g_a[]) is false.\n"),
    )
    verdicts, note = _solve(runner, tmp_path)
    assert verdicts == {"g_a": "false", "g_b": "true"}
    assert "preciseActions retry on 1 goal(s)" in note
    assert "g_a=false" in note
    assert len(runner.calls) == 3


def test_still_stuck_after_precise_is_honestly_unknown(tmp_path):
    runner = Fake(
        _raw("RESULT not attacker(w_g_a[]) cannot be proved.\n"),
        _raw("RESULT not attacker(w_g_a[]) cannot be proved.\n"),
    )
    verdicts, _ = _solve(runner, tmp_path)
    assert verdicts == {"g_a": "unknown", "g_b": "true"}


def test_trace_timeout_stays_unknown_and_does_not_buy_precise(tmp_path):
    runner = Fake(_raw(timeout=True))
    verdicts, note = _solve(runner, tmp_path)
    assert verdicts == {"g_a": "unknown", "g_b": "true"}
    assert len(runner.calls) == 2
    assert "preciseActions retry on 0 goal(s)" in note


def test_three_sources_are_numbered_and_derived_from_untagged_base(tmp_path):
    runner = Fake(
        _raw("RESULT not attacker(w_g_a[]) cannot be proved.\n"),
        _raw("RESULT not attacker(w_g_a[]) is false.\n"),
    )
    _solve(runner, tmp_path)
    first, trace, precise = runner.calls

    assert first[0].startswith("set reconstructTrace = false.\n")
    assert "preciseActions" not in first[0]
    assert first[1].endswith("01_proverif") and first[2] is None

    assert "reconstructTrace" not in trace[0]
    assert "preciseActions" not in trace[0]
    assert "attacker(w_g_a)" in trace[0] and "attacker(w_g_b)" not in trace[0]
    assert "let processA()" in trace[0]
    assert trace[1].endswith("02_proverif_trace_g_a") and trace[2] == 90

    assert precise[0].startswith("set preciseActions = true.\n")
    assert "reconstructTrace" not in precise[0]
    assert "attacker(w_g_a)" in precise[0] and "attacker(w_g_b)" not in precise[0]
    assert precise[1].endswith("03_proverif_precise_g_a") and precise[2] == 100


def test_no_retry_when_everything_decided(tmp_path):
    class AllDecided(Fake):
        async def run(self, pv, log_to, extra_args=(), timeout_s=None):
            self.calls.append((pv, str(log_to), timeout_s))
            return _raw("RESULT not attacker(w_g_a[]) is true.\n"
                        "RESULT not attacker(w_g_b[]) is false.\n")

    runner = AllDecided()
    verdicts, note = _solve(runner, tmp_path)
    assert verdicts == {"g_a": "true", "g_b": "false"}
    assert note == "ok; vacuity check: no observation point to ask about"
    assert len(runner.calls) == 1
    assert runner.calls[0][0].startswith("set reconstructTrace = false.\n")


def test_tagged_input_is_rejected_before_any_solver_call(tmp_path):
    runner = Fake()
    try:
        asyncio.run(solve_grid(
            runner, "set reconstructTrace = false.\n" + PV,
            ["g_a", "g_b"], name="t", cell_dir=tmp_path))
    except NodeError as exc:
        assert "untagged solve input" in str(exc)
    else:
        raise AssertionError("tagged model.pv was accepted")
    assert runner.calls == []
