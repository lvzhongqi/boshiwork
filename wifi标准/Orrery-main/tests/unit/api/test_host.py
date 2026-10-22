"""Tests for the host's fix loop: a run in flight is stopped before its
directories move, and only after the user has confirmed. Everything around
that ordering is faked.
"""

import asyncio
from types import SimpleNamespace

from orrery.agent.tools.expert_tools import FixPlan
from orrery.api.host import Host
from orrery.expert.session import ExpertReply
from orrery.pipeline.control.interrupts import RunControl
from orrery.services.events import AwaitingConfirm
from orrery.services.store.atomic import write_json, write_text
from orrery.services.store.layout import RunLayout
from tests.fixtures import PROVERIF_STUB

# A real backend name: attaching an expert session builds an actual chat
# client, and the factory only accepts backends it knows.
CFG = {"llm": {"backend": "remote-claude",
               "profiles": {"remote-claude": {"api_key": "k", "model": "m"}}},
       "proverif": {"executable": str(PROVERIF_STUB)}}

_CLAIM_FILES = ("assumptions", "properties", "claims")


class _Session:
    """Just enough ExpertSession for chat(): proposes one plan, then records
    what it was told about the outcome."""

    def __init__(self, layout, protocol_dir, trace):
        self.layout = layout
        self.protocol_dir = protocol_dir
        self.protocol = layout.protocol
        self.trace = trace
        self.outcome = None

    async def handle(self, text):
        return ExpertReply(kind="plan", text="because",
                           plan=FixPlan("extract_principals", "resume", text))

    def resolve_plan(self, outcome):
        self.trace.append("superseded")     # execute() has moved the directories
        self.outcome = outcome


class _Host(Host):
    def __init__(self, trace):
        super().__init__(overrides=CFG)
        self.trace = trace

    def on_event(self, e):
        pass

    async def confirm(self, plan, cost):
        self.trace.append("confirmed")
        return True

    def make_run(self, protocol_name, protocol_dir, **kw):
        self.trace.append(f"restarted from {kw.get('from_node')}")
        self.kw = kw
        return SimpleNamespace(
            start=_result, control=RunControl(),
            run_dir=self._session.layout.run_dir)


async def _result():
    return SimpleNamespace(status="ok", failure="")


def _layout(tmp_path, **meta):
    lay = RunLayout(tmp_path / "wr", "NSPK", "NSPK")
    lay.run_dir.mkdir(parents=True, exist_ok=True)
    write_text(lay.open_node("extract_principals") / "principals.json", "{}")
    write_json(lay.run_json, {"protocol": "NSPK", "protocol_id": "NSPK",
                              "protocol_dir": str(tmp_path),
                              "run_name": "NSPK", "nodes": {},
                              "status": "running", **meta})
    return lay


def test_a_run_in_flight_is_stopped_before_anything_moves(tmp_path):
    trace: list[str] = []
    host = _Host(trace)
    lay = _layout(tmp_path)
    host._session = _Session(lay, tmp_path, trace)

    async def main():
        async def fake_run():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                trace.append("run stopped")
                raise

        task = asyncio.ensure_future(fake_run())
        control = RunControl()
        control.bind(asyncio.get_running_loop(), task)
        host._run = SimpleNamespace(control=control)
        await asyncio.sleep(0.01)

        reply = await host.chat("the entities are wrong")
        trace.append("done")
        assert "interrupted first" in reply, reply

    asyncio.run(main())
    # the three steps of the contract, in order: stop, then execute, then restart
    assert trace == ["confirmed", "run stopped", "superseded",
                     "restarted from extract_principals", "done"]
    # nothing moves: the fix files a message and names a re-entry point, and the
    # earlier work stops being current when the re-run writes past it
    assert (lay.node_dir("extract_principals") / "principals.json").exists()
    # the session is told which step's work is about to be replaced, so its next
    # answer reads the file again instead of quoting the old text
    assert "extract_principals" in host._session.outcome


