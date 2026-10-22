"""Helpers for running batches of independent tasks concurrently.

The scenario fan-out is capped by ``pipeline.max_scenarios_concurrency``; work
inside one scenario uses ``run_all`` and has no cap. Both forms preserve input
order and cancel sibling work when a branch fails. ``at``/``where`` tag an
escaping exception with the branch it came from.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


async def _collect(factories: list[Callable[[], Awaitable]], one) -> list:
    """Run ``one(factory)`` for every factory with shared error handling."""
    try:
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(one(f)) for f in factories]
    except BaseExceptionGroup as eg:
        # The pipeline runner catches precisely (`except NodeError` /
        # `except GapRaised`), so a lone child exception is unwrapped out of
        # the group it was packed into; several stay grouped.
        flat = eg.exceptions
        while len(flat) == 1 and isinstance(flat[0], BaseExceptionGroup):
            flat = flat[0].exceptions
        if len(flat) == 1:
            raise flat[0] from None
        raise
    return [t.result() for t in tasks]


async def run_capped(factories: list[Callable[[], Awaitable]], *, limit: int) -> list:
    """Run coroutine factories, at most ``limit`` at a time, results in input
    order. Takes factories rather than coroutine objects, so the ones the
    semaphore blocks are not created — and holding resources — up front. A
    failing branch cancels its siblings, as ``asyncio.CancelledError``.

    :param limit: how many factories may run at once; must be >= 1.
    """
    if limit < 1:
        raise ValueError(f"[run_capped] limit must be >= 1, got {limit}")
    sem = asyncio.Semaphore(limit)

    async def one(factory):
        async with sem:
            return await factory()

    return await _collect(factories, one)


async def run_all(factories: list[Callable[[], Awaitable]]) -> list:
    """Run every independent factory concurrently, with no scheduling cap."""
    async def one(factory):
        return await factory()

    return await _collect(factories, one)


#: Set on an exception by the first (innermost) branch that claims it.
_STEP = "orrery_step"


async def at(step: str, coro: Awaitable):
    """Run one branch of a fan-out and tag whatever escapes it with the branch's
    identity path (``scenarios/baseline/inject/Secrecy``), the address a fix is
    aimed by. A failure is emitted from outside every branch, so it is the one
    event whose envelope cannot carry the scenario and unit by itself. The
    innermost claim wins, so the tag is the most precise level that saw it.
    """
    try:
        return await coro
    except BaseException as e:
        if not getattr(e, _STEP, None):
            setattr(e, _STEP, step)
        raise


def where(e: BaseException) -> str:
    """The step an exception escaped from, or ``""`` when no branch claimed it
    — a failure on the serial spine of the run, where the node name already
    locates it."""
    return getattr(e, _STEP, "") or ""


__all__ = ["run_all", "run_capped", "at", "where"]
