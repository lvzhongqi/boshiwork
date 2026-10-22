"""Wire translation for the Responses adapter: input items, tool shapes, output
parsing, plus factory-level config checks shared by every backend.

Only the pure shape functions are covered, which is where Responses disagrees
with Chat Completions. Nothing touches the network.
"""
import pytest

from orrery.infra.llm.client import (
    ChatMessage, FunctionTool, Role, ToolChoice,
)
from orrery.infra.llm.factory import build_chat_client
from orrery.infra.llm.remote.openai import RemoteChatOpenAI
from orrery.infra.llm.remote.openai_compatible import (
    RemoteChatOpenAICompatible,
)

TOOL = FunctionTool(
    name="get_weather",
    description="Get the weather.",
    parameters={"type": "object", "properties": {"city": {"type": "string"}},
                "required": ["city"], "additionalProperties": False},
)


def _client() -> RemoteChatOpenAI:
    return RemoteChatOpenAI(api_key="test-key", model_name="gpt-5.6-sol")


# ---------------------------------------------------------------- input items

def test_plain_roles_stay_messages():
    items = _client()._build_input([
        ChatMessage(Role.SYSTEM, "sys"),
        ChatMessage(Role.USER, "hi"),
    ])
    assert items == [{"role": "system", "content": "sys"},
                     {"role": "user", "content": "hi"}]


def test_system_blocks_are_joined():
    """A pre-split system prompt is one prompt; only claude.py marks the split."""
    items = _client()._build_input([ChatMessage(Role.SYSTEM, ["corpus", "node"])])
    assert items == [{"role": "system", "content": "corpus\n\nnode"}]


def test_assistant_tool_call_becomes_a_sibling_item():
    """The shape difference from Chat Completions: a tool call is not a field on
    the assistant message but an item beside it."""
    items = _client()._build_input([
        ChatMessage(Role.ASSISTANT, "let me check",
                    tool_calls=[{"id": "call_1", "type": "function",
                                 "name": "get_weather",
                                 "arguments": '{"city":"Paris"}'}]),
    ])
    assert items == [
        {"role": "assistant", "content": "let me check"},
        {"type": "function_call", "call_id": "call_1", "name": "get_weather",
         "arguments": '{"city":"Paris"}'},
    ]


def test_tool_result_is_an_output_item_keyed_by_call_id():
    items = _client()._build_input([
        ChatMessage(Role.TOOL, "sunny", tool_call_id="call_1"),
    ])
    assert items == [{"type": "function_call_output", "call_id": "call_1",
                      "output": "sunny"}]


def test_tool_message_without_id_is_rejected():
    with pytest.raises(RuntimeError, match="tool_call_id"):
        _client()._build_input([ChatMessage(Role.TOOL, "sunny")])


def test_reasoning_is_replayed_before_the_call_it_led_to():
    """Replay order matters: the reasoning item has to precede the call it led
    to."""
    block = {"type": "reasoning", "id": "rs_1", "encrypted_content": "abc",
             "summary": []}
    items = _client()._build_input([
        ChatMessage(Role.ASSISTANT, "", thinking_blocks=[block],
                    tool_calls=[{"id": "call_1", "type": "function",
                                 "name": "get_weather", "arguments": "{}"}]),
    ])
    assert [i.get("type") for i in items] == ["reasoning", "function_call"]
    assert items[0] == block


def test_foreign_thinking_blocks_are_ignored_not_replayed():
    """A transcript written by claude.py or gemini.py replays as a round that
    reasoned from scratch, instead of provoking a 400."""
    items = _client()._build_input([
        ChatMessage(Role.ASSISTANT, "text",
                    thinking_blocks=[{"type": "thinking", "signature": "x"},
                                     {"type": "thought_signature"}]),
    ])
    assert items == [{"role": "assistant", "content": "text"}]


# ---------------------------------------------------------------- tool shapes

def test_tools_are_flat_not_nested_under_function():
    [sent] = _client()._convert_tools([TOOL])
    assert sent["type"] == "function"
    assert sent["name"] == "get_weather"          # not sent["function"]["name"]
    assert sent["parameters"] == TOOL.schema()
    assert "function" not in sent


def test_tool_choice_named_tool_is_flat():
    choice, _ = _client()._convert_tool_choice(ToolChoice.tool("get_weather"))
    assert choice == {"type": "function", "name": "get_weather"}


def test_tool_choice_required_and_none():
    assert _client()._convert_tool_choice(ToolChoice.required())[0] == "required"
    assert _client()._convert_tool_choice(ToolChoice.none())[0] == "none"


def test_disable_parallel_is_a_separate_parameter():
    _, parallel = _client()._convert_tool_choice(
        ToolChoice.required(disable_parallel=True))
    assert parallel is False


# ------------------------------------------------------------ output parsing

