"""Finding the solver file behind a false cell, and running it again for the
graph. The runner is a stand-in: these tests are about what is asked of the
solver and what is made of its answer."""

import asyncio
from pathlib import Path

import pytest

from orrery.infra.proverif.runner import RawRun
from orrery.modules.attacks.locate import LocateError, solver_source
from orrery.modules.attacks.reproduce import LONG, ReproductionError, rerun
from orrery.services.store.atomic import write_text
from orrery.services.store.layout import RunLayout
from tests.fixtures import ATTACK_GRAPHS

_FALSE = ("RESULT inj-event(end_auth_x(a)) ==> inj-event(begin_auth_x(a)) is false.\n"
          "RESULT (even event(end_auth_x(a)) ==> event(begin_auth_x(a)) is false.)\n")
_UNSURE = "RESULT inj-event(end_auth_x(a)) ==> inj-event(begin_auth_x(a)) cannot be proved.\n"
_PV = "query a: bitstring; inj-event(end_auth_x(a)) ==> inj-event(begin_auth_x(a)).\nprocess 0\n"


def _run(tmp_path, files: dict[str, str]):
    lay = RunLayout(tmp_path / "wr", "P", "r1")
    lay.run_dir.mkdir(parents=True)
    lay.open_node("scenarios")
    lay.open_scenario("lowe")
    fam = lay.open_inject_family("lowe", "Authentication")
    for name, text in files.items():
        write_text(fam / name, text)
    return lay


def test_the_later_retry_is_the_one_that_answered(tmp_path):
    lay = _run(tmp_path, {
        "02_proverif_trace_auth_x.pv": _PV, "02_proverif_trace_auth_x.txt": _UNSURE,
        "03_proverif_precise_auth_x.pv": _PV, "03_proverif_precise_auth_x.txt": _FALSE})
    assert solver_source(lay.inject_family_dirs("lowe"), "auth_x", label="lowe").name == "03_proverif_precise_auth_x.pv"


def test_the_trace_retry_when_no_precise_retry_ran(tmp_path):
    lay = _run(tmp_path, {"02_proverif_trace_auth_x.pv": _PV,
                          "02_proverif_trace_auth_x.txt": _FALSE})
    assert solver_source(lay.inject_family_dirs("lowe"), "auth_x", label="lowe").name == "02_proverif_trace_auth_x.pv"


def test_a_false_cell_without_its_file_is_an_error(tmp_path):
    lay = _run(tmp_path, {"01_proverif.txt": _UNSURE})
    with pytest.raises(LocateError, match="no goal-only solver file"):
        solver_source(lay.inject_family_dirs("lowe"), "auth_x", label="lowe")


def test_a_file_that_does_not_say_false_is_an_error(tmp_path):
    lay = _run(tmp_path, {"02_proverif_trace_auth_x.pv": _PV,
                          "02_proverif_trace_auth_x.txt": _UNSURE})
    with pytest.raises(LocateError, match="answers unknown"):
        solver_source(lay.inject_family_dirs("lowe"), "auth_x", label="lowe")


_WEAK_PV = "free pi: password [private].\nweaksecret pi.\nprocess 0\n"
_WEAK_FALSE = "RESULT Weak secret pi is false.\n"


def test_a_weak_secret_file_is_read_by_its_own_verdicts(tmp_path):
    lay = _run(tmp_path, {"02_proverif_trace_weak_pi.pv": _WEAK_PV,
                          "02_proverif_trace_weak_pi.txt": _WEAK_FALSE})
    assert solver_source(lay.inject_family_dirs("lowe"), "weak_pi",
                         label="lowe").name == "02_proverif_trace_weak_pi.pv"


def test_answers_no_goal_owns_are_a_locate_error(tmp_path):
    lay = _run(tmp_path, {"02_proverif_trace_auth_x.pv": _PV,
                          "02_proverif_trace_auth_x.txt": _WEAK_FALSE})
    with pytest.raises(LocateError, match="which goal"):
        solver_source(lay.inject_family_dirs("lowe"), "auth_x", label="lowe")