def test_the_rerun_gets_claims_inputs_the_fix_cannot_move(tmp_path):
    """A fix at or before extract_claims makes the run's own copy of the three
    claim files stop being current, so the re-run must be handed the paths
    run.json records instead: those live in the corpus, outside the run
    directory, where nothing the fix does can move them.
    """
    trace: list[str] = []
    host = _Host(trace)
    lay = _layout(tmp_path, **{f: str(tmp_path / "claims" / f"{f}.json")
                               for f in _CLAIM_FILES})
    claims_dir = lay.open_node("extract_claims")
    for f in _CLAIM_FILES:
        write_text(tmp_path / "claims" / f"{f}.json", "{}")
        write_text(claims_dir / f"{f}.json", "{}")               # the run's own copy
    host._session = _Session(lay, tmp_path, trace)

    asyncio.run(host.chat("the entities are wrong"))

    # the run's own copy is among the work the re-entry replaces, so it is
    # exactly the path the re-run must not be handed
    assert lay.rel(claims_dir) in host._session.outcome
    for f in _CLAIM_FILES:
        assert host.kw[f].exists(), f
        assert not host.kw[f].is_relative_to(lay.run_dir), f


def test_a_missing_claims_input_stays_missing_and_a_dead_path_is_loud(tmp_path):
    """A run that never had an input re-runs without one; the run's own copy
    under the claims step is never substituted for it. A recorded path that no
    longer resolves raises, because a silent None would flip the re-run into
    extraction mode and answer a different question."""
    import pytest

    trace: list[str] = []
    host = _Host(trace)
    lay = _layout(tmp_path)
    write_text(lay.open_node("extract_claims") / "claims.json", "{}")
    host._session = _Session(lay, tmp_path, trace)

    asyncio.run(host.chat("the entities are wrong"))
    assert host.kw["claims"] is None            # never recorded, and not invented
    assert host.kw["assumptions"] is None

    host2 = _Host(trace)
    lay2 = _layout(tmp_path / "second",
                   claims=str(tmp_path / "second" / "gone.json"))
    host2._session = _Session(lay2, tmp_path / "second", trace)
    with pytest.raises(FileNotFoundError, match="does not resolve"):
        asyncio.run(host2.chat("the entities are wrong"))


def test_no_run_in_flight_is_not_an_error(tmp_path):
    trace: list[str] = []
    host = _Host(trace)
    host._session = _Session(_layout(tmp_path), tmp_path, trace)
    reply = asyncio.run(host.chat("the entities are wrong"))
    assert "interrupted first" not in reply
    assert trace == ["confirmed", "superseded", "restarted from extract_principals"]


def test_two_messages_do_not_overlap(tmp_path):
    """`ExpertSession._turn` only guards the model round. Everything after it —
    pricing, halting, archiving, restarting — must not run bare."""
    trace: list[str] = []

    class _SlowHost(_Host):
        """Confirmation is where a real user is slowest, so the overlap, if
        there is one, is widest here."""

        def __init__(self, trace):
            super().__init__(trace)
            self.inflight = 0
            self.peak = 0

        async def confirm(self, plan, cost):
            self.inflight += 1
            self.peak = max(self.peak, self.inflight)
            await asyncio.sleep(0.02)
            self.inflight -= 1
            return True

    host = _SlowHost(trace)
    host._session = _Session(_layout(tmp_path), tmp_path, trace)

    async def main():
        await asyncio.gather(host.chat("one"), host.chat("two"))

    asyncio.run(main())
    assert host.peak == 1, "the two turns overlapped"
    assert trace.count("restarted from extract_principals") == 2   # both ran


def test_attach_binds_the_run_s_own_ledger(tmp_path):
    """The expert speaks when no pipeline is running, and a durable emit on an
    unbound bus raises. Binding here lets its rounds, and the question a
    stopped run waits on, reach the stream the pipeline writes."""
    from orrery.services.store.atomic import read_jsonl_tolerant

    lay = _layout(tmp_path)
    host = _Host([])
    host.attach(lay.run_dir)

    host.emit(AwaitingConfirm(run="NSPK", node="expert",
                               plan_digest="d", cost_digest="c"))
    rows = read_jsonl_tolerant(lay.run_dir / "events.jsonl")
    assert [r["t"] for r in rows] == ["awaiting_confirm"]
    assert rows[0]["seq"] == 0 and rows[0]["node"] == "expert"


