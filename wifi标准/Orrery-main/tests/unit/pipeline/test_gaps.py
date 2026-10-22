"""Gap acceptance and rollback: the five mechanical checks passing and failing,
the side effects of a rejection and an acceptance, the runner's rollback loop,
the interrupt state, and manual release. All stubs, no LLM."""

import asyncio
import json

import pytest

from orrery.agent.tools.gap_tools import GapReport
from orrery.nodes.base import GapRaised, Node, RunEnv
from orrery.pipeline.control import gaps
from orrery.pipeline.main import Run
from orrery.services import facts
from orrery.services.store.atomic import read_jsonl_tolerant, write_text
from orrery.services.store.layout import RunLayout
from orrery.services.transcript.reader import TranscriptReader
from orrery.services.transcript.writer import TranscriptWriter


class FakeDocs:
    def __init__(self, text):
        self.text = text

    def grep(self, pattern, **kw):
        return f"§1 hit {pattern}" if pattern in self.text else \
            f"(no matches for '{pattern}' in main document)"


def _env(tmp_path, doc_text="the document has a key called K_as", budget=3,
         reject_limit=2):
    layout = RunLayout(tmp_path / "wr", "P", "r1")
    # a gap target has to have run already: its artifacts and its facts live in
    # the directory its execution opened
    layout.run_dir.mkdir(parents=True, exist_ok=True)
    for node in ("load_document", "extract_principals"):
        layout.open_node(node)
    return RunEnv(protocol_dir=tmp_path, layout=layout,
                  config={"pipeline": {"gap_budget": budget,
                                       "gap_reject_limit": reject_limit,
                                       "mode": "auto",
                                       "max_scenarios_concurrency": 2},
                          "agent": {"max_rounds": 3, "max_tool_calls": 5,
                                    "max_repairs": 1, "tool_return_chars": 1000}},
                  doc_set=FakeDocs(doc_text),
                  model_driven_names=("extract_principals",))


def _raised(tmp_path, target="extract_principals", missing="K_as"):
    tp = tmp_path / "reporter_transcript.jsonl"
    TranscriptWriter(tp).meta(node="apply")
    return GapRaised(GapReport(reporter="apply:s1", scenario="s1", target=target,
                               missing=missing, evidence="§3.1 'the key K_as'"),
                     tp, "call_9")


UP = ["load_document", "extract_principals"]


def test_verify_five_checks(tmp_path):
    env = _env(tmp_path)
    ok, _ = gaps.verify(env, _raised(tmp_path), UP)
    assert ok                                                  # all checks pass → accepted
    ok, r = gaps.verify(env, _raised(tmp_path, target="solve"), UP)
    assert not ok and "not upstream of the reporter" in r
    # a pure-code target reads no messages, so re-running it changes nothing
    ok, r = gaps.verify(env, _raised(tmp_path, target="load_document"), UP)
    assert not ok and "reads no messages" in r
    # the name is in fact in the upstream artifact
    write_text(env.layout.node_dir("extract_principals") / "principals.json",
               json.dumps({"principals": [{"name": "A", "description": "initiator"}],
                           "values": [{"name": "K_as", "derived_from": [],
                                      "description": "A's configured key"}]}))
    ok, r = gaps.verify(env, _raised(tmp_path), UP)
    assert not ok and "is in fact present" in r
    # a name only in prose the session wrote (quotes.md) is not presence:
    # downstream reads the machine artifacts, so the gap stands
    (env.layout.node_dir("extract_principals") / "principals.json").unlink()
    write_text(env.layout.node_dir("extract_principals") / "quotes.md",
               "sec 2: the K_as value is configured before the run")
    ok, _ = gaps.verify(env, _raised(tmp_path), UP)
    assert ok
    # not found in the document → rejected, because the problem is in the claims
    env2 = _env(tmp_path, doc_text="no such word here")
    ok, r = gaps.verify(env2, _raised(tmp_path, missing="K_xx"), UP)
    assert not ok and "not in the document either" in r


def test_budget_counts_only_accepted(tmp_path):
    env = _env(tmp_path, budget=1)
    v, _ = gaps.process(env, _raised(tmp_path), UP)
    assert v == "accepted"
    v, r = gaps.process(env, _raised(tmp_path), UP)          # the budget of 1 is used up
    assert v == "rejected" and "budget" in r
    entries = read_jsonl_tolerant(env.layout.run_dir / "gaps.jsonl")
    assert [e["verdict"] for e in entries] == ["accepted", "rejected"]


def test_process_side_effects(tmp_path):
    env = _env(tmp_path)
    raised = _raised(tmp_path)
    v, _ = gaps.process(env, raised, UP)
    assert v == "accepted"
    # accepted: filed as a fact in the target's own directory, the copy a fresh
    # session reads at prompt build
    got = facts.read(env.layout.node_dir("extract_principals"))
    assert got and "K_as" in got[0].text and got[0].source == "gap:apply:s1"
    # no session exists at the target's node path, so none is created
    assert not env.layout.node_transcript("extract_principals").exists()
    # rejected: the diagnosis goes back into the reporter's transcript as a
    # paired tool_result
    raised2 = _raised(tmp_path, target="solve")
    v, _ = gaps.process(env, raised2, UP)
    assert v == "rejected"
    rep = TranscriptReader(raised2.transcript_path).entries()
    tr = [e for e in rep if e["t"] == "tool_result"]
    assert tr and tr[-1]["tool_call_id"] == "call_9" and "gap rejected" in tr[-1]["content"]


