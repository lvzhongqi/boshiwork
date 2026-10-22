"""Tests for the run registry: several runs in one process, on one loop.

Everything a run does is faked; what is under test is who owns what and what
happens when the same thing is asked twice."""

import asyncio
from pathlib import Path

import pytest
from types import SimpleNamespace

from orrery.api.host import Host
from orrery.api.registry import RunRegistry
from orrery.pipeline.control.interrupts import RunControl

CFG = {"llm": {"model": "m", "api_key": "k"},
       "proverif": {"executable": "/bin/true"}}


class _Host(Host):
    """A host whose run never touches disk: it waits until interrupted."""

    def __init__(self, trace):
        super().__init__(overrides=CFG)
        self.trace = trace
        self.attached = []

    def on_event(self, e):
        pass

    async def confirm(self, plan, cost):
        return True

    def attach(self, run_dir):
        self.attached.append(str(run_dir))
        return SimpleNamespace(run_dir=run_dir)

    def make_run(self, protocol_name, protocol_dir, **kw):
        control = RunControl()
        trace = self.trace
        # A Run resolves its own name at construction — given one it takes it,
        # given none it allocates the next free one — and the registry keys its
        # entry on the result, so the stand-in has to answer that too.
        # The directory too: the registry refuses a fresh run whose directory
        # is already there, so the stand-in names one that is not.
        run_name = kw.get("run_name") or "ALLOCATED01"
        layout = SimpleNamespace(
            run_name=run_name,
            run_dir=Path(protocol_dir) / "wr" / "P" / run_name)

        async def start():
            control.bind(asyncio.get_running_loop(), asyncio.current_task())
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                trace.append(f"{kw.get('run_name')} stopped")
                raise
            return SimpleNamespace(status="ok")

        run = SimpleNamespace(start=start, control=control, layout=layout)
        self._run = run
        return run


def test_two_runs_live_side_by_side(tmp_path):
    trace, reg = [], RunRegistry()

    async def main():
        a = reg.start("NSPK01", _Host(trace), "NSPK", tmp_path)
        b = reg.start("NSSK01", _Host(trace), "NSSK", tmp_path)
        await asyncio.sleep(0.01)
        assert a.running and b.running
        assert reg.names() == ["NSPK01", "NSSK01"]
        await reg.stop_all()
        assert not a.running and not b.running

    asyncio.run(main())
    assert sorted(trace) == ["NSPK01 stopped", "NSSK01 stopped"]


def test_the_same_run_cannot_be_started_twice(tmp_path):
    """Two executions on one run directory is two writers on one ledger."""
    trace, reg = [], RunRegistry()

    async def main():
        reg.start("NSPK01", _Host(trace), "NSPK", tmp_path)
        await asyncio.sleep(0.01)
        try:
            reg.start("NSPK01", _Host(trace), "NSPK", tmp_path)
        except RuntimeError as e:
            assert "already in flight" in str(e)
        else:
            raise AssertionError("the second start was allowed")
        await reg.stop_all()

    asyncio.run(main())


def test_attaching_to_a_live_run_reuses_its_host(tmp_path):
    """The host that started a run holds its bus and its control handle. A
    second host on the same directory would be a second writer on one ledger,
    with a `seq` colliding with the first's."""
    trace, reg = [], RunRegistry()
    starter, latecomer = _Host(trace), _Host(trace)

    async def main():
        reg.start("NSPK01", starter, "NSPK", tmp_path)
        await asyncio.sleep(0.01)
        entry = reg.attach("NSPK01", latecomer, tmp_path / "NSPK01")
        assert entry.host is starter, "a second host took over a live run"
        assert starter.attached and not latecomer.attached
        await reg.stop_all()

    asyncio.run(main())


def test_attaching_to_a_finished_run_takes_the_host_it_is_given(tmp_path):
    """Nothing is holding a run that is over, so whoever asks may open it."""
    reg = RunRegistry()
    host = _Host([])
    entry = reg.attach("NSPK01", host, tmp_path / "NSPK01")
    assert entry.host is host and host.attached


def test_control_of_a_run_this_process_does_not_hold(tmp_path):
    """A page can ask twice, or ask about a run started by a different process.
    Neither is an error — it just did not happen."""
    reg = RunRegistry()
    assert reg.interrupt("nobody") is False
    assert reg.approve("nobody") is False


