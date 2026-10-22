"""run_agent's deterministic branches: a scripted fake LLM walks each exit in
turn."""

import asyncio

import pytest

from orrery.agent.budget import LoopBudget
from orrery.agent.runner import GiveUpSpec, SubmitSpec, run_agent
from orrery.agent.tools.context import ToolContext
from orrery.agent.tools.gap_tools import gap_tool
from orrery.agent.tools.registry import ToolDef
from orrery.infra.llm.client import (
    ChatClient, ChatResponse, FunctionParameter, TokenUsage, ToolChoiceMode,
)
from orrery.services.transcript.reader import TranscriptReader
from orrery.services.transcript.resume import load_messages
from orrery.services.transcript.writer import TranscriptWriter


class FakeChat(ChatClient):
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.calls_tools = []      # the tool menu offered each round
        self.calls_schema = []     # the json_schema sent each round, if any
        self.calls_tool_choice = []

    async def invoke(self, messages, tools=None, tool_choice=None, temperature=0,
                     response_format=None, json_schema=None, **kw) -> ChatResponse:
        self.calls.append(list(messages))
        self.calls_tools.append(list(tools or []))
        self.calls_schema.append(json_schema)
        self.calls_tool_choice.append(tool_choice)
        return self.script.pop(0)


def _resp(content="", tool_calls=None, thinking=None):
    return ChatResponse(content=content, usage=TokenUsage(),
                        tool_calls=tool_calls or [], thinking=thinking)


def _tc(name, args, id_="call_1"):
    import json
    return {"id": id_, "type": "function", "name": name,
            "arguments": json.dumps(args), "arguments_json": args}


ECHO = ToolDef(name="echo", description="echo it back",
               parameters=FunctionParameter(type="object", properties={
                   "text": FunctionParameter(type="string")}, required=["text"]),
               handler=lambda ctx, text: f"echo:{text}")

JSON_SPEC = SubmitSpec(kind="json", schema={"type": "object"})
PV_SPEC = SubmitSpec(kind="fence", fence_lang="proverif")
BUDGET = LoopBudget(max_rounds=6, max_tool_calls=5, max_repairs=2)


def _run(llm, tmp_path, *, submit=JSON_SPEC, accept=lambda s, f: [],
         tools=None, resume_from=None, budget=BUDGET, upstream=("flow",)):
    w = TranscriptWriter(tmp_path / "transcript.jsonl")
    return asyncio.run(run_agent(
        llm, system="sys", user="do the work", tools=tools or [ECHO],
        ctx=ToolContext(node="t", upstream_nodes=upstream), submit=submit,
        accept=accept, budget=budget, writer=w, resume_from=resume_from,
    )), tmp_path / "transcript.jsonl"


def test_tool_then_json_submit_ok(tmp_path):
    llm = FakeChat([
        _resp(tool_calls=[_tc("echo", {"text": "hi"})], thinking="let me think"),
        _resp(content='{"answer": 1}'),
    ])
    r, path = _run(llm, tmp_path)
    assert r.status == "ok" and r.submission == {"answer": 1}
    assert r.rounds_used == 2 and r.tool_calls_used == 1
    # tool results and thinking are both on the transcript, so it can resume
    msgs = load_messages(path)
    assert any(m.tool_call_id == "call_1" for m in msgs)
    assert msgs[2].thinking == "let me think"


def test_accept_fail_repairs_then_pass(tmp_path):
    llm = FakeChat([_resp(content='{"v": 1}'), _resp(content='{"v": 2}')])
    seen = []
    def accept(s, fences):
        seen.append(s)
        return ["v must be 2"] if s["v"] != 2 else []
    r, path = _run(llm, tmp_path, accept=accept)
    assert r.status == "ok" and r.repairs_used == 1
    # the diagnosis entered the session as a user message
    entries = TranscriptReader(path).entries()
    assert any("repair 1 of" in e["content"] for e in entries if e["t"] == "user")


def test_repairs_exhausted_fails(tmp_path):
    llm = FakeChat([_resp(content=f'{{"v": {i}}}') for i in range(4)])
    r, _ = _run(llm, tmp_path, accept=lambda s, f: ["never passes"])
    assert r.status == "failed" and "after 2 repair rounds" in r.failure


