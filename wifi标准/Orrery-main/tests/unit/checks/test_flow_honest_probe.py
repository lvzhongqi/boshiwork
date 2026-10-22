"""The honest-run probe: the model marks each role's successful end, and the
framework strips those marks back to a plain flow model.

The mark has to come from the model because the terminal ``0`` of a body does
not locate success -- a body whose branches end in error handling has the error
branch last. Stripping replaces the mark with ``0`` rather than deleting the
line, which would leave ``out(...);`` in front of an ``else``.
"""

import asyncio
from pathlib import Path

import orrery.checks.rules.flow  # noqa: F401  importing registers the checks
from orrery.checks.registry import must_failures, run_checks
from orrery.infra.proverif.runner import RawRun
from orrery.modules.pvtext.probe import strip_probe

_MODEL = """\
free c: channel.
free channel_A_B: channel [private].
free channel_B_A: channel [private].

event reached_A().
event reached_B().
query event(reached_A()).
query event(reached_B()).

let processA(A: host) =
  out(channel_A_B, A);
  in(channel_B_A, x: bitstring);
  if x = A then
    event reached_A()
  else
    0.

let processB(B: host) =
  in(channel_A_B, y: host);
  out(channel_B_A, B);
  event reached_B().

process
  new A: host;
  ( !processA(A) | !processB(A) )
"""

_ROLES = ["A", "B"]


def _marked(pv: str) -> list[str]:
    return must_failures(asyncio.run(run_checks(
        ["flow_honest_end_marked"], {"pv": pv, "roles": _ROLES})))


def test_the_success_branch_is_accepted_even_when_the_body_ends_on_an_error():
    """processA's last line is the error branch's `0` and the mark sits inside
    the `then`, which is still an accepted shape."""
    assert _marked(_MODEL) == []


def test_a_role_that_never_marks_its_end_is_told_where_to_put_it():
    pv = _MODEL.replace("    event reached_A()\n", "    0\n")
    f = _marked(pv)
    assert any("never reaches `event reached_A()`" in x for x in f)
    assert any("honest run has succeeded" in x for x in f)


def test_a_mark_followed_by_a_semicolon_is_a_waypoint_not_an_end():
    """Buried after a send it would be trivially reachable, and stripping it
    back would leave `0; 0`, which ProVerif does not take."""
    pv = _MODEL.replace("  out(channel_A_B, A);\n",
                        "  out(channel_A_B, A);\n  event reached_A();\n")
    assert any("followed by `;`" in x for x in _marked(pv))


def test_a_role_may_not_mark_another_roles_end():
    pv = _MODEL.replace("    event reached_A()\n", "    event reached_B()\n")
    f = _marked(pv)
    assert any("belongs to role B" in x for x in f)


def test_the_main_process_may_not_mark_an_end():
    pv = _MODEL.replace("  new A: host;\n", "  new A: host;\n  event reached_A();\n")
    assert any("the main process calls" in x for x in _marked(pv))


def test_only_the_probes_queries_are_allowed():
    pv = _MODEL.replace("query event(reached_A()).\n",
                        "query event(reached_A()).\nquery attacker(new sk).\n")
    fails = must_failures(asyncio.run(run_checks(
        ["flow_no_extra_queries"], {"pv": pv, "roles": _ROLES})))
    assert any("attacker(new sk)" in f for f in fails)
    assert must_failures(asyncio.run(run_checks(
        ["flow_no_extra_queries"], {"pv": _MODEL, "roles": _ROLES}))) == []


def test_stripping_gives_back_a_plain_flow_model():
    out = strip_probe(_MODEL)
    assert "reached_" not in out                  # events and queries both gone
    assert "[private]" not in out                 # public network in the flow model
    assert "free channel_A_B: channel." in out
    assert out.count("\n    0\n  else\n    0.") == 1   # the mark became a null process
    assert out.rstrip().endswith("( !processA(A) | !processB(A) )")


class _FakeRunner:
    def __init__(self, raw: RawRun) -> None:
        self.raw, self.calls = raw, 0

    async def run(self, pv, log_to, extra_args=()):
        self.calls += 1
        return self.raw


def _raw(stdout: str, returncode: int = 0) -> RawRun:
    return RawRun(stdout=stdout, stderr="", returncode=returncode,
                  duration_s=0.0, timed_out=False)


def _payload(runner, tmp_path):
    return {"pv": _MODEL, "runner": runner,
            "pv_log": lambda tag: Path(tmp_path) / tag,
            "fixed_lines": [], "roles": _ROLES}


def test_one_proverif_call_answers_both_solver_checks(tmp_path):
    """The submitted file is already the honest-run model, so syntax and
    reachability read the same single ProVerif call."""
    runner = _FakeRunner(_raw(
        "RESULT not event(reached_A) is false.\n"
        "RESULT not event(reached_B) is false.\n"))
    results = asyncio.run(run_checks(
        ["flow_typecheck", "flow_reachability"], _payload(runner, tmp_path)))
    assert runner.calls == 1
    assert must_failures(results) == []


def test_a_syntax_error_is_the_typechecks_to_report(tmp_path):
    """Reachability reports itself unanswered rather than diagnosing a flow that
    was never solved, so the repair works from the syntax error alone."""
    runner = _FakeRunner(_raw(
        'File "x.pv", line 1, character 1:\nError: Syntax error.\n', 2))
    results = asyncio.run(run_checks(
        ["flow_typecheck", "flow_reachability"], _payload(runner, tmp_path)))
    fails = must_failures(results)
    assert any("Syntax error" in f for f in fails)
    assert any("reached no verdict" in f for f in fails)
    assert not any("do not line up" in f for f in fails)


def test_an_unreached_event_names_the_branch_as_a_possible_cause(tmp_path):
    runner = _FakeRunner(_raw(
        "RESULT not event(reached_A) is true.\n"
        "RESULT not event(reached_B) is false.\n"))
    fails = must_failures(asyncio.run(run_checks(
        ["flow_reachability"], _payload(runner, tmp_path))))
    assert len(fails) == 1
    assert "role A never reaches" in fails[0]
    assert "a branch the honest run does not take" in fails[0]


def test_a_role_whose_name_prefixes_another_is_judged_on_its_own_verdict(tmp_path):
    """NSSK's roles are A, B and AS: ``reached_A`` is a prefix of
    ``reached_AS``, so a substring match would let the server's verdict
    answer for A. Each role reads only the query naming it as a whole word."""
    runner = _FakeRunner(_raw(
        "RESULT not event(reached_A) is true.\n"        # A never gets there
        "RESULT not event(reached_AS) is false.\n"))    # the server does
    fails = must_failures(asyncio.run(run_checks(
        ["flow_reachability"], {**_payload(runner, tmp_path), "roles": ["A", "AS"]})))
    assert len(fails) == 1 and "role A never reaches" in fails[0]


def test_a_type_error_reaches_the_model_without_the_host_path(tmp_path):
    """The flow and scenario typechecks used to hand ProVerif's location line
    over verbatim, run directory and all; only the goal typecheck cut it."""
    runner = _FakeRunner(_raw(
        'File "/home/u/runs/P/P01/05_extract_flow/rounds/03_r1_typecheck.pv", '
        'line 12, characters 4-9:\nError: unbound identifier skA.\n', 2))
    fails = must_failures(asyncio.run(run_checks(
        ["flow_typecheck"], _payload(runner, tmp_path))))
    assert fails == ["line 12, characters 4-9: Error: unbound identifier skA."]