class _Obj:
    """Minimal stand-in for an SDK model: attribute access plus model_dump."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, exclude_none=False):
        return {k: v for k, v in self.__dict__.items()
                if not (exclude_none and v is None)}


def test_output_is_split_four_ways():
    response = _Obj(output=[
        _Obj(type="reasoning", id="rs_1", encrypted_content="enc",
             summary=[_Obj(type="summary_text", text="thought about it")]),
        _Obj(type="message", content=[_Obj(type="output_text", text="the answer")]),
        _Obj(type="function_call", call_id="call_1", name="get_weather",
             arguments='{"city":"Paris"}'),
    ])
    content, thinking, tool_calls, blocks = RemoteChatOpenAI._extract_output(response)
    assert content == "the answer"
    assert thinking == "thought about it"
    assert tool_calls == [{"id": "call_1", "type": "function",
                           "name": "get_weather",
                           "arguments": '{"city":"Paris"}',
                           "arguments_json": {"city": "Paris"}}]
    # The reasoning item is kept whole, because it goes back verbatim.
    assert blocks[0]["id"] == "rs_1" and blocks[0]["encrypted_content"] == "enc"


def test_tool_call_id_carries_call_id_not_item_id():
    """A function_call_output pairs against call_id, not against the item's own
    id."""
    response = _Obj(output=[_Obj(type="function_call", id="fc_x",
                                 call_id="call_x", name="get_weather",
                                 arguments="{}")])
    _, _, tool_calls, _ = RemoteChatOpenAI._extract_output(response)
    assert tool_calls[0]["id"] == "call_x"


def test_unparseable_arguments_survive_as_raw_text():
    response = _Obj(output=[_Obj(type="function_call", call_id="c",
                                 name="get_weather", arguments="{not json")])
    _, _, tool_calls, _ = RemoteChatOpenAI._extract_output(response)
    assert tool_calls[0]["arguments"] == "{not json"
    assert tool_calls[0]["arguments_json"] is None


def test_usage_maps_the_renamed_counters():
    response = _Obj(usage=_Obj(input_tokens=100, output_tokens=20,
                               total_tokens=120,
                               input_tokens_details=_Obj(cached_tokens=40)))
    usage = RemoteChatOpenAI._extract_usage(response)
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens,
            usage.cached_tokens) == (100, 20, 120, 40)


# ------------------------------------------------------------------- factory

def test_the_two_backends_resolve_to_their_own_adapters():
    common = {"model": "gpt-5.6-sol", "api_key": "k", "url": "https://x/v1"}
    assert isinstance(
        build_chat_client({"backend": "remote-openai-responses", **common}),
        RemoteChatOpenAI)
    assert isinstance(
        build_chat_client({"backend": "remote-openai-compatible", **common}),
        RemoteChatOpenAICompatible)


def test_the_old_backend_name_fails_loudly_and_names_both_successors():
    """One config value cannot name two protocols, so the retired name is an
    error naming both successors."""
    with pytest.raises(ValueError) as e:
        build_chat_client({"backend": "remote-openai", "model": "deepseek-chat",
                           "api_key": "k"})
    assert "remote-openai-responses" in str(e.value)
    assert "remote-openai-compatible" in str(e.value)


# ------------------------------------------------- config-level safety (all backends)

_BACKENDS = ["remote-claude", "remote-gemini",
             "remote-openai-responses", "remote-openai-compatible"]


@pytest.mark.parametrize("backend", _BACKENDS)
@pytest.mark.parametrize("key", [None, "", "   "])
def test_an_empty_api_key_is_refused_rather_than_falling_back_to_the_env(
    backend, key, monkeypatch
):
    """Every vendor SDK falls back to its own env var when handed no key, which
    would make the config a false record of the account a run used. The factory
    refuses before building a client."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "env-key")
    with pytest.raises(ValueError) as e:
        build_chat_client({"backend": backend, "model": "m", "api_key": key})
    assert "api_key" in str(e.value)


@pytest.mark.parametrize("backend", _BACKENDS)
def test_timeout_s_reaches_every_backend(backend):
    """llm.timeout_s must reach every adapter."""
    c = build_chat_client({"backend": backend, "model": "m", "api_key": "k",
                           "timeout_s": 1234})
    assert c.timeout_s == 1234


@pytest.mark.parametrize("backend", _BACKENDS)
def test_every_adapter_takes_api_key_first(backend):
    """One positional order across all four: (api_key, model_name)."""
    c = build_chat_client({"backend": backend, "model": "the-model",
                           "api_key": "the-key"})
    assert (c.api_key, c.model_name) == ("the-key", "the-model")


def test_temperature_is_dropped_with_a_warning_not_a_400(caplog):
    """The reasoning families 400 on temperature and the rest ignore it, so the
    adapter never sends it and warns once per client."""
    c = _client()
    with caplog.at_level("WARNING"):
        c._warn_temperature_dropped(0.5)
        c._warn_temperature_dropped(0.5)      # said once per client, not per call
    assert sum("temperature dropped" in r.message for r in caplog.records) == 1


