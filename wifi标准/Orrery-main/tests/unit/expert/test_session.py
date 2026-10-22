"""The expert long session against a fake LLM: the answer path, the plan path,
filling in the tool_result, and continuing the session."""

import asyncio
import json
from pathlib import Path

from orrery.expert.session import ExpertSession
from orrery.infra.llm.client import ChatClient, ChatResponse, TokenUsage
from orrery.services.transcript.reader import TranscriptReader


class FakeChat(ChatClient):
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def invoke(self, messages, **kw):
        self.calls.append(list(messages))
        return self.script.pop(0)


def _resp(content="", tool_calls=None):
    return ChatResponse(content=content, usage=TokenUsage(),
                        tool_calls=tool_calls or [])


def _fix_call(step="extract_principals"):
    args = {"step": step, "mode": "resume", "message": "add S",
            "directive": False, "rationale": "an entity was missed"}
    return {"id": "fx1", "type": "function", "name": "propose_fix",
            "arguments": json.dumps(args), "arguments_json": args}


CFG = {"expert": {"max_rounds": 4, "max_tool_calls": 6},
       "agent": {"max_rounds": 4, "max_tool_calls": 6, "max_repairs": 1,
                 "tool_return_chars": 2000},
       "llm": {"backend": "stub", "model": "x", "api_key": "k"}}


def _mk_run(tmp_path) -> Path:
    proto = tmp_path / "proto"
    (proto / "source" / "main").mkdir(parents=True)
    (proto / "source" / "main" / "toy.md").write_text(
        "# 1 Intro\n\nA and B exchange nonces.\n")
    run_dir = tmp_path / "wr" / "proto" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({
        "protocol": "proto", "protocol_id": "proto",
        "protocol_dir": str(proto),
        "run_name": "r1", "nodes": {}, "status": "ok"}))
    # open_node records the directory in the index, which is what marks it as
    # this step's current one.
    from orrery.services.store.layout import RunLayout
    lay = RunLayout(tmp_path / "wr", "proto", "r1")
    d = lay.open_node("extract_principals")
    (d / "principals.json").write_text('{"A": "initiator", "B": "responder"}')
    return run_dir


def test_the_layout_follows_the_protocol_identity_not_its_name(tmp_path):
    """A run directory is named by the protocol's identity, which for a bundle
    or a versioned entry is not the protocol's name."""
    run_dir = tmp_path / "wr" / "EDHOC-draft-08-symmetric" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({
        "protocol": "EDHOC", "protocol_id": "EDHOC-draft-08-symmetric",
        "version": "draft-08", "subprotocol": "symmetric",
        "protocol_dir": str(tmp_path), "run_name": "r1", "status": "ok"}))

    s = ExpertSession(run_dir, CFG, FakeChat([]))
    assert s.layout.run_dir == run_dir
    assert s.layout.run_json.exists()


def test_reply_plan_resolve_and_continuity(tmp_path):
    run_dir = _mk_run(tmp_path)
    llm = FakeChat([
        _resp(content="Because §1 of the document mentions only A and B."),
        _resp(tool_calls=[_fix_call()]),
        _resp(content="Sure, anything else?"),
    ])
    s = ExpertSession(run_dir, CFG, llm)

    r1 = asyncio.run(s.handle("why are A and B the only entities?"))
    assert r1.kind == "reply" and "§1" in r1.text

    r2 = asyncio.run(s.handle("add S to the entities"))
    assert r2.kind == "plan"
    assert r2.plan.step == "extract_principals" and r2.plan.mode == "resume"

    s.resolve_plan("the plan was executed")                    # fill in the tool_result
    r3 = asyncio.run(s.handle("thanks"))
    assert r3.kind == "reply"
    # the session continues: the third request carries the whole history,
    # including the paired tool_use and tool_result
    msgs = llm.calls[2]
    kinds = [m.role.value for m in msgs]
    assert kinds.count("user") >= 3 and "tool" in kinds
    # the expert transcript lives in an underscore domain, invisible to the
    # pipeline
    entries = TranscriptReader(run_dir / "_expert" / "transcript.jsonl").entries()
    assert any(e["t"] == "tool_result" and "was executed" in e["content"]
               for e in entries)


