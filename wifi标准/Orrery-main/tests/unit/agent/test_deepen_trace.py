"""The expert's long-trace tool: it reads a reproduction the run or an earlier
question already made, and otherwise runs the cell's own solver file once and
keeps the result where the console's reproductions live."""

import asyncio
from pathlib import Path

import pytest

from orrery.agent.tools.context import ToolContext
from orrery.agent.tools.review_tools import _deepen_trace
from orrery.infra.proverif.runner import RawRun
from orrery.services.store.atomic import write_text
from orrery.services.store.layout import RunLayout

_FALSE = "RESULT inj-event(end_auth_x(a)) ==> inj-event(begin_auth_x(a)) is false.\n"
_PV = "process 0\n"


def _run(tmp_path, *, with_step: bool = False):
    lay = RunLayout(tmp_path / "wr", "P", "r1")
    lay.run_dir.mkdir(parents=True)
    lay.open_node("scenarios")
    lay.open_scenario("lowe")
    fam = lay.open_inject_family("lowe", "Authentication")
    write_text(fam / "02_proverif_trace_auth_x.pv", _PV)
    write_text(fam / "02_proverif_trace_auth_x.txt", _FALSE)
    if with_step:
        lay.open_node("reproduce_attacks")
        write_text(lay.attack_dir("lowe", "auth_x", manual=False) / "trace.txt",
                   "1st process: the step's own long trace\n")
    return lay


class _Runner:
    def __init__(self):
        self.calls = 0

    async def run(self, pv, log_to, extra_args=(), timeout_s=None):
        self.calls += 1
        where = Path(extra_args[extra_args.index("-graph") + 1])
        (where / "trace1.dot").write_text("digraph {}")
        write_text(Path(str(log_to) + ".txt"), "long display\n" + _FALSE)
        return RawRun(stdout="long display\n" + _FALSE, stderr="",
                      returncode=0, duration_s=0.1, timed_out=False)


def _ctx(lay, runner):
    return ToolContext(node="expert", artifacts_root=lay.run_dir,
                       proverif=(runner, 60) if runner else None)


def test_the_steps_own_reproduction_is_read_back(tmp_path):
    lay = _run(tmp_path, with_step=True)
    runner = _Runner()
    out = asyncio.run(_deepen_trace(_ctx(lay, runner), "lowe", "auth_x"))
    assert "the step's own long trace" in out
    assert runner.calls == 0


def test_a_cell_nobody_reproduced_is_run_once_and_kept(tmp_path):
    lay = _run(tmp_path)
    runner = _Runner()
    first = asyncio.run(_deepen_trace(_ctx(lay, runner), "lowe", "auth_x"))
    second = asyncio.run(_deepen_trace(_ctx(lay, runner), "lowe", "auth_x"))
    assert "long display" in first and first == second
    assert runner.calls == 1
    kept = lay.attack_dir("lowe", "auth_x", manual=True)
    assert (kept / "trace.txt").is_file() and (kept / "trace.dot").is_file()


def test_a_cell_that_is_not_false_says_what_would_be(tmp_path):
    lay = _run(tmp_path)
    with pytest.raises(RuntimeError, match="only a goal whose verdict is false"):
        asyncio.run(_deepen_trace(_ctx(lay, _Runner()), "lowe", "auth_y"))


def test_without_a_solver_only_an_existing_reproduction_can_be_read(tmp_path):
    lay = _run(tmp_path)
    with pytest.raises(RuntimeError, match="no solver is configured"):
        asyncio.run(_deepen_trace(_ctx(lay, None), "lowe", "auth_x"))


@pytest.mark.parametrize("scenario,goal", [("../x", "auth_x"), ("lowe", "a/b")])
def test_names_that_are_not_plain_are_refused(tmp_path, scenario, goal):
    lay = _run(tmp_path)
    with pytest.raises(RuntimeError, match="plain names"):
        asyncio.run(_deepen_trace(_ctx(lay, _Runner()), scenario, goal))
