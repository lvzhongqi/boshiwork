"""The run control handle: interrupt and manual release, both safe to call from
any thread. Nodes know nothing about either.

Interrupting is asyncio cancellation, which propagates through await points on
its own; only agent/runner (writing the interrupt marker) and the proverif
runner (killing the process group) notice it. In manual mode the engine emits
AwaitingApproval and stops at an internal gate the host opens with ``resume()``.
"""

from __future__ import annotations

import asyncio


class RunControl:
    """The handle the host holds: whoever holds it can interrupt or release the
    run. Run control is a host-level action, and expert cannot import pipeline
    at all, so it has no such power."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._approval: asyncio.Event | None = None

    # ── Engine side (called from inside run()) ──

    async def wait_approval(self, timeout_s: float | None = None) -> None:
        """Stop at the gate until the host calls resume(). A timeout (configured
        as approval_timeout_s) raises CancelledError instead of releasing, which
        would silently degrade manual mode into auto."""
        self._loop = asyncio.get_running_loop()
        self._approval = asyncio.Event()
        try:
            if timeout_s:
                await asyncio.wait_for(self._approval.wait(), timeout_s)
            else:
                await self._approval.wait()
        except TimeoutError:
            raise asyncio.CancelledError(
                f"manual release waited more than {timeout_s}s; treating it as an interrupt"
            ) from None

    # ── Host side (thread-safe, callable from any thread) ──

    def bind(self, loop: asyncio.AbstractEventLoop, task: asyncio.Task) -> None:
        """Attach the handle to the loop and task of a run that has started."""
        self._loop, self._task = loop, task

    def interrupt(self) -> None:
        """Stop everything. Recovery is a from_node re-entry."""
        if self._loop is not None and self._task is not None:
            self._loop.call_soon_threadsafe(self._task.cancel)

    def resume(self) -> None:
        """Manual release: wake the engine coroutine waiting at the
        AwaitingApproval gate."""
        if self._loop is not None and self._approval is not None:
            self._loop.call_soon_threadsafe(self._approval.set)

    @property
    def done(self) -> bool:
        """The run task has finished. False when no run has been bound yet."""
        return self._task.done() if self._task is not None else False

    @property
    def running(self) -> bool:
        """A run is in flight: a task is bound and has not finished. False
        before a run starts, so it is not the negation of ``done``."""
        return self._task is not None and not self._task.done()

    async def stopped(self) -> None:
        """Wait until the run task is really over. interrupt() only requests
        cancellation; killing the ProVerif process group and writing the
        interrupt marker happen while the run unwinds, so anything that moves
        this run's directories waits here or races a live writer. asyncio.wait
        rather than await, which would re-raise the cancellation."""
        if self._task is not None:
            await asyncio.wait({self._task})