def test_turns_are_serialised(tmp_path):
    """Two messages arriving together queue instead of sharing one baseline:
    each is answered once, and the second turn sees the first's answer."""
    run_dir = _mk_run(tmp_path)

    class SlowChat(FakeChat):
        def __init__(self):
            super().__init__([])
            self.n = 0

        async def invoke(self, messages, **kw):
            self.n += 1
            self.calls.append(list(messages))
            await asyncio.sleep(0.02)          # a real round trip is not instant
            return _resp(content=f"reply {self.n}")

    llm = SlowChat()
    s = ExpertSession(run_dir, CFG, llm)
    asyncio.run(_both(s))

    kinds = [(e["t"], e.get("content"))
             for e in TranscriptReader(run_dir / "_expert" / "transcript.jsonl").entries()
             if e["t"] in ("user", "assistant")]
    # each user message carries the run-state block in front of it
    assert [k for k, _ in kinds] == ["user", "assistant", "user", "assistant"]
    assert kinds[0][1].endswith("one") and kinds[2][1].endswith("two")
    assert [c for k, c in kinds if k == "assistant"] == ["reply 1", "reply 2"]
    # the second turn was sent the first turn's exchange
    assert any(m.content == "reply 1" for m in llm.calls[1])


async def _both(s):
    return await asyncio.gather(s.handle("one"), s.handle("two"))


def test_a_pending_plan_blocks_the_next_message(tmp_path):
    """The plan's tool_call is answered by resolve_plan; a turn slipping in
    between would separate the call from its result, which the API rejects."""
    run_dir = _mk_run(tmp_path)
    llm = FakeChat([_resp(tool_calls=[_fix_call()]), _resp(content="later")])
    s = ExpertSession(run_dir, CFG, llm)

    assert asyncio.run(s.handle("fix it")).kind == "plan"
    blocked = asyncio.run(s.handle("and another thing"))
    assert blocked.kind == "failed" and "waiting for your decision" in blocked.text

    s.resolve_plan("executed")
    assert asyncio.run(s.handle("and another thing")).kind == "reply"


def test_every_session_of_the_run_is_readable(tmp_path):
    """Discovery walks the whole tree: the scenario stage nests its sessions
    three levels down, and those are the ones that wrote scenario.pv and
    model.pv."""
    run_dir = _mk_run(tmp_path)
    for rel in ("03_extract_principals",
                "08_scenarios/lowe/apply/01_lkr_from_start",
                "08_scenarios/lowe/inject/Secrecy",
                "_expert"):
        d = run_dir / rel
        d.mkdir(parents=True, exist_ok=True)
        (d / "transcript.jsonl").write_text('{"t": "meta"}\n', encoding="utf-8")

    keys = ExpertSession(run_dir, CFG, FakeChat([]))._transcripts()
    assert set(keys) == {"extract_principals",
                         "scenarios/lowe/apply/01_lkr_from_start",
                         "scenarios/lowe/inject/Secrecy"}
    # the underscore domain stays out: the expert's own conversation is not
    # evidence
    assert all("_expert" not in str(p) for p in keys.values())


def test_executed_notice_names_the_stale_artifacts(tmp_path):
    """The notice names the artifact paths that went stale, and caps the list
    when a step replaced many files."""
    from orrery.expert.session import executed_notice

    text = executed_notice("extract_flow", ["06_extract_flow/flow.pv",
                                              "results.json"])
    assert "06_extract_flow/flow.pv" in text and "results.json" in text
    assert "out of date" in text

    many = executed_notice("claims", [f"f{i}.json" for i in range(20)])
    assert "and 8 more" in many                    # capped, and says so
    assert "no artifact was replaced" in executed_notice("claims", [])


def test_an_empty_step_is_rejected_in_the_session(tmp_path):
    """A plan with no step would file the message where no session reads it.
    The tool rejects it, and the rejection comes back as a tool_result so the
    model corrects the call itself."""
    run_dir = _mk_run(tmp_path)
    llm = FakeChat([
        _resp(tool_calls=[_fix_call(step="")]),
        _resp(content="Right — the step path was missing."),
    ])
    r = asyncio.run(ExpertSession(run_dir, CFG, llm).handle("fix scenario lowe"))
    assert r.kind == "reply"
    entries = TranscriptReader(run_dir / "_expert" / "transcript.jsonl").entries()
    assert any(e["t"] == "tool_result" and "step is required" in e["content"]
               for e in entries)


def test_the_session_reports_its_rounds(tmp_path):
    """Given a bus, the session emits rounds and tool calls under the node name
    "expert" and appends them to the run's ledger. run_agent only builds the
    delta sink when an emitter is present, so streamed fragments hang off the
    same bus."""
    from orrery.services.events import EventBus

    run_dir = _mk_run(tmp_path)
    seen = []
    bus = EventBus(run_dir / "events.jsonl")
    bus.subscribe(seen.append)
    llm = FakeChat([_resp(content="§1 names only A and B.")])

    asyncio.run(ExpertSession(run_dir, CFG, llm, bus=bus).handle("why?"))

    kinds = [type(e).__name__ for e in seen]
    assert "RoundStarted" in kinds
    assert {e.node for e in seen} == {"expert"}      # not a step of the pipeline
    # and it landed in the run's own ledger, so a late reader can replay it
    assert "round_started" in (run_dir / "events.jsonl").read_text(encoding="utf-8")


