"""Streaming across the three backends: what reaches the on_delta sink, and the
reply the call still returns. The sink is a side channel, so every test asserts
both halves.

No network: each SDK object is replaced by the smallest fake carrying the shape
the adapter reads.
"""
from types import SimpleNamespace as NS

import pytest
from google.genai import types as gtypes

from orrery.infra.llm.client import feed
from orrery.infra.llm.remote.claude import RemoteChatClaude
from orrery.infra.llm.remote.gemini import RemoteChatGemini
from orrery.infra.llm.remote.openai import RemoteChatOpenAI


class Recorder:
    """A sink that keeps what it was handed."""

    def __init__(self):
        self.seen: list[tuple[str, str]] = []

    def __call__(self, kind, text):
        self.seen.append((kind, text))

    def text(self) -> str:
        return "".join(t for k, t in self.seen if k == "text")

    def thinking(self) -> str:
        return "".join(t for k, t in self.seen if k == "thinking")


class _FakeStream:
    """An async context manager that is also an async iterator, the shape all
    three SDKs hand back."""

    def __init__(self, events, final):
        self._events, self._final = events, final
        self.iterated = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def __aiter__(self):
        self.iterated = True
        for e in self._events:
            yield e

    async def get_final_message(self):
        return self._final

    async def get_final_response(self):
        if self._final is None:
            raise RuntimeError("Didn't receive a `response.completed` event.")
        return self._final


# ------------------------------------------------------------------ the sink

def test_a_raising_sink_costs_the_fragment_and_nothing_else():
    """A sink that raises costs only its own fragment; the call the model
    answered still succeeds."""
    def explode(kind, text):
        raise ValueError("the UI fell over")

    feed(explode, "text", "hello")          # must not raise


def test_empty_fragments_never_reach_the_sink():
    r = Recorder()
    feed(r, "text", "")
    feed(r, "text", None)
    feed(r, "text", "real")
    assert r.seen == [("text", "real")]


# ---------------------------------------------------------------- anthropic

def _claude_final(text="the answer", stop="end_turn"):
    return NS(
        stop_reason=stop,
        content=[NS(type="text", text=text)],
        usage=NS(input_tokens=10, output_tokens=4, cache_read_input_tokens=0,
                 cache_creation_input_tokens=0),
    )


def _claude(events, final):
    c = RemoteChatClaude(api_key="k", model_name="claude-sonnet-5")
    stream = _FakeStream(events, final)
    c.client = NS(messages=NS(stream=lambda **kw: stream))
    return c, stream


@pytest.mark.asyncio
async def test_claude_splits_thinking_from_text_and_still_returns_the_whole_reply():
    events = [
        NS(type="content_block_delta", delta=NS(type="thinking_delta", thinking="let me ")),
        NS(type="content_block_delta", delta=NS(type="thinking_delta", thinking="think")),
        NS(type="content_block_delta", delta=NS(type="text_delta", text="the ")),
        NS(type="content_block_delta", delta=NS(type="text_delta", text="answer")),
    ]
    client, _ = _claude(events, _claude_final())
    r = Recorder()
    resp = await client._invoke_once(
        system_blocks=["sys"], claude_messages=[], temperature=None, cache=False,
        tools_param=None, on_delta=r)
    assert r.thinking() == "let me think"
    assert r.text() == "the answer"
    # The side channel is a copy, not a diversion.
    assert resp.content == "the answer"


@pytest.mark.asyncio
async def test_claude_forwards_neither_tool_arguments_nor_signatures():
    """Neither is readable text: arguments are meaningless until whole, and a
    signature is not text at all."""
    events = [
        NS(type="content_block_delta", delta=NS(type="input_json_delta", partial_json='{"pa')),
        NS(type="content_block_delta", delta=NS(type="signature_delta", signature="abc")),
        NS(type="message_stop"),
    ]
    client, _ = _claude(events, _claude_final())
    r = Recorder()
    await client._invoke_once(
        system_blocks=None, claude_messages=[], temperature=None, cache=False,
        tools_param=None, on_delta=r)
    assert r.seen == []


@pytest.mark.asyncio
async def test_claude_without_a_sink_does_not_walk_the_stream():
    """With no sink there is no read loop: the SDK drains the stream inside
    get_final_message."""
    client, stream = _claude([], _claude_final())
    resp = await client._invoke_once(
        system_blocks=None, claude_messages=[], temperature=None, cache=False,
        tools_param=None)
    assert stream.iterated is False
    assert resp.content == "the answer"


# ------------------------------------------------------------ openai responses

def _openai_final(text="hi"):
    return NS(
        status="completed",
        output=[NS(type="message", content=[NS(text=text)])],
        usage=NS(input_tokens=3, output_tokens=1, total_tokens=4,
                 input_tokens_details=NS(cached_tokens=0)),
    )