def test_acceptance_posts_into_a_live_session(tmp_path):
    """When the target keeps a session at its node path, the acceptance lands
    there too — the data side of resuming it."""
    env = _env(tmp_path)
    TranscriptWriter(env.layout.node_transcript("extract_principals")).meta(node="e")
    v, _ = gaps.process(env, _raised(tmp_path), UP)
    assert v == "accepted"
    tgt = TranscriptReader(env.layout.node_transcript("extract_principals")).entries()
    assert any("K_as" in e.get("content", "") for e in tgt if e["t"] == "user")


def test_rejections_are_capped(tmp_path):
    # a rejection re-runs the reporting node, so an unbounded loop burns tokens;
    # past the limit the run stops instead of circling
    env = _env(tmp_path, reject_limit=2)
    bad = lambda: _raised(tmp_path, target="solve")           # noqa: E731  not upstream → always rejected
    assert gaps.process(env, bad(), UP)[0] == "rejected"
    v, r = gaps.process(env, bad(), UP)
    assert v == "exhausted" and "circling" in r
    # the second rejection is still recorded — the ledger shows why the run died
    entries = read_jsonl_tolerant(env.layout.run_dir / "gaps.jsonl")
    assert [e["verdict"] for e in entries] == ["rejected", "rejected"]


# ── the runner's rollback loop, with stub nodes ──

class UpNode(Node):
    name = "up"
    model_driven = True         # a legal gap target: it can read the message
    def __init__(self):
        self.runs = 0
    def is_done(self, env):
        return (env.layout.node_dir("up") / "out.txt").exists()
    async def run(self, env):
        self.runs += 1
        write_text(env.layout.node_dir("up") / "out.txt",
                   f"v{self.runs}" + (" K_as" if self.runs > 1 else ""))


class DownNode(Node):
    name = "down"
    def __init__(self):
        self.runs = 0
    def is_done(self, env):
        return (env.layout.node_dir("down") / "out.txt").exists()
    async def run(self, env):
        self.runs += 1
        up = (env.layout.node_dir("up") / "out.txt").read_text()
        if "K_as" not in up:
            tp = env.layout.node_dir("down") / "transcript.jsonl"
            TranscriptWriter(tp).meta(node="down")
            raise GapRaised(GapReport("down", None, "up", "K_as", "§1"), tp, "c1")
        write_text(env.layout.node_dir("down") / "out.txt", "done")


def _ov(tmp_path):
    return {"llm": {"backend": "stub",
                    "profiles": {"stub": {"api_key": "k", "model": "x"}}},
            "proverif": {"executable": "/bin/true"},
            "paths": {"work_root": str(tmp_path / "wr")}}


def test_runner_gap_rollback_loop(tmp_path, monkeypatch):
    # doc_set is None, so verify skips the document check. up's first version
    # has no K_as, so down reports a gap; it is accepted, up runs again into a
    # directory of its own, and down follows it and passes.
    up, down = UpNode(), DownNode()
    r = asyncio.run(Run("P", tmp_path, _ov(tmp_path), table=[up, down]).start())
    assert r.status == "ok"
    assert up.runs == 2 and down.runs == 2
    # the run reads as what happened: forward, back to up, forward again
    assert [d.name for d in sorted(r.run_dir.iterdir()) if d.is_dir()] == [
        "01_up", "02_down", "03_up", "04_down"]
    # the first attempt stays where it was, and the message that sent the
    # pipeline back is carried into the attempt that had to read it
    assert (r.run_dir / "01_up" / "out.txt").read_text().startswith("v1")
    assert any("K_as" in f.text and f.source.startswith("gap:")
               for f in facts.read(r.run_dir / "03_up"))
    assert not (r.run_dir / "_history").exists()
    assert json.loads((r.run_dir / "gaps.jsonl").read_text().splitlines()[0]
                      )["verdict"] == "accepted"


def test_interrupt_flushes_status(tmp_path):
    class Slow(Node):
        name = "slow"
        def is_done(self, env):
            return False
        async def run(self, env):
            await asyncio.sleep(30)

    async def main():
        run = Run("P", tmp_path, _ov(tmp_path), table=[Slow()])
        task = asyncio.get_running_loop().create_task(run.start())
        await asyncio.sleep(0.2)
        run.control.interrupt()
        with pytest.raises(asyncio.CancelledError):
            await task
        return run.run_dir          # the name is allocated, so ask the run for it

    rj = json.loads((asyncio.run(main()) / "run.json").read_text())
    assert rj["status"] == "interrupted"


def test_manual_awaits_approval_per_node(tmp_path):
    """In manual mode AwaitingApproval is emitted at each node boundary and the
    engine stops at the gate, which the host opens through run.control."""
    from orrery.services.events import AwaitingApproval

    stops = []
    ov = _ov(tmp_path)
    ov["pipeline"] = {"mode": "manual"}
    run = Run("P", tmp_path, ov, table=[UpNode()])

    def on_event(e):
        if isinstance(e, AwaitingApproval):
            stops.append(e.node)
            # resume cannot be called synchronously inside the callback (the
            # gate does not exist yet), so it is scheduled for the next tick
            asyncio.get_running_loop().call_soon(run.control.resume)

    run.bus.subscribe(on_event)
    asyncio.run(run.start())
    assert stops == ["up"]

    # auto mode neither stops nor emits the event
    stops.clear()
    ov["pipeline"]["mode"] = "auto"
    run2 = Run("P", tmp_path, ov, table=[UpNode()], run_name="r2")
    run2.bus.subscribe(on_event)
    asyncio.run(run2.start())
    assert stops == []

    # manual with no subscriber: nobody could see AwaitingApproval, so it is an
    # explicit error
    ov["pipeline"]["mode"] = "manual"
    with pytest.raises(ValueError, match="subscriber"):
        asyncio.run(Run("P", tmp_path, ov, table=[UpNode()], run_name="r3").start())
