"""The run registry: one process, one event loop, several runs.

``Host`` serves one interactive session, one run in flight; a web front end
needs several at once with any tab attached to any of them. The registry is
that difference and nothing more — it holds hosts and does not know what a run
does. Everything lives on the caller's event loop; nothing here creates one.
This is api, above pipeline: the pipeline never learns it exists.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from orrery.api.host import Host
from orrery.pipeline.main import Run, RunResult


@dataclass
class Entry:
    """One run this process is holding, and the host that speaks for it."""

    host: Host
    run: Run | None = None              # None until a run is started under it
    task: asyncio.Task | None = None    # the in-flight execution, if any
    result: RunResult | None = None

    @property
    def current(self) -> Run | None:
        """The run in flight or last built under this entry. The host's, when
        it has one: a fix executed by the expert re-runs through
        ``Host.make_run`` and never comes through ``start``, so ``run`` here
        would still name the first execution while the host is on its second.
        """
        return self.host.current or self.run

    @property
    def running(self) -> bool:
        if self.task is not None and not self.task.done():
            return True
        run = self.current
        return run is not None and run.control.running


def _report_crash(name: str, task: asyncio.Task) -> None:
    if task.cancelled() or task.exception() is None:
        return
    logging.getLogger(__name__).error(
        "run %s ended in an exception before or outside its ledger: %r",
        name, task.exception())


class RunRegistry:
    """Runs by name. A name is unique inside one work root, which is what the
    run directory already guarantees."""

    def __init__(self) -> None:
        self._entries: dict[str, Entry] = {}

    def get(self, name: str) -> Entry | None:
        return self._entries.get(name)

    def names(self) -> list[str]:
        return sorted(self._entries)

    def running(self) -> frozenset[str]:
        """The runs this process is actually executing right now.

        Not the same question as ``names``: an entry also exists for an expert
        session attached to a run that finished long ago."""
        return frozenset(n for n, e in self._entries.items() if e.running)

    def attach(self, name: str, host: Host, run_dir: str | Path) -> Entry:
        """Open an expert session on a run and remember it.

        A run this process is already executing keeps its existing entry: that
        host holds its bus and control handle, and a second host bound to the
        same directory would be a second writer on one ledger.
        """
        entry = self._entries.get(name)
        if entry is None:
            entry = self._entries[name] = Entry(host=host)
        entry.host.attach(run_dir)
        return entry

    def start(self, name: str, host: Host, protocol_name, protocol_dir,
              **kw) -> Entry:
        """Construct a run under ``host`` and set it going on this loop.

        Returns as soon as the task is scheduled; whoever cares subscribes to
        the bus. Raises RuntimeError when the resolved name is already in
        flight in this process.
        """
        # Construction is what resolves the name — starting without one is
        # ordinary, the engine allocating the next free <protocol id><NN> — so
        # the duplicate check has nothing to key on until afterwards.
        run = host.make_run(protocol_name, protocol_dir, run_name=name, **kw)
        name = run.layout.run_name
        if (existing := self._entries.get(name)) is not None and existing.running:
            raise RuntimeError(
                f"run {name!r} is already in flight in this process; interrupt "
                f"it before starting it again")
        # A fresh run under a name that is taken is refused by start() with
        # FileExistsError, which would land in the task below, where nobody
        # reads it: the page would be told the name and navigate to the old
        # run's ledger. Asked here instead, before the task exists.
        if (kw.get("from_node") is None and kw.get("fork_from") is None
                and run.layout.run_dir.exists()):
            raise FileExistsError(
                f"run {name!r} already exists: {run.layout.run_dir}. A run directory "
                f"is never overwritten; leave the name blank to have the next "
                f"free one allocated, or re-enter that run with from_step")
        entry = self._entries[name] = Entry(host=host, run=run)

        async def _execute() -> RunResult:
            entry.result = await run.start()
            return entry.result

        entry.task = asyncio.get_running_loop().create_task(_execute())
        # Everything that fails after the ledger is bound is on the ledger. A
        # failure before that (start() refusing the directory, a config the
        # engine will not run from) has nowhere else to go than the log.
        entry.task.add_done_callback(lambda t: _report_crash(name, t))
        return entry

    def interrupt(self, name: str) -> bool:
        """Ask a run to stop. False when there is nothing running under that
        name, which is not an error — a page can ask twice."""
        entry = self._entries.get(name)
        if entry is None or entry.current is None or not entry.running:
            return False
        entry.current.control.interrupt()
        return True

    def approve(self, name: str) -> bool:
        """Release a run waiting at a manual-mode node boundary."""
        entry = self._entries.get(name)
        if entry is None or entry.current is None:
            return False
        entry.current.control.resume()
        return True

    def forget(self, name: str) -> bool:
        """Drop a run this process no longer holds, its directory having been
        deleted. Raises RuntimeError on one still in flight: the entry is what
        the interrupt handle hangs off, so losing it would leave the task
        running with nothing able to stop it."""
        entry = self._entries.get(name)
        if entry is None:
            return False
        if entry.running:
            raise RuntimeError(
                f"run {name!r} is still in flight; interrupt it before "
                f"dropping it")
        del self._entries[name]
        return True

    async def stop(self, name: str, *, timeout: float | None = None) -> bool:
        """Interrupt one run and wait for it to finish unwinding. False when
        nothing was running under that name.

        Two executions in one run directory is the state the store's
        immutability argument assumes cannot happen, so a caller meaning to
        restart the run waits here first. ``timeout`` bounds that wait, which a
        run holds until its next await — a ten-minute model call or a solver
        subprocess. Raises TimeoutError when it runs out.
        """
        if not self.interrupt(name):
            return False
        entry = self._entries[name]
        task = entry.task
        if task is not None and not task.done():
            done, _ = await asyncio.wait([task], timeout=timeout)
            if not done:
                raise TimeoutError(
                    f"run {name!r} was asked to stop and has not finished "
                    f"unwinding after {timeout:g}s")
            return True
        # A run the host started itself (a fix's re-run) has no task here;
        # its control handle is what says when it has unwound.
        run = entry.current
        if run is not None and run.control.running:
            try:
                await asyncio.wait_for(run.control.stopped(), timeout)
            except TimeoutError:
                raise TimeoutError(
                    f"run {name!r} was asked to stop and has not finished "
                    f"unwinding after {timeout:g}s") from None
        return True

    async def stop_all(self) -> None:
        """Interrupt every run and wait for each to finish unwinding — the
        server's shutdown path. A run moving files has to stop on its own
        rather than be killed mid-write, so this wait is unbounded."""
        for name in self.names():
            self.interrupt(name)
        tasks = [e.task for e in self._entries.values()
                 if e.task is not None and not e.task.done()]
        if tasks:
            await asyncio.wait(tasks)
        for e in self._entries.values():
            run = e.current
            if run is not None and run.control.running:
                await run.control.stopped()