def test_identical_resubmission_stops(tmp_path):
    llm = FakeChat([_resp(content='{"v": 1}'), _resp(content='{"v": 1}')])
    r, _ = _run(llm, tmp_path, accept=lambda s, f: ["did not pass"])
    assert r.status == "failed" and "identical to the last one" in r.failure


def test_fence_submission_and_missing_fence_repair(tmp_path):
    llm = FakeChat([
        _resp(content="wrote it but forgot the fence free c: channel."),
        _resp(content="```proverif\nfree c: channel.\nprocess 0\n```"),
    ])
    r, _ = _run(llm, tmp_path, submit=PV_SPEC)
    assert r.status == "ok" and r.submission.startswith("free c")
    assert r.repairs_used == 1


def test_degraded_opening_fence_recovered(tmp_path):
    # A gateway that drops the reply's first token turns "```proverif\n..."
    # into "proverif\n...". A start-anchored degraded opening is recovered as
    # long as the closing fence is intact.
    for head in ("proverif\n", "`proverif\n", "``proverif\n"):
        llm = FakeChat([_resp(content=head + "free c: channel.\nprocess 0\n```")])
        r, _ = _run(llm, tmp_path, submit=PV_SPEC)
        assert r.status == "ok" and r.submission.startswith("free c"), head
        assert r.repairs_used == 0


def test_degraded_fence_not_recovered_mid_reply(tmp_path):
    # The loss only ever hits the reply's first token, so a bare tag word in
    # the middle of prose is a repair round, not a submission.
    llm = FakeChat([
        _resp(content="the file is written in proverif\nsyntax, see below ```"),
        _resp(content="```proverif\nfree c: channel.\nprocess 0\n```"),
    ])
    r, _ = _run(llm, tmp_path, submit=PV_SPEC)
    assert r.status == "ok" and r.repairs_used == 1


def test_rounds_budget(tmp_path):
    llm = FakeChat([
        _resp(tool_calls=[_tc("echo", {"text": "x"}, f"c{i}")])
        for i in range(3)
    ] + [_resp(content='{"answer": 1}')])
    r, _ = _run(llm, tmp_path, budget=LoopBudget(max_rounds=3, max_tool_calls=99))
    assert r.status == "ok" and r.rounds_used == 4
    assert llm.calls_tools[-1] == []
    assert llm.calls_tool_choice[-1].mode is ToolChoiceMode.NONE


def test_finalization_is_one_shot_if_the_submission_is_rejected(tmp_path):
    llm = FakeChat([
        _resp(tool_calls=[_tc("echo", {"text": "x"})]),
        _resp(content='{"answer": 1}'),
    ])
    r, _ = _run(
        llm, tmp_path,
        budget=LoopBudget(max_rounds=1, max_tool_calls=99, max_repairs=6),
        accept=lambda s, f: ["never passes"],
    )
    assert r.status == "failed" and "max_rounds" in r.failure
    assert r.rounds_used == 2 and len(llm.calls) == 2


def test_report_gap_exits_immediately(tmp_path):
    llm = FakeChat([_resp(tool_calls=[_tc(
        "report_gap",
        {"target": "flow", "missing": "K_as", "evidence": "§3.1 'the key K_as'"},
        "gap_call",
    )])])
    r, _ = _run(llm, tmp_path, tools=[ECHO, gap_tool(("flow",))])
    assert r.status == "gap"
    assert r.gap.target == "flow" and r.gap.reporter == "t"
    assert r.gap_tool_call_id == "gap_call"


def test_report_gap_with_a_target_that_is_not_upstream_stays_in_session(tmp_path):
    # The handler refuses in-session: the model sees an ordinary tool error and
    # corrects itself here, with no node re-run and nothing counted against the
    # rejection limit.
    llm = FakeChat([
        _resp(tool_calls=[_tc("report_gap", {
            "target": "cross_check", "missing": "K_as", "evidence": "§3.1"})]),
        _resp(content='{"answer": 1}'),
    ])
    r, path = _run(llm, tmp_path, tools=[ECHO, gap_tool(("flow",))], upstream=("flow",))
    assert r.status == "ok"
    results = [e for e in TranscriptReader(path).entries() if e["t"] == "tool_result"]
    assert "is not upstream" in results[-1]["content"]
    assert "flow" in results[-1]["content"]          # the legal set is named