def test_attach_does_not_open_a_second_bus_on_a_live_run(tmp_path):
    """Two buses on one events.jsonl each keep their own seq, so they hand out
    colliding numbers — and seq is what a reader resumes from."""
    lay = _layout(tmp_path)
    host = _Host([])
    live = SimpleNamespace(control=RunControl(), bus=object())
    host._run = live

    host.attach(lay.run_dir)
    assert host._bus is live.bus
    assert not (lay.run_dir / "events.jsonl").exists()   # nothing rebound it


class _Plain(Host):
    """A host with the real make_run; these two tests are about which bus a
    constructed run ends up holding."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.seen = []

    def on_event(self, e):
        self.seen.append(e)

    async def confirm(self, plan, cost):
        return True


def _plain(lay):
    return _Plain(overrides={**CFG, "paths": {"work_root": str(lay.root)}})


def test_a_re_entry_takes_over_the_bus_already_on_that_ledger(tmp_path):
    """A re-entry is a second Run over a ledger this host may already have
    bound (the console's retry, an accepted fix plan), so it takes that bus
    over instead of the fresh one the engine built. Two buses on one
    events.jsonl each keep their own seq and hand out colliding numbers, and a
    console already subscribed to the first bus would go silent for the retry.
    """
    lay = _layout(tmp_path)
    host = _plain(lay)
    host.attach(lay.run_dir)
    bound = host._bus

    run = host.make_run("NSPK", tmp_path, run_name="NSPK",
                        from_node="extract_principals")
    assert run.bus is bound

    # taken over, not subscribed twice: attach() already put on_event on it
    run.bus.emit(AwaitingConfirm(run="NSPK", node="expert",
                                 plan_digest="d", cost_digest="c"))
    assert len(host.seen) == 1


def test_a_run_on_a_different_ledger_gets_its_own_bus(tmp_path):
    """The takeover is keyed on the ledger, not on the host: a host that
    started a different run and reused the bus would write that run's events
    into the first one's events.jsonl."""
    lay = _layout(tmp_path)
    host = _plain(lay)
    host.attach(lay.run_dir)
    bound = host._bus

    other = host.make_run("NSPK", tmp_path, run_name="NSPK02")
    assert other.bus is not bound
    assert other.bus.path is None            # start() binds it, and to its own


def test_a_question_stopped_while_its_plan_waits_still_answers_the_plan(tmp_path):
    """The proposal is a tool_use, and the session refuses every later message
    until it is answered. Stopping the question while the confirmation card
    is up (or while the run unwinds) cancels the turn, and the plan has to be
    resolved on that way out too, or nothing on the page can ever clear it."""
    trace: list[str] = []

    class _Waits(_Host):
        async def confirm(self, plan, cost):
            trace.append("waiting")
            await asyncio.get_running_loop().create_future()   # never decided

    host = _Waits(trace)
    lay = _layout(tmp_path)
    session = _Session(lay, tmp_path, trace)
    host._session = session
    # heavy: the fix supersedes the step that is current, so a decision is asked
    import orrery.api.host as host_mod
    real_estimate = host_mod.fixes.estimate
    host_mod.fixes.estimate = lambda layout, plan: SimpleNamespace(
        heavy=True, superseded=["01_extract_principals"], reruns=["x"],
        from_node="extract_principals")

    async def main():
        task = asyncio.ensure_future(host.chat("the entities are wrong"))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    try:
        asyncio.run(main())
    finally:
        host_mod.fixes.estimate = real_estimate
    assert trace == ["waiting", "superseded"]
    assert "stopped" in session.outcome and "not executed" in session.outcome
