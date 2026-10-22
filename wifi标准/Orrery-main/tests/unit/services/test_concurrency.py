"""Tests for the concurrency helpers: run_capped honours its cap and returns
results in input order, and `at`/`where` keep the address of the branch a
failure escaped from on the exception itself."""

import asyncio

import pytest

from orrery.services.concurrency import at, run_all, run_capped, where


def test_cap_enforced_and_order_kept():
    async def main():
        running = 0
        peak = 0

        def make(i):
            async def job():
                nonlocal running, peak
                running += 1
                peak = max(peak, running)
                await asyncio.sleep(0.02)
                running -= 1
                return i
            return job

        results = await run_capped([make(i) for i in range(10)], limit=3)
        assert results == list(range(10))
        assert peak <= 3

    asyncio.run(main())


def test_bad_limit_rejected():
    async def main():
        with pytest.raises(ValueError):
            await run_capped([], limit=0)

    asyncio.run(main())


def test_run_all_starts_every_factory_without_a_cap():
    async def main():
        ready = asyncio.Event()
        started = 0

        def make(i):
            async def job():
                nonlocal started
                started += 1
                if started == 5:
                    ready.set()
                await ready.wait()
                return i
            return job

        assert await run_all([make(i) for i in range(5)]) == list(range(5))

    asyncio.run(main())


class Boom(RuntimeError):
    pass


def test_a_branch_names_itself_on_whatever_escapes_it():
    """A crash inside a fan-out reaches the runner carrying its branch address.
    The ledger cannot supply it: siblings interleave, so the last line before
    the crash may belong to any of them."""
    async def main():
        async def job():
            raise Boom("no closing period found")

        with pytest.raises(Boom) as ei:
            await run_capped(
                [lambda: at("scenarios/baseline/inject/Secrecy", job())],
                limit=2)
        assert where(ei.value) == "scenarios/baseline/inject/Secrecy"

    asyncio.run(main())


def test_the_innermost_branch_keeps_the_claim():
    """Levels nest, and the address is the innermost level that saw the
    failure, not the outermost one that caught it last."""
    async def main():
        async def job():
            raise Boom("x")

        async def outer():
            return await at("scenarios/baseline/inject/Secrecy/basic", job())

        with pytest.raises(Boom) as ei:
            await at("scenarios/baseline", outer())
        assert where(ei.value) == "scenarios/baseline/inject/Secrecy/basic"

    asyncio.run(main())


def test_an_untagged_exception_reports_no_place():
    """A failure on the run's serial spine carries no branch, so where()
    answers with the empty string."""
    assert where(Boom("x")) == ""