def test_resume_continues_old_session(tmp_path):
    llm1 = FakeChat([_resp(content='{"v": 1}')])
    r1, path = _run(llm1, tmp_path)
    assert r1.status == "ok"
    old = load_messages(path)
    llm2 = FakeChat([_resp(content='{"v": 2}')])
    r2, _ = _run(llm2, tmp_path, resume_from=old)
    assert r2.status == "ok" and r2.submission == {"v": 2}
    # the resumed request carries every old message plus the new user one
    assert len(llm2.calls[0]) == len(old) + 1


def test_cancel_writes_interrupt_marker(tmp_path):
    class Hang(ChatClient):
        async def invoke(self, *a, **k):
            await asyncio.sleep(30)

    async def main():
        w = TranscriptWriter(tmp_path / "transcript.jsonl")
        task = asyncio.ensure_future(run_agent(
            Hang(), system="s", user="u", tools=[], ctx=ToolContext(node="t"),
            submit=JSON_SPEC, accept=lambda s, f: [], budget=BUDGET, writer=w,
        ))
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    entries = TranscriptReader(tmp_path / "transcript.jsonl").entries()
    assert entries[-1]["t"] == "interrupted"


# The tool submission form: the product arrives as a submit call, so a round
# that only talks costs a round instead of the task. The tests below walk that
# separation and the tool shapes the API needs kept intact.

TOOL_SPEC = SubmitSpec(kind="tool", schema={
    "type": "object",
    "properties": {"v": {"type": "integer"}},
    "required": ["v"],
    "additionalProperties": False,
})


def _submit(v, id_="call_s"):
    return _tc("submit", {"v": v}, id_=id_)


def test_submit_tool_delivers_the_product(tmp_path):
    llm = FakeChat([_resp(content="Looking at section 3 first.",
                          tool_calls=[_tc("echo", {"text": "hi"})]),
                    _resp(content="Ready.", tool_calls=[_submit(1)])])
    r, path = _run(llm, tmp_path, submit=TOOL_SPEC)
    assert r.status == "ok" and r.submission == {"v": 1}
    # submitting is not evidence gathering and is not rationed with it
    assert r.tool_calls_used == 1
    # the tool the model was offered carries the product's schema
    tools = [t.name for t in llm.calls_tools[-1]]
    assert tools == ["echo", "submit"]
    submit_tool = next(t for t in llm.calls_tools[-1] if t.name == "submit")
    assert submit_tool.schema()["required"] == ["v"]
    assert submit_tool.strict is False          # decoding is left unconstrained


def test_tool_submission_finalization_forces_submit_only(tmp_path):
    llm = FakeChat([
        _resp(tool_calls=[_tc("echo", {"text": "hi"})]),
        _resp(tool_calls=[_submit(1)]),
    ])
    r, path = _run(
        llm, tmp_path, submit=TOOL_SPEC,
        budget=LoopBudget(max_rounds=1, max_tool_calls=5, max_repairs=2),
    )
    assert r.status == "ok" and r.submission == {"v": 1}
    assert r.rounds_used == 2
    assert [tool.name for tool in llm.calls_tools[-1]] == ["submit"]
    choice = llm.calls_tool_choice[-1]
    assert choice.mode is ToolChoiceMode.TOOL
    assert choice.tool_name == "submit" and choice.disable_parallel is True
    prompts = [e["content"] for e in TranscriptReader(path).entries()
               if e["t"] == "user"]
    assert any("Final submission round" in prompt for prompt in prompts)


def test_finalization_keeps_terminal_gap_but_removes_reading_tools(tmp_path):
    llm = FakeChat([
        _resp(tool_calls=[_tc("echo", {"text": "hi"})]),
        _resp(tool_calls=[_tc(
            "report_gap",
            {"target": "flow", "missing": "K", "evidence": "§1 'K'"},
        )]),
    ])
    r, _ = _run(
        llm, tmp_path, submit=TOOL_SPEC,
        tools=[ECHO, gap_tool(("flow",))], upstream=("flow",),
        budget=LoopBudget(max_rounds=1, max_tool_calls=5, max_repairs=2),
    )
    assert r.status == "gap"
    assert [tool.name for tool in llm.calls_tools[-1]] == ["report_gap", "submit"]
    choice = llm.calls_tool_choice[-1]
    assert choice.mode is ToolChoiceMode.REQUIRED
    assert choice.disable_parallel is True