def _openai(events, final):
    c = RemoteChatOpenAI(api_key="k", model_name="gpt-5.6-sol")
    stream = _FakeStream(events, final)
    c.client = NS(responses=NS(stream=lambda **kw: stream))
    return c, stream


@pytest.mark.asyncio
async def test_responses_maps_both_reasoning_events_onto_thinking():
    """Responses spells reasoning two ways depending on the model; both map to
    thinking so the caller need not know which one arrived."""
    events = [
        NS(type="response.reasoning_summary_text.delta", delta="sum "),
        NS(type="response.reasoning_text.delta", delta="raw"),
        NS(type="response.output_text.delta", delta="hi"),
        NS(type="response.function_call_arguments.delta", delta='{"a'),
        NS(type="response.completed"),
    ]
    client, _ = _openai(events, _openai_final())
    r = Recorder()
    resp = await client._invoke_once(
        input_items=[], tools_param=None, tool_choice=None, temperature=None,
        reasoning=None, want_json=False, json_schema=None, on_delta=r, kwargs={})
    assert r.thinking() == "sum raw"
    assert r.text() == "hi"
    assert resp.content == "hi"


@pytest.mark.asyncio
async def test_a_truncated_stream_is_a_degraded_service_not_a_bug_in_us():
    """A relay that cuts the SSE short leaves no `response.completed`; the
    adapter restates the SDK's error as a degraded service."""
    client, _ = _openai([NS(type="response.output_text.delta", delta="hi")], None)
    with pytest.raises(RuntimeError, match="closed the stream before completing"):
        await client._invoke_once(
            input_items=[], tools_param=None, tool_choice=None, temperature=None,
            reasoning=None, want_json=False, json_schema=None,
            on_delta=Recorder(), kwargs={})


# ------------------------------------------------------------------- gemini

def _chunk(parts, usage=None, finish=None):
    return NS(
        prompt_feedback=None,
        usage_metadata=usage,
        candidates=[NS(content=NS(parts=parts), finish_reason=finish)],
    )


def _gemini(chunks):
    c = RemoteChatGemini(api_key="k", model_name="gemini-3.1-pro-preview")

    async def _stream(**kw):
        async def gen():
            for ch in chunks:
                yield ch
        return gen()

    c.client = NS(aio=NS(models=NS(generate_content_stream=_stream)))
    return c


@pytest.mark.asyncio
async def test_gemini_merges_chunks_into_one_candidate_the_parser_can_read():
    """Text split across chunks must merge back into the single string the
    parser would have seen unstreamed."""
    chunks = [
        _chunk([gtypes.Part(text="think ", thought=True)]),
        _chunk([gtypes.Part(text="the ")]),
        _chunk([gtypes.Part(text="answer")],
               usage=gtypes.GenerateContentResponseUsageMetadata(
                   prompt_token_count=7, candidates_token_count=2,
                   total_token_count=9),
               finish=gtypes.FinishReason.STOP),
    ]
    r = Recorder()
    _, candidates, usage = await _gemini(chunks)._stream_and_merge([], {}, r)
    assert r.thinking() == "think " and r.text() == "the answer"
    content, thinking, tool_calls, _ = RemoteChatGemini._extract_parts(candidates[0])
    assert content == "the answer"
    assert thinking == "think "
    assert candidates[0].finish_reason == gtypes.FinishReason.STOP
    # Cumulative, so the last chunk's counters are the call's.
    assert usage.total_token_count == 9


@pytest.mark.asyncio
async def test_gemini_keeps_a_tool_calls_signature_through_the_merge():
    """Gemini 3 rejects a replayed turn whose function_call parts lost their
    thought_signature, so the merge has to carry it through."""
    call = gtypes.Part(
        function_call=gtypes.FunctionCall(name="read_document", args={"id": "1"}),
        thought_signature=b"sig-bytes",
    )
    _, candidates, _ = await _gemini([_chunk([gtypes.Part(text="ok")]),
                                      _chunk([call])])._stream_and_merge([], {}, Recorder())
    _, _, tool_calls, blocks = RemoteChatGemini._extract_parts(candidates[0])
    assert tool_calls[0]["name"] == "read_document"
    assert blocks and blocks[0]["target"] == "tool_call"
    assert blocks[0]["id"] == tool_calls[0]["id"]


@pytest.mark.asyncio
async def test_gemini_reports_a_blocked_prompt_as_no_candidates():
    """A refused prompt streams feedback and no parts, so the caller raises on
    the empty candidate list just as on the non-streaming path."""
    blocked = NS(prompt_feedback=NS(block_reason="SAFETY"), usage_metadata=None,
                 candidates=[])
    feedback, candidates, _ = await _gemini([blocked])._stream_and_merge(
        [], {}, Recorder())
    assert feedback.block_reason == "SAFETY"
    assert candidates == []
