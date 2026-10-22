"""The independent review leaves the same trace as any other model call:
prompts, thinking and usage in its own transcript, one ledger line per step. A
scripted fake LLM walks the clean path, the retry path and the void."""

import asyncio
import json

from orrery.checks.reviewer.checker import review_flow
from orrery.infra.llm.client import (
    ChatClient, ChatResponse, TokenUsage,
)
from orrery.infra.llm.validation import OutputFormatViolation
from orrery.services.transcript.reader import TranscriptReader
from orrery.services.transcript.writer import TranscriptWriter

PV = "let processA(A: host) = event end_x(A); 0."
REF = {"knowledge": {"principals": [{"name": "A", "description": "initiator"}],
                     "values": [
                         {"name": "SKA", "derived_from": [],
                          "description": "private key"},
                         {"name": "PKA", "derived_from": ["SKA"],
                          "description": "verification key"}]},
       "flow_text": "# 4 Protocol\nStep 1: A -> B: {N_a, A}PKB",
       "flow_source": "flow_sections"}


class FakeChat(ChatClient):
    """Each script entry is either a ChatResponse to return or an exception to
    raise, so a format violation is scripted the same way as a reply."""

    def __init__(self, script):
        self.script = list(script)

    async def invoke(self, messages, tools=None, tool_choice=None,
                     temperature=None, response_format=None, json_schema=None,
                     **kw) -> ChatResponse:
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _reply(findings, thinking=None):
    return ChatResponse(
        content=json.dumps({"findings": findings}),
        usage=TokenUsage(input_tokens=11, output_tokens=22, total_tokens=33),
        thinking=thinking,
        thinking_blocks=[{"type": "thinking", "thinking": thinking or "",
                          "signature": "sig"}] if thinking else None,
    )


def _run(llm, path, notes):
    return asyncio.run(review_flow(
        llm, pv_text=PV, writer=TranscriptWriter(path), model="fake-1",
        note=notes.append, **REF))


def test_session_is_traced_whole(tmp_path):
    notes: list[str] = []
    path = tmp_path / "z3_review.jsonl"
    found = _run(FakeChat([_reply(
        [{"item": 1, "finding": "no query in the flow model",
          "counterfactual": "event end_x(A)"}], thinking="weighing item 1")]),
        path, notes)

    # the finding came back stamped by the mechanical search
    assert [f["status"] for f in found] == ["confirmed"]

    entries = TranscriptReader(path).entries()
    kinds = [e["t"] for e in entries]
    assert kinds == ["meta", "system", "user", "assistant"]
    assert entries[0]["model"] == "fake-1"
    # which selection produced the flow text is recorded
    assert entries[0]["flow_source"] == "flow_sections"
    # the prompts are on disk in full, not summarised
    assert "six items" in entries[1]["content"]
    assert PV in entries[2]["content"]
    # the reference material for the flow is the document, not an artifact
    assert "Step 1: A -> B" in entries[2]["content"]
    # thinking, the provider-native blocks behind it, and usage all kept
    asst = entries[3]
    assert asst["thinking"] == "weighing item 1"
    assert asst["thinking_blocks"][0]["signature"] == "sig"
    assert asst["usage"]["output_tokens"] == 22
    # and the transcript still restores as a session
    assert len(TranscriptReader(path).messages()) == 3

    assert len(notes) == 2
    assert "reconciling" in notes[0]
    assert "1 model call(s), 1 finding(s), 1 confirmed" in notes[1]
    assert "z3_review.jsonl" in notes[1]


def test_format_violation_and_retry_are_traced(tmp_path):
    notes: list[str] = []
    path = tmp_path / "z3_review.jsonl"
    found = _run(FakeChat([OutputFormatViolation("no JSON object; got: blah"),
                           _reply([])]), path, notes)
    assert found == []

    entries = TranscriptReader(path).entries()
    assert [e["t"] for e in entries] == [
        "meta", "system", "user", "meta", "user", "assistant"]
    # the reply that never became a ChatResponse still leaves its excerpt
    marker = entries[3]
    assert marker["outcome"] == "format_violation"
    assert marker["call"] == 1
    assert "got: blah" in marker["detail"]
    assert "retrying once" in notes[1]
    assert "2 model call(s)" in notes[2]


def test_void_review_says_so_on_the_ledger(tmp_path):
    notes: list[str] = []
    path = tmp_path / "z3_review.jsonl"
    found = _run(FakeChat([OutputFormatViolation("first"),
                           OutputFormatViolation("second")]), path, notes)
    # warning level: the node is never brought down, the void is the record
    assert found[0]["status"] == "unverified"
    assert "void after 2 call(s)" in notes[-1]
    kinds = [e["t"] for e in TranscriptReader(path).entries()]
    assert kinds == ["meta", "system", "user", "meta", "user", "meta"]