def test_rejected_submission_answers_the_call_and_continues(tmp_path):
    llm = FakeChat([_resp(tool_calls=[_submit(1, "a")]),
                    _resp(tool_calls=[_submit(2, "b")])])
    r, path = _run(llm, tmp_path, submit=TOOL_SPEC,
                   accept=lambda s, f: ["v must be 2"] if s["v"] != 2 else [])
    assert r.status == "ok" and r.repairs_used == 1
    # the diagnosis comes back as that call's result, not as a free-standing
    # user message: an unanswered tool_use is a 400 on the next round
    entries = TranscriptReader(path).entries()
    rejected = [e for e in entries if e["t"] == "tool_result" and e["tool_call_id"] == "a"]
    assert len(rejected) == 1 and "v must be 2" in rejected[0]["content"]
    # the accepted call is answered too, so the session restores as finished
    # rather than killed mid-submission
    assert entries[-1]["t"] == "tool_result" and entries[-1]["tool_call_id"] == "b"
    assert not any("did not finish" in (m.content or "")
                   for m in load_messages(path))


def test_a_parallel_round_answers_every_call(tmp_path):
    """A round may carry a reading tool and the submission together. If the
    submission is rejected the round has to continue, and every tool_use in it
    needs a result or the next request is rejected outright."""
    llm = FakeChat([
        _resp(tool_calls=[_tc("echo", {"text": "hi"}, id_="e"), _submit(1, "s")]),
        _resp(tool_calls=[_submit(2, "s2")]),
    ])
    r, path = _run(llm, tmp_path, submit=TOOL_SPEC,
                   accept=lambda s, f: ["v must be 2"] if s["v"] != 2 else [])
    assert r.status == "ok"
    answered = {e["tool_call_id"] for e in TranscriptReader(path).entries()
                if e["t"] == "tool_result"}
    assert {"e", "s"} <= answered


def test_talking_without_submitting_costs_a_round_not_the_task(tmp_path):
    llm = FakeChat([_resp(content="I have enough evidence now."),
                    _resp(tool_calls=[_submit(1)])])
    r, path = _run(llm, tmp_path, submit=TOOL_SPEC)
    assert r.status == "ok" and r.rounds_used == 2
    # nudged rather than parsed as a product
    assert any("called no tool" in e["content"]
               for e in TranscriptReader(path).entries() if e["t"] == "user")


def test_two_silent_rounds_stop_the_task(tmp_path):
    llm = FakeChat([_resp(content="Thinking."), _resp(content="Still thinking.")])
    r, _ = _run(llm, tmp_path, submit=TOOL_SPEC)
    assert r.status == "failed" and "did not submit" in r.failure


def test_arguments_off_schema_are_repairable_not_fatal(tmp_path):
    llm = FakeChat([_resp(tool_calls=[_tc("submit", {"wrong": 1}, id_="a")]),
                    _resp(tool_calls=[_submit(2)])])
    r, path = _run(llm, tmp_path, submit=TOOL_SPEC)
    assert r.status == "ok" and r.repairs_used == 1
    bad = next(e for e in TranscriptReader(path).entries()
               if e["t"] == "tool_result" and e["tool_call_id"] == "a")
    assert "does not match json_schema" in bad["content"]


def test_a_node_tool_named_submit_is_refused(tmp_path):
    clash = ToolDef(name="submit", description="not the submission tool",
                    parameters=FunctionParameter(type="object", properties={},
                                                 required=[]),
                    handler=lambda ctx: "x")
    with pytest.raises(ValueError, match="already has a tool named"):
        _run(FakeChat([]), tmp_path, submit=TOOL_SPEC, tools=[clash])


GIVE_UP_SPEC = SubmitSpec(
    kind="tool", schema=TOOL_SPEC.schema,
    give_up=GiveUpSpec(name="report_stuck", description="end by giving up",
                       schema={"type": "object",
                               "properties": {"reason": {"type": "string",
                                                         "minLength": 1}},
                               "required": ["reason"],
                               "additionalProperties": False}))


