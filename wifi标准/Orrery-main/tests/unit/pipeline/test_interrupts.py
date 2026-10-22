"""RunControl: what "the run has stopped" means.

interrupt() only requests cancellation; the run then unwinds, killing the
ProVerif process group and writing its interrupt marker. stopped() waits for
that unwinding to finish.
"""

import asyncio

from orrery.pipeline.control.interrupts import RunControl


def test_running_is_false_before_a_run_starts():
    c = RunControl()
    assert not c.running and not c.done      # not bound yet: neither running nor finished


def test_stopped_waits_for_the_unwinding_and_does_not_raise():
    trace: list[str] = []

    async def main():
        async def fake_run():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                await asyncio.sleep(0.05)    # unwinding: kill subprocesses, write the marker
                trace.append("run unwound")
                raise

        task = asyncio.ensure_future(fake_run())
        c = RunControl()
        c.bind(asyncio.get_running_loop(), task)
        await asyncio.sleep(0.01)
        assert c.running

        c.interrupt()
        await c.stopped()                    # returns instead of re-raising the cancellation
        trace.append("directories moved")
        assert not c.running and c.done

    asyncio.run(main())
    assert trace == ["run unwound", "directories moved"]