def test_a_rejected_reply_is_not_copied_into_the_exception_message():
    """The rejected text belongs in OutputFormatViolation.raw, which the runner
    writes to the transcript, not in every chained traceback."""
    from orrery.infra.llm.validation import clean_json
    body = "no json here " * 500
    with pytest.raises(ValueError) as e:
        clean_json(body)
    message = str(e.value)
    assert "no json here" not in message      # not even one copy of the body
    assert len(message) < 200                 # a length, not the payload


def test_describe_response_names_the_shape_it_got():
    """An empty reply is described by status, token counts and item kinds,
    which decide between a degraded service and an adapter that failed to read
    what it was sent. A truncated dump of the response JSON can land inside an
    encrypted reasoning blob and say none of it."""
    from orrery.infra.llm.remote.openai import RemoteChatOpenAI as R
    described = R._describe_response(_Obj(
        status="completed", incomplete_details=None, error=None,
        usage=_Obj(input_tokens=9000, output_tokens=512,
                   output_tokens_details=_Obj(reasoning_tokens=512)),
        output=[_Obj(type="reasoning", summary=[],
                     encrypted_content="Z" * 8000)]))
    assert "status='completed'" in described
    assert "out=512" in described and "reasoning=512" in described
    assert "0 summary part(s), 8000 char(s) encrypted" in described
    assert "Z" * 20 not in described          # a length, never the ciphertext
    assert len(described) < 300               # bounded by items, not by size


def test_describe_response_names_an_item_this_adapter_cannot_read():
    """An item kind the adapter cannot read is named as such, rather than
    filed as the service's fault."""
    from orrery.infra.llm.remote.openai import RemoteChatOpenAI as R
    described = R._describe_response(_Obj(
        status="completed",
        output=[_Obj(type="custom_tool_call", name="submit")]))
    assert "output.custom_tool_call" in described
    assert "does not read it" in described


# ------------------------------------------- nothing goes on the wire uninvited

def test_headers_come_only_from_config():
    """The factory recognises no endpoint: whatever the url, a request carries
    the configured headers and nothing else. A relay's own header requirements
    are stated where that endpoint is configured."""
    for url in ("https://api.bltcy.ai/v1", "https://some.relay.example/v1", None):
        c = build_chat_client({"backend": "remote-claude", "model": "m",
                               "api_key": "k", "url": url})
        added = {k.lower() for k in (c.client.default_headers or {})}
        assert "anthropic-beta" not in added

    c = build_chat_client({"backend": "remote-claude", "model": "m", "api_key": "k",
                           "url": "https://api.bltcy.ai/v1",
                           "extra_headers": {"anthropic-beta": "x", "user-agent": "curl/8.7.1"}})
    sent = {k.lower(): v for k, v in dict(c.client.default_headers).items()}
    assert sent["anthropic-beta"] == "x" and sent["user-agent"] == "curl/8.7.1"


def test_no_seed_is_sent_unless_the_caller_asks():
    """A seed reaches the wire only when the caller passes one; the adapter
    supplies no default."""
    import inspect
    src = inspect.getsource(RemoteChatOpenAICompatible.invoke)
    assert 'kwargs.pop("seed", None)' in src
    assert 'kwargs.pop("seed", 42)' not in src


# ------------------------------------------------------------ claude max_tokens

def test_max_tokens_is_a_constant_clamped_by_the_family_ceiling():
    """Anthropic requires max_tokens, so the backend sends a fixed default
    clamped to the family ceiling: the families cap at 128000 / 64000 / 16384
    and exceeding a cap is a 400."""
    from orrery.infra.llm.remote.claude import (
        _DEFAULT_MAX_TOKENS, _max_output_tokens,
    )
    assert _max_output_tokens("claude-sonnet-5") == _DEFAULT_MAX_TOKENS
    assert _max_output_tokens("claude-haiku-4-5") == _DEFAULT_MAX_TOKENS
    assert _max_output_tokens("some-unknown-model") == 16384   # the low fallback


def test_max_tokens_no_longer_moves_with_the_timeout():
    from orrery.infra.llm.remote.claude import RemoteChatClaude
    short = RemoteChatClaude(api_key="k", model_name="claude-sonnet-5", timeout_s=60)
    long = RemoteChatClaude(api_key="k", model_name="claude-sonnet-5", timeout_s=3600)
    assert short.max_tokens == long.max_tokens


def test_an_unread_item_type_is_not_dropped_in_silence(caplog):
    """An item the adapter ignored and a service that sent nothing look alike
    downstream but need opposite fixes; only the warning tells them apart."""
    import logging
    with caplog.at_level(logging.WARNING):
        content, _, tool_calls, _ = RemoteChatOpenAI._extract_output(
            _Obj(output=[_Obj(type="custom_tool_call", name="submit")]))
    assert content == "" and tool_calls == []
    assert "custom_tool_call" in caplog.text