def test_giving_up_ends_the_task_with_its_own_status(tmp_path):
    """run_agent with a give_up spec, end to end: calling the give-up tool ends
    the task under its own status instead of failing it."""
    llm = FakeChat([_resp(tool_calls=[_tc("report_stuck",
                                          {"reason": "no such value"})])])
    r, path = _run(llm, tmp_path, submit=GIVE_UP_SPEC)
    assert r.status == "gave_up" and r.gave_up == {"reason": "no such value"}
    # the model was offered both exits
    assert {"submit", "report_stuck"} <= {t.name for t in llm.calls_tools[-1]}
    # the give-up call was answered, so the transcript restores cleanly
    entries = TranscriptReader(path).entries()
    assert entries[-1]["t"] == "tool_result"


def test_a_malformed_give_up_is_repairable_not_fatal(tmp_path):
    llm = FakeChat([_resp(tool_calls=[_tc("report_stuck", {"reason": ""},
                                          id_="a")]),
                    _resp(tool_calls=[_submit(2)])])
    r, _ = _run(llm, tmp_path, submit=GIVE_UP_SPEC)
    assert r.status == "ok" and r.repairs_used == 1


def test_give_up_needs_the_tool_form(tmp_path):
    spec = SubmitSpec(kind="json", schema={"type": "object"},
                      give_up=GIVE_UP_SPEC.give_up)
    with pytest.raises(ValueError, match="needs kind='tool'"):
        _run(FakeChat([]), tmp_path, submit=spec)


def test_calling_both_exits_in_one_round_rejects_the_round(tmp_path):
    """The two exits contradict each other, so a round carrying both is
    rejected whole and every call in it is answered."""
    llm = FakeChat([_resp(tool_calls=[_submit(1, id_="s"),
                                      _tc("report_stuck", {"reason": "r"},
                                          id_="g")]),
                    _resp(tool_calls=[_submit(2)])])
    r, path = _run(llm, tmp_path, submit=GIVE_UP_SPEC)
    assert r.status == "ok" and r.submission == {"v": 2}
    assert r.repairs_used == 1
    answered = {e["tool_call_id"] for e in TranscriptReader(path).entries()
                if e["t"] == "tool_result"}
    assert {"s", "g"} <= answered


def test_each_repair_round_leaves_its_own_prompt(tmp_path):
    """One prompt file per round, not one per session: a rejected round's
    prompt is the diagnosis the checks produced."""
    llm = FakeChat([_resp(content='{"v": 1}'),      # rejected
                    _resp(content="thinking out loud"),   # also a bad submission
                    _resp(content='{"v": 2}')])
    r, _ = _run(llm, tmp_path,
                accept=lambda s, f: [] if s.get("v") == 2 else ["v must be 2"],
                budget=LoopBudget(max_rounds=6, max_tool_calls=5, max_repairs=3))
    assert r.status == "ok"
    names = sorted(p.name for p in (tmp_path / "rounds").iterdir())
    assert names == ["00_prompt.md", "01_prompt.md", "02_prompt.md"]
    # the opening prompt carries tools and system prompt; a later round's
    # carries only the message that opened it
    assert "TOOLS" in (tmp_path / "rounds" / "00_prompt.md").read_text()
    later = (tmp_path / "rounds" / "01_prompt.md").read_text()
    assert "v must be 2" in later and "TOOLS" not in later


def test_a_resumed_session_files_the_message_it_comes_back_on(tmp_path):
    llm = FakeChat([_resp(content='{"v": 1}')])
    _run(llm, tmp_path)                                   # the first session
    llm2 = FakeChat([_resp(content='{"v": 2}')])
    _run(llm2, tmp_path, resume_from=load_messages(tmp_path / "transcript.jsonl"))
    names = sorted(p.name for p in (tmp_path / "rounds").iterdir())
    assert names == ["00_prompt.md", "01_prompt.md"]
    assert "resumed" in (tmp_path / "rounds" / "01_prompt.md").read_text()


class StreamingChat(FakeChat):
    """A fake that streams fragments before it answers, the way a real adapter
    does. Their order against the durable events is the contract the console's
    session timeline rests on."""

    async def invoke(self, messages, tools=None, on_delta=None, **kw):
        if on_delta is not None:
            on_delta("thinking", "weighing it")
            on_delta("text", "the answer")
        return await super().invoke(messages, tools=tools, **kw)