class _Runner:
    """Records what it was asked and draws the given graphs where told to."""

    def __init__(self, stdout: str, graphs: int = 1, **raw):
        self.stdout, self.graphs, self.raw = stdout, graphs, raw
        self.calls = []

    async def run(self, pv, log_to, extra_args=(), timeout_s=None):
        self.calls.append((pv, log_to, extra_args, timeout_s))
        where = Path(extra_args[extra_args.index("-graph") + 1])
        dot = (ATTACK_GRAPHS / "nspk_auth.dot").read_text()
        for k in range(1, self.graphs + 1):
            (where / f"trace{k}.dot").write_text(dot)
        return RawRun(**{"stdout": self.stdout, "stderr": "", "returncode": 0,
                         "duration_s": 0.2, "timed_out": False, **self.raw})


def _source(tmp_path):
    src = tmp_path / "02_proverif_trace_auth_x.pv"
    src.write_text(_PV)
    return src


def test_the_rerun_asks_for_the_long_display_and_the_graph(tmp_path):
    runner = _Runner(_FALSE, graphs=2)
    rep = asyncio.run(rerun(runner, _source(tmp_path), tmp_path / "cell",
                            "auth_x", timeout_s=100))
    pv, log_to, args, timeout = runner.calls[0]
    assert pv == LONG + _PV and log_to == tmp_path / "cell" / "trace"
    assert args[0] == "-graph" and args[2:] == ("-commandLineGraph", "true")
    assert timeout == 100
    assert rep.status == "ok" and rep.verdict == "false" and rep.traces == 2
    assert rep.dot == tmp_path / "cell" / "trace.dot" and rep.dot.is_file()
    assert (tmp_path / "cell" / "graph" / "trace2.dot").is_file()


def test_a_rerun_that_runs_out_of_time_is_an_outcome(tmp_path):
    runner = _Runner("", graphs=0, timed_out=True, returncode=-1)
    rep = asyncio.run(rerun(runner, _source(tmp_path), tmp_path / "cell",
                            "auth_x", timeout_s=5))
    assert rep.status == "timeout" and rep.dot is None


def test_a_rerun_that_no_longer_finds_the_attack_says_so(tmp_path):
    runner = _Runner(_UNSURE, graphs=0)
    rep = asyncio.run(rerun(runner, _source(tmp_path), tmp_path / "cell",
                            "auth_x", timeout_s=5))
    assert (rep.status, rep.verdict) == ("not_false", "unknown")


def test_a_syntax_error_on_rerun_is_a_bug(tmp_path):
    runner = _Runner('File "x.pv", line 1, characters 1-3:\nError: Syntax error.\n',
                     graphs=0, returncode=2)
    with pytest.raises(ReproductionError, match="syntax error"):
        asyncio.run(rerun(runner, _source(tmp_path), tmp_path / "cell",
                          "auth_x", timeout_s=5))


def test_a_weak_secret_rerun_reads_its_own_verdicts(tmp_path):
    src = tmp_path / "02_proverif_trace_weak_pi.pv"
    src.write_text(_WEAK_PV)
    rep = asyncio.run(rerun(_Runner(_WEAK_FALSE, graphs=0), src, tmp_path / "home",
                            "weak_pi", timeout_s=30))
    assert (rep.status, rep.verdict) == ("no_graph", "false")


def test_a_rerun_whose_answers_belong_to_no_goal_is_a_bug(tmp_path):
    with pytest.raises(ReproductionError, match="cannot be read"):
        asyncio.run(rerun(_Runner(_WEAK_FALSE), _source(tmp_path),
                          tmp_path / "home", "auth_x", timeout_s=30))


def test_a_goal_only_file_owns_every_answer_even_untagged(tmp_path):
    """The goal-only copy drops the id comment a direct secrecy query carried
    in the full model; the file holds that goal alone, so its answers are the
    goal's all the same."""
    from orrery.infra.proverif.outcome import parse_verdicts
    from orrery.modules.attacks.locate import goal_verdict
    pv = ("query attacker(new K).\n"
          "query attacker(witness_secrecy_k_K_B).\n")
    out = ("RESULT not attacker(K[!1 = v]) is false.\n"
           "RESULT not attacker(witness_secrecy_k_K_B[]) is true.\n")
    assert goal_verdict(pv, parse_verdicts(out), "secrecy_k", where="t") == "false"