def test_starting_without_a_name_registers_under_the_one_the_run_took(tmp_path):
    """The ordinary launch gives no name: the engine allocates the next free
    one, and the registry keys its entry on that rather than on the None it was
    handed. The page has nowhere to navigate until it is told the name."""
    reg = RunRegistry()

    async def main():
        entry = reg.start(None, _Host([]), "NSPK", tmp_path)
        assert reg.names() == ["ALLOCATED01"]
        assert reg.get("ALLOCATED01") is entry
        reg.interrupt("ALLOCATED01")
        await asyncio.wait([entry.task])

    asyncio.run(main())


def test_forget_drops_a_run_but_never_a_live_one(tmp_path):
    """A deleted run's entry goes with it, or a later request reaches a host
    still bound to a directory that is gone. Never while it runs: the entry
    holds the interrupt handle, so losing it strands the task."""
    import pytest

    trace, reg = [], RunRegistry()

    async def main():
        host = _Host(trace)
        reg.start("R1", host, "P", tmp_path)
        with pytest.raises(RuntimeError, match="still in flight"):
            reg.forget("R1")
        reg.interrupt("R1")
        await asyncio.wait([reg.get("R1").task])
        assert reg.forget("R1") is True
        assert reg.get("R1") is None
        assert reg.forget("R1") is False        # asking twice is not an error

    asyncio.run(main())


def test_stop_waits_for_the_run_to_unwind(tmp_path):
    """`stop` returns once the run has actually unwound, which is when the next
    one may begin. `interrupt` only asks and returns, so a caller that restarted
    straight after it would have two executions on one directory."""
    trace, reg = [], RunRegistry()

    async def main():
        entry = reg.start("NSPK01", _Host(trace), "NSPK", tmp_path)
        await asyncio.sleep(0.01)
        assert entry.running
        assert await reg.stop("NSPK01") is True
        assert not entry.running          # already unwound, not merely asked
        reg.start("NSPK01", _Host(trace), "NSPK", tmp_path)   # so this is legal
        await asyncio.sleep(0.01)
        await reg.stop_all()

    asyncio.run(main())
    assert trace == ["NSPK01 stopped", "NSPK01 stopped"]


def test_stopping_a_run_that_is_not_running_is_not_an_error(tmp_path):
    """A page may ask twice, and a finished run is the ordinary case: re-entry
    is offered whatever state a run is in."""
    trace, reg = [], RunRegistry()

    async def main():
        assert await reg.stop("NSPK01") is False       # never heard of it
        reg.start("NSPK01", _Host(trace), "NSPK", tmp_path)
        await asyncio.sleep(0.01)
        await reg.stop("NSPK01")
        assert await reg.stop("NSPK01") is False       # already stopped

    asyncio.run(main())


def test_stop_gives_up_rather_than_waiting_for_ever(tmp_path):
    """A run notices its cancellation only at its next await, which a long model
    call can delay. Waiting on that inside a request would leave the page's
    button hanging, so the wait times out and says so; asking again is safe."""
    trace, reg = [], RunRegistry()

    async def main():
        entry = reg.start("NSPK01", _Stubborn(trace), "NSPK", tmp_path)
        await asyncio.sleep(0.01)
        try:
            await reg.stop("NSPK01", timeout=0.05)
        except TimeoutError as e:
            assert "has not finished unwinding" in str(e)
        else:
            raise AssertionError("it waited")
        assert entry.running                    # still going, and said so
        entry.task.cancel()
        try:
            await entry.task
        except asyncio.CancelledError:
            pass

    asyncio.run(main())


class _Stubborn(_Host):
    """A run that never notices the interrupt: the shape of one stuck in a call
    it cannot be pulled out of."""

    def make_run(self, protocol_name, protocol_dir, **kw):
        run = super().make_run(protocol_name, protocol_dir, **kw)
        control = run.control
        control.interrupt = lambda: None        # asked, and carries on
        return run


def test_a_fresh_run_under_a_taken_name_is_refused_at_the_door(tmp_path):
    """start() would raise FileExistsError inside the task, where nobody
    reads it, and the page would navigate to the old run's ledger believing
    a new one had begun. The registry asks before the task exists."""
    async def main():
        reg = RunRegistry()
        host = _Host([])
        taken = tmp_path / "wr" / "P" / "R01"
        taken.mkdir(parents=True)
        with pytest.raises(FileExistsError, match="already exists"):
            reg.start("R01", host, "P", tmp_path)
        assert reg.get("R01") is None
        # a re-entry into that directory is the one legitimate case
        entry = reg.start("R01", host, "P", tmp_path, from_node="x")
        assert entry.running
        await reg.stop("R01")

    asyncio.run(main())