def test_a_round_is_announced_prompt_then_fragments_then_the_round(tmp_path):
    """What a live watcher sees, in order: the prompt is filed before the call
    goes out, the reply arrives as fragments while the call is open, and
    RoundStarted lands only once there is a reply to number."""
    seen = []
    llm = StreamingChat([
        _resp(tool_calls=[_tc("echo", {"text": "hi"})]),
        _resp(content='{"answer": 1}'),
    ])
    w = TranscriptWriter(tmp_path / "transcript.jsonl")
    r = asyncio.run(run_agent(
        llm, system="sys", user="do the work", tools=[ECHO],
        ctx=ToolContext(node="t", artifacts_root=tmp_path), submit=JSON_SPEC,
        accept=lambda s, f: [], budget=BUDGET, writer=w,
        emitter=seen.append))
    assert r.status == "ok"
    kinds = [e.type_name() for e in seen]
    assert kinds[:6] == ["prompt_filed", "model_delta", "model_delta",
                         "round_started", "tool_called", "tool_returned"]
    filed = seen[0]
    # run-relative so the reader can open it; the length rides on the event so
    # a collapsed line needs no fetch
    assert filed.path == "rounds/00_prompt.md" and filed.round_no == 1
    assert filed.chars == len((tmp_path / "rounds" / "00_prompt.md").read_text())


def test_a_terminal_tool_call_is_announced_like_any_other(tmp_path):
    """submit ends the loop by returning out of it, so its announcement has to
    be emitted before that return; otherwise a session that submitted once and
    called nothing else leaves no tool call on the ledger."""
    seen = []
    llm = FakeChat([_resp(tool_calls=[_tc("submit", {"answer": 1})])])
    w = TranscriptWriter(tmp_path / "transcript.jsonl")
    r = asyncio.run(run_agent(
        llm, system="sys", user="go", tools=[ECHO],
        ctx=ToolContext(node="t", artifacts_root=tmp_path),
        submit=SubmitSpec(kind="tool", schema={"type": "object"}),
        accept=lambda s, f: [], budget=BUDGET, writer=w, emitter=seen.append))
    assert r.status == "ok"
    called = [e for e in seen if e.type_name() == "tool_called"]
    assert [e.tool for e in called] == ["submit"]
    # and no ToolReturned: it answered the framework, not the model
    assert not [e for e in seen if e.type_name() == "tool_returned"]


def test_a_budget_of_none_is_no_ceiling(tmp_path):
    """The expert's default: no round ceiling and no call ceiling. A node's
    loop has to end by construction because nothing is watching it; the expert
    answers a person who is, so how much evidence a question needs is the
    question's business."""
    llm = FakeChat([
        _resp(tool_calls=[_tc("echo", {"text": f"r{i}"}, f"c{i}")]) for i in range(20)
    ] + [_resp(content='{"answer": 1}')])
    r, _ = _run(llm, tmp_path, tools=[ECHO],
                budget=LoopBudget(max_rounds=None, max_tool_calls=None,
                                  max_repairs=1))
    assert r.status == "ok"
    # far past both of the numbers a node would have stopped at
    assert r.rounds_used == 21 and r.tool_calls_used == 20


def test_a_refused_opening_call_leaves_nothing_to_resume_from(tmp_path):
    """A call the service refuses leaves nothing behind to replay.

    The failure mode this guards: the request is too long, the API 400s, and
    the node carries on in the same directory on re-entry. Were the message
    already on the transcript, resume would replay the very bytes that were
    refused and the session could never be started again. The system prompt
    goes with it: recorded alone it restores to a session that is not empty,
    so the node would resume it with "continue from the progress above" and
    the task itself would never be sent.
    """
    from orrery.services.transcript.resume import resume_messages

    class Refuses(ChatClient):
        async def invoke(self, *a, **k):
            raise RuntimeError("400 prompt is too long")

    w = TranscriptWriter(tmp_path / "transcript.jsonl")
    w.meta(node="t")
    with pytest.raises(RuntimeError):
        asyncio.run(run_agent(
            Refuses(), system="sys", user="a very long question", tools=[],
            ctx=ToolContext(node="t"), submit=JSON_SPEC,
            accept=lambda s, f: [], budget=BUDGET, writer=w))
    kinds = [e["t"] for e in TranscriptReader(w.path).entries()]
    assert kinds == ["meta"]
    # and what it restores to is a fresh start, so the node sends the task again
    assert resume_messages(w.path) is None


