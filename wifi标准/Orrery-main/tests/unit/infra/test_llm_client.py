"""Unit tests for the llm layer: the interface shapes, ToolChoice's two checks,
JSON cleaning, and the factory's error paths. Nothing touches the network.
"""

import asyncio

import pytest

from orrery.infra.llm.client import (
    ChatClient,
    ChatMessage,
    ChatResponse,
    FunctionParameter,
    FunctionTool,
    Role,
    TokenUsage,
    ToolChoice,
)
from orrery.infra.llm.factory import build_chat_client
from orrery.infra.llm.validation import clean_json, ensure_valid_json


class FakeChat(ChatClient):
    async def invoke(self, messages, tools=None, tool_choice=None,
                     temperature=0, response_format=None, json_schema=None,
                     **kwargs) -> ChatResponse:
        return ChatResponse(content="hi", usage=TokenUsage())


def test_chat_shapes_thinking_optional():
    resp = asyncio.run(FakeChat().invoke([ChatMessage(Role.USER, "x")]))
    assert resp.thinking is None
    assert resp.usage.cache_creation_tokens == 0
    msg = ChatMessage(Role.ASSISTANT, "y", thinking="…")
    assert msg.thinking == "…"


def _tool(name="t") -> FunctionTool:
    return FunctionTool(name=name, description="d",
                        parameters=FunctionParameter(type="object", properties={}))


def test_tool_choice_two_defenses():
    with pytest.raises(ValueError):
        ToolChoice.tool("absent").validate_against([_tool("present")])
    with pytest.raises(ValueError):
        ToolChoice.required().validate_against(None)   # forcing with no tool menu
    with pytest.raises(RuntimeError):
        ToolChoice.required().verify_response([])      # gateway dropped tool_choice
    with pytest.raises(RuntimeError):
        ToolChoice.none().verify_response([{"name": "t"}])
    ToolChoice.tool("t").verify_response([{"name": "t"}])


def test_clean_json_and_result_side_validation():
    assert clean_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert clean_json('before {"a": {"b": 2}} after') == '{"a": {"b": 2}}'
    with pytest.raises(RuntimeError):
        ensure_valid_json("not JSON at all", "m")


def test_factory_error_paths():
    with pytest.raises(ValueError):
        build_chat_client({"backend": "no-such-backend", "model": "m"})
    with pytest.raises(ValueError):
        build_chat_client({"backend": "remote-claude", "api_key": "k"})  # model missing
    with pytest.raises(ValueError):
        build_chat_client({"model": "m", "api_key": "k"})   # backend missing


def test_a_budget_spent_on_thinking_is_recoverable_not_a_dead_service():
    """Extended thinking can consume all of max_tokens before one output token
    is written, leaving a reply that carries thinking and nothing else. The
    service said why it stopped, so this surfaces as a format violation the
    node can repair rather than a dead service.
    """
    import types

    from orrery.infra.llm.remote.claude import RemoteChatClaude
    from orrery.infra.llm.validation import OutputFormatViolation

    NS = types.SimpleNamespace

    class _Stream:
        """The SDK's streaming handle: an async context manager that iterates
        no events and hands back one final message."""
        def __init__(self, final):
            self._final = final

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def __aiter__(self):
            return
            yield  # noqa: unreachable, makes this an async generator

        async def get_final_message(self):
            return self._final

    client = RemoteChatClaude(api_key="k", model_name="claude-sonnet-5")
    final = NS(stop_reason="max_tokens",
               content=[NS(type="thinking", thinking="x" * 4000)],
               usage=NS(input_tokens=10, output_tokens=client.max_tokens,
                        cache_read_input_tokens=0, cache_creation_input_tokens=0))
    client.client = NS(messages=NS(stream=lambda **kw: _Stream(final)))

    with pytest.raises(OutputFormatViolation) as caught:
        asyncio.run(client._invoke_once(
            system_blocks=["sys"], claude_messages=[], temperature=None,
            cache=False, tools_param=None))
    # The usage rides along, or the round that burned the budget bills zero.
    assert caught.value.usage.output_tokens == client.max_tokens
    assert "deliberation" in str(caught.value)
