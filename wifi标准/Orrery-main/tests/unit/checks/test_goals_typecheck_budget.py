"""What ``goals_typecheck`` asks ProVerif, and on what budget: it runs the
injected file verbatim and reads only the syntax outcome.

Two things here fail silently, so each gets a test. The call is capped, because
ProVerif answers the typecheck question before it starts solving and the solve
node solves the same file afterwards. A pass on the cap carries a note saying
so, since under the cap TIMEOUT is what a healthy large model looks like.
"""

import asyncio
from pathlib import Path

import pytest

from orrery.checks.rules.goals import _TYPECHECK_TIMEOUT_S, _typecheck
from orrery.infra.proverif.outcome import OutcomeKind
from orrery.infra.proverif.runner import RawRun


class _Runner:
    """Records the budget it was handed and replays a canned result."""

    def __init__(self, raw: RawRun):
        self.raw, self.timeout_s = raw, None

    async def run(self, pv, log_to, extra_args=(), timeout_s=None):
        self.timeout_s = timeout_s
        return self.raw


def _run(raw: RawRun):
    runner = _Runner(raw)
    payload = {"pv": "process 0", "runner": runner,
               "pv_log": lambda purpose: Path(purpose)}
    return runner, asyncio.run(_typecheck(payload))


_SOLVED = RawRun(stdout="RESULT not attacker(s[]) is true.\n", stderr="",
                 returncode=0, duration_s=0.4, timed_out=False)
_CUT_OFF = RawRun(stdout="", stderr="", returncode=-1,
                  duration_s=float(_TYPECHECK_TIMEOUT_S), timed_out=True)
_TYPE_ERROR = RawRun(
    stdout='File "/tmp/x/03_r1_typecheck.pv", line 5, characters 67-73:\n'
           "Error: function begin_a expects 2 arguments of types host, "
           "bitstring but is here given 1 argument of type host.\n",
    stderr="", returncode=2, duration_s=0.01, timed_out=False)


def test_the_call_is_capped():
    runner, result = _run(_SOLVED)
    assert runner.timeout_s == _TYPECHECK_TIMEOUT_S
    assert result.passed


def test_a_pass_on_the_cap_explains_itself():
    _, result = _run(_CUT_OFF)
    assert result.passed
    assert result.findings == []
    # "timeout" alone would read as a check that failed to finish; here it is
    # the check finishing the way it means to.
    assert result.note != OutcomeKind.TIMEOUT.value
    assert "typechecked" in result.note
    assert str(_TYPECHECK_TIMEOUT_S) in result.note


def test_a_clean_solve_inside_the_cap_carries_no_note():
    _, result = _run(_SOLVED)
    assert result.note == ""


def test_a_type_error_blocks_and_keeps_no_host_path():
    _, result = _run(_TYPE_ERROR)
    assert not result.passed
    assert len(result.findings) == 1
    assert "expects 2 arguments" in result.findings[0]
    assert "/tmp/x/" not in result.findings[0]
    # the line the model has to fix survives; the file name it never saw goes
    assert result.findings[0].startswith("line 5, characters 67-73:")
    assert "03_r1_typecheck.pv" not in result.findings[0]


@pytest.mark.parametrize("budget", [None, 7])
def test_runner_honours_a_per_call_budget(budget, tmp_path):
    """A per-call budget reaches asyncio.wait_for, and omitting it keeps the
    instance budget."""
    from orrery.infra.proverif.runner import ProVerifRunner

    seen = {}

    async def fake_wait_for(coro, timeout):
        seen["timeout"] = timeout
        coro.close()
        raise asyncio.TimeoutError

    r = ProVerifRunner("/bin/echo", timeout_s=1800)
    import orrery.infra.proverif.runner as mod
    real, mod.asyncio.wait_for = mod.asyncio.wait_for, fake_wait_for
    try:
        raw = asyncio.run(r.run("process 0", log_to=tmp_path / "x",
                                timeout_s=budget))
    finally:
        mod.asyncio.wait_for = real
    assert seen["timeout"] == (1800 if budget is None else budget)
    assert raw.timed_out