def test_a_refused_repair_call_keeps_the_session_up_to_its_last_reply(tmp_path):
    """The same refusal later in a session drops only the diagnosis that was
    refused with it; everything the model did answer stays on the record."""
    class RefusesSecond(ChatClient):
        def __init__(self):
            self.n = 0

        async def invoke(self, *a, **k):
            self.n += 1
            if self.n == 1:
                return _resp(content='{"v": 1}')
            raise RuntimeError("400 prompt is too long")

    w = TranscriptWriter(tmp_path / "transcript.jsonl")
    with pytest.raises(RuntimeError):
        asyncio.run(run_agent(
            RefusesSecond(), system="sys", user="do the work", tools=[],
            ctx=ToolContext(node="t"), submit=JSON_SPEC,
            accept=lambda s, f: ["v must be 2"], budget=BUDGET, writer=w))
    kinds = [e["t"] for e in TranscriptReader(w.path).entries()]
    assert kinds == ["system", "user", "assistant"]


def test_an_interrupted_call_is_settled_before_the_marker(tmp_path):
    """An interrupt is not a refusal: the message the model was answering when
    it was cut off is what a resume picks up from, so it lands on the record,
    in front of the interrupted marker."""
    class HangOnSecond(ChatClient):
        def __init__(self):
            self.n = 0

        async def invoke(self, *a, **k):
            self.n += 1
            if self.n == 1:
                return _resp(content='{"v": 1}')
            await asyncio.sleep(30)

    async def main():
        w = TranscriptWriter(tmp_path / "transcript.jsonl")
        task = asyncio.ensure_future(run_agent(
            HangOnSecond(), system="s", user="u", tools=[],
            ctx=ToolContext(node="t"), submit=JSON_SPEC,
            accept=lambda s, f: ["v must be 2"], budget=BUDGET, writer=w))
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    kinds = [e["t"] for e in TranscriptReader(tmp_path / "transcript.jsonl").entries()]
    assert kinds == ["system", "user", "assistant", "user", "interrupted"]


def test_a_diagnosis_the_budget_cut_off_is_still_recorded(tmp_path):
    """The loop leaves on its own with a diagnosis the model never saw: a
    resumed session continues from it, so it is on the record."""
    llm = FakeChat([_resp(content='{"v": 1}'), _resp(content='{"v": 2}'),
                    _resp(content='{"v": 3}')])
    r, path = _run(llm, tmp_path, accept=lambda s, f: ["not yet"],
                   budget=LoopBudget(max_rounds=2, max_tool_calls=5, max_repairs=9))
    assert r.status == "failed" and "max_rounds" in r.failure
    kinds = [e["t"] for e in TranscriptReader(path).entries()]
    # two rounds, the one-shot finalization round (its diagnosis and the
    # finalization prompt settled together), then the diagnosis nobody saw
    assert kinds == ["system", "user", "assistant", "user", "assistant",
                     "user", "user", "assistant", "user"]


def test_a_refused_format_still_records_the_message_it_answered(tmp_path):
    """The other half of the rule: a format violation is an answer. The model
    was called and billed, so the message it replied to belongs on the record,
    in front of the rejection line."""
    from orrery.infra.llm.validation import OutputFormatViolation

    class OnceBad(ChatClient):
        def __init__(self):
            self.n = 0

        async def invoke(self, *a, **k):
            self.n += 1
            if self.n == 1:
                raise OutputFormatViolation("not JSON", raw="prose")
            return _resp(content='{"v": 1}')

    w = TranscriptWriter(tmp_path / "transcript.jsonl")
    r = asyncio.run(run_agent(
        OnceBad(), system="sys", user="do the work", tools=[],
        ctx=ToolContext(node="t"), submit=JSON_SPEC,
        accept=lambda s, f: [], budget=BUDGET, writer=w))
    assert r.status == "ok"
    kinds = [e["t"] for e in TranscriptReader(w.path).entries()]
    assert kinds == ["system", "user", "rejected", "user", "assistant"]
