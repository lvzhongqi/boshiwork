"""The checks skeleton: registration, execution and the must-level summary."""

import asyncio

import pytest

from orrery.checks.registry import (
    CheckResult, must_failures, register, run_checks,
)


def test_register_run_and_must_failures():
    register("t_shape", "must",
             lambda p: CheckResult("t_shape", "must", bool(p), ["empty artifact"] if not p else []))
    register("t_style", "warn",
             lambda p: CheckResult("t_style", "warn", False, ["a style note"]))
    rs = asyncio.run(run_checks(["t_shape", "t_style"], "not empty"))
    assert must_failures(rs) == []                       # warn does not block
    rs2 = asyncio.run(run_checks(["t_shape", "t_style"], ""))
    assert must_failures(rs2) == ["empty artifact"]
    with pytest.raises(RuntimeError, match="not registered"):
        asyncio.run(run_checks(["no_such_check"], "x"))
    with pytest.raises(RuntimeError, match="registered twice"):
        register("t_shape", "must", lambda p: None)



def test_each_check_reports_itself_as_it_goes():
    """Each check reports its own name, duration and outcome as the round goes,
    plus a "running" line for the ones that await a ProVerif subprocess, so a
    long round is not silent until the verdict."""
    import asyncio

    from orrery.checks.registry import CheckResult, register, run_checks

    register("t_quick", "must", lambda p: CheckResult("t_quick", "must", True))

    async def slow(p):
        return CheckResult("t_slow", "must", False, ["it did not line up"])

    register("t_slow", "must", slow)

    seen = []
    asyncio.run(run_checks(["t_quick", "t_slow"], {},
                           on=lambda *a: seen.append(a)))
    states = [(n, st) for n, st, _s, _f, _note in seen]
    # "running" only for the check that awaits; a synchronous one is over
    # before the line could be drawn.
    assert states == [("t_quick", "passed"),
                      ("t_slow", "running"), ("t_slow", "failed")]
    assert seen[0][2] is not None and seen[1][2] is None   # seconds
    assert seen[2][3] == ["it did not line up"]


def test_a_check_may_pass_and_still_have_something_to_say():
    """A pass that verified nothing (goals_typecheck on a solver timeout) carries
    its outcome as a note, not a finding: a green tick alone would read as a
    model that had been checked, and there is nothing here to repair."""
    import asyncio

    from orrery.checks.registry import CheckResult, register, run_checks

    register("t_noted", "must",
             lambda p: CheckResult("t_noted", "must", True, [], "timeout"))
    seen = []
    asyncio.run(run_checks(["t_noted"], {}, on=lambda *a: seen.append(a)))
    (name, state, _s, findings, note), = seen
    assert state == "passed" and findings == [] and note == "timeout"
