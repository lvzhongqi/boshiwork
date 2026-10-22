"""Unit tests for the runner's subprocess management: a timeout, a memory limit
and a cancellation all kill the child, and each leaves the right record.

The ProVerif binary never appears — a sleep script stands in for the slow cases
and a non-existent path for the missing-binary case, all inside tmp_path.
"""

import asyncio
import stat
import time
from pathlib import Path

import pytest

import orrery.infra.proverif.runner as runner_module
from orrery.infra.proverif.outcome import OutcomeKind, classify
from orrery.infra.proverif.runner import ProVerifRunner


@pytest.fixture()
def slow_fake_pv(tmp_path: Path) -> str:
    script = tmp_path / "fake_proverif"
    script.write_text("#!/bin/sh\nsleep 60\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_timeout_kills_and_flags(slow_fake_pv, tmp_path):
    async def main():
        runner = ProVerifRunner(executable=slow_fake_pv, timeout_s=1)
        start = time.monotonic()
        raw = await runner.run("process 0", log_to=tmp_path / "r1_typecheck")
        assert raw.timed_out is True
        assert time.monotonic() - start < 5          # killed, not waited out for 60s
        assert classify(raw).kind is OutcomeKind.TIMEOUT
        # a timeout still writes both files; the output header is the only
        # record of why there is no ProVerif output
        assert (tmp_path / "r1_typecheck.pv").read_text() == "process 0"
        assert "timed_out=True" in (tmp_path / "r1_typecheck.txt").read_text()

    asyncio.run(main())


def test_cancel_kills_subprocess(slow_fake_pv, tmp_path):
    async def main():
        runner = ProVerifRunner(executable=slow_fake_pv, timeout_s=120)
        task = asyncio.ensure_future(
            runner.run("process 0", log_to=tmp_path / "cancel_case"))
        await asyncio.sleep(0.3)
        task.cancel()
        start = time.monotonic()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert time.monotonic() - start < 5          # takes effect at once

    asyncio.run(main())


def test_memory_limit_kills_and_records(slow_fake_pv, tmp_path, monkeypatch):
    limit = 8 * 1024 ** 3
    monkeypatch.setattr(runner_module, "_memory_limit_bytes", lambda: limit)
    monkeypatch.setattr(runner_module, "_rss_bytes", lambda _pid: limit)

    async def main():
        runner = ProVerifRunner(executable=slow_fake_pv, timeout_s=120)
        start = time.monotonic()
        raw = await runner.run("process 0", log_to=tmp_path / "memory_case")
        assert raw.memory_limited is True
        assert raw.timed_out is False
        assert raw.peak_rss_bytes == limit
        assert raw.memory_limit_bytes == limit
        assert time.monotonic() - start < 5
        assert classify(raw).kind is OutcomeKind.RESOURCE_LIMIT
        text = (tmp_path / "memory_case.txt").read_text()
        assert "memory_limited=True" in text
        assert "memory_limit_mib=8192.0" in text

    asyncio.run(main())


def test_missing_rss_while_process_exits_is_not_a_crash(tmp_path, monkeypatch):
    script = tmp_path / "quick_proverif"
    script.write_text("#!/bin/sh\nsleep 0.2\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(runner_module, "_MEMORY_POLL_S", 0.01)
    monkeypatch.setattr(runner_module, "_rss_bytes", lambda _pid: None)

    async def main():
        runner = ProVerifRunner(executable=str(script), timeout_s=5)
        raw = await runner.run("process 0", log_to=tmp_path / "exit_race")
        assert raw.returncode == 0
        assert raw.timed_out is False
        assert raw.memory_limited is False
        assert raw.peak_rss_bytes == 0

    asyncio.run(main())


def test_missing_binary_raises(tmp_path):
    async def main():
        runner = ProVerifRunner(executable="/nonexistent/proverif", timeout_s=5)
        with pytest.raises(FileNotFoundError):
            await runner.run("process 0", log_to=tmp_path / "missing")

    asyncio.run(main())


GiB = 1024 ** 3


def _cgroups(tmp_path, monkeypatch, self_cgroup: str, files: dict[str, str]):
    """A fixture cgroup tree: /proc/self/cgroup's content and the limit files
    under the mount, both redirected into tmp_path."""
    root = tmp_path / "sys" / "fs" / "cgroup"
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    proc = tmp_path / "proc_self_cgroup"
    proc.write_text(self_cgroup)
    monkeypatch.setattr(runner_module, "_CGROUP_ROOT", root)
    monkeypatch.setattr(runner_module, "_SELF_CGROUP", proc)


def test_a_container_cap_bounds_the_solver_ceiling(tmp_path, monkeypatch):
    """Inside a container sysconf reports the whole host; the cgroup says what
    this process may really use. The smallest cap on the way to the root
    wins, and the ceiling is sized off it rather than off the host."""
    monkeypatch.setattr(runner_module, "_physical_memory_bytes", lambda: 64 * GiB)
    _cgroups(tmp_path, monkeypatch, "0::/docker/abc\n", {
        "docker/abc/memory.max": str(4 * GiB),
        "docker/memory.max": "max",
    })
    assert runner_module._usable_memory_bytes() == 4 * GiB
    # 65% of 4 GiB is under the floor, and the floor may not pass 90%
    assert runner_module._memory_limit_bytes() == int(4 * GiB * 0.9)


def test_cgroup_v1_and_an_unlimited_cgroup(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_module, "_physical_memory_bytes", lambda: 16 * GiB)
    _cgroups(tmp_path, monkeypatch, "12:memory:/job\n3:cpu:/job\n", {
        "memory/job/memory.limit_in_bytes": str(2 * GiB),
    })
    assert runner_module._usable_memory_bytes() == 2 * GiB
    # v1 spells "no limit" as a huge number; the host's size stands
    _cgroups(tmp_path, monkeypatch, "12:memory:/job\n", {
        "memory/job/memory.limit_in_bytes": "9223372036854771712",
    })
    assert runner_module._usable_memory_bytes() == 16 * GiB


def test_no_cgroup_keeps_the_old_ceiling_on_a_large_machine(tmp_path, monkeypatch):
    """macOS, or a Linux box with no cap: the rule is the one the paper's
    runs used wherever the machine is large enough for it."""
    monkeypatch.setattr(runner_module, "_SELF_CGROUP", tmp_path / "absent")
    monkeypatch.setattr(runner_module, "_physical_memory_bytes", lambda: 62 * GiB)
    assert runner_module._memory_limit_bytes() == int(62 * GiB * 0.65)
    monkeypatch.setattr(runner_module, "_physical_memory_bytes", lambda: 12 * GiB)
    assert runner_module._memory_limit_bytes() == 8 * GiB          # the floor
    monkeypatch.setattr(runner_module, "_physical_memory_bytes", lambda: 8 * GiB)
    # the floor used to be the whole machine here
    assert runner_module._memory_limit_bytes() == int(8 * GiB * 0.9)


def test_a_limit_file_that_is_not_a_number_is_loud(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_module, "_physical_memory_bytes", lambda: 8 * GiB)
    _cgroups(tmp_path, monkeypatch, "0::/x\n", {"x/memory.max": "lots"})
    with pytest.raises(RuntimeError, match="does not hold a memory limit"):
        runner_module._usable_memory_bytes()


def test_a_solver_that_cannot_run_is_named_for_what_is_wrong(tmp_path, monkeypatch):
    """Each way a solver setting goes wrong gets its own clause, and a real
    ProVerif, or anything answering -help the way it does, gets none."""
    from tests.fixtures import PROVERIF_STUB
    monkeypatch.setenv("PATH", str(tmp_path))                 # nothing on PATH
    assert "no program of that name is on PATH" in runner_module.solver_problem("proverif")
    assert "does not exist" in runner_module.solver_problem(str(tmp_path / "nope"))
    assert "is a directory" in runner_module.solver_problem(str(tmp_path))
    plain = tmp_path / "plain"
    plain.write_text("#!/bin/sh\necho hello\n")
    assert "not executable" in runner_module.solver_problem(str(plain))
    plain.chmod(0o755)
    said = runner_module.solver_problem(str(plain))
    assert "does not answer like ProVerif" in said and "'hello'" in said
    assert runner_module.solver_problem(str(PROVERIF_STUB)) is None
    # a bare name that is on PATH is found there
    (tmp_path / "proverif").symlink_to(PROVERIF_STUB)
    assert runner_module.solver_problem("proverif") is None