def test_without_a_bus_the_session_is_silent(tmp_path):
    """The headless path — a script attaching to a run — answers normally and
    writes no event ledger."""
    run_dir = _mk_run(tmp_path)
    llm = FakeChat([_resp(content="answer")])
    r = asyncio.run(ExpertSession(run_dir, CFG, llm).handle("why?"))
    assert r.kind == "reply"
    assert not (run_dir / "events.jsonl").exists()


def test_sealed_sessions_are_readable_history(tmp_path):
    """A superseded attempt's transcript seals into its directory's slot band
    (NN_transcript.jsonl); discovery keys it under the step's own name, so
    earlier attempts stay readable alongside the current one."""
    run_dir = _mk_run(tmp_path)
    d = run_dir / "04_extract_flow"
    d.mkdir()
    (d / "transcript.jsonl").write_text("{}")
    (d / "02_transcript.jsonl").write_text("{}")
    keys = ExpertSession(run_dir, CFG, FakeChat([]))._transcripts()
    assert "extract_flow" in keys
    assert "extract_flow/02_transcript.jsonl" in keys


def test_read_expected_appears_only_when_the_run_has_a_corpus():
    """read_expected is in the expert's tool list only when the run recorded a
    corpus; the rest of the list is identical either way. A corpus-less run
    lacks the tool entirely, so the model is never told the subject exists."""
    from orrery.expert.session import build_prompt

    without = [t.name for t in build_prompt(has_truth=False).tools]
    with_ = [t.name for t in build_prompt(has_truth=True).tools]
    assert "read_expected" not in without
    assert "read_expected" in with_
    assert [n for n in with_ if n != "read_expected"] == without


def test_the_corpus_side_has_exactly_one_door_but_the_comparison_does_not(tmp_path):
    """The corpus's own files (results, cases) sit outside the run directory on
    a path layout does not expose, so read_expected is the only way in. The
    comparison against them is cross_check's artifact inside the run directory,
    reached by read_artifact and absent from read_expected's enum."""
    import json as _json
    from orrery.agent.tools.context import ToolContext
    from orrery.agent.tools.truth_tools import TRUTH_TOOLS

    (tmp_path / "10_cross_check").mkdir()
    (tmp_path / "10_cross_check" / "cross_check.json").write_text(
        _json.dumps({"acc": 1.0, "results": []}), encoding="utf-8")
    corpus = tmp_path / "corpus"
    (corpus / "results").mkdir(parents=True)
    (corpus / "results" / "results.json").write_text(
        _json.dumps({"protocol_id": "X", "results": []}), encoding="utf-8")

    ctx = ToolContext(node="expert", artifacts_root=tmp_path, ground_truth=corpus)
    read = TRUTH_TOOLS[0].handler
    assert "protocol_id" in read(ctx, which="results", from_line=None, to_line=None)
    assert "comparison" not in TRUTH_TOOLS[0].parameters.properties["which"].enum
    # the comparison is an ordinary artifact, reachable the plain way
    assert "acc" in ctx.resolve_artifact(
        "10_cross_check/cross_check.json").read_text(encoding="utf-8")
    # with no corpus the tool refuses
    bare = ToolContext(node="expert", artifacts_root=tmp_path)
    try:
        read(bare, which="results", from_line=None, to_line=None)
        raise AssertionError("answered without a corpus")
    except RuntimeError as e:
        assert "not given a corpus" in str(e)


def test_a_session_on_a_run_given_its_own_document_reads_that_document(tmp_path):
    """A run started on a reader's own file has no corpus layout under its
    protocol_dir — that directory is simply where the file happened to sit. The
    session reads what the run was handed, off the record load_document reads,
    or discovery raises and it cannot answer a single question about the run."""
    doc = tmp_path / "Desktop" / "NSPK.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("# 1 Intro\n\nA and B exchange nonces.\n", encoding="utf-8")
    run_dir = tmp_path / "wr" / "NSPK" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({
        "protocol": "NSPK", "protocol_id": "NSPK", "run_name": "r1",
        "protocol_dir": str(doc.parent),
        "documents": {"main": str(doc), "refs": []},
        "status": "failed"}), encoding="utf-8")

    s = ExpertSession(run_dir, CFG, FakeChat([]))
    ctx = asyncio.run(s._ctx())
    assert ctx.doc_set.main_doc_id == "NSPK"
