"""System blocks: one prompt split at cache-breakpoint boundaries. The claude
adapter marks each block; the other backends join them; the visible prompt
never changes."""
from orrery.infra.llm.client import ChatMessage, Role
from orrery.infra.llm.remote.claude import RemoteChatClaude


def _client(**kw) -> RemoteChatClaude:
    return RemoteChatClaude(api_key="test-key", model_name="claude-opus-5", **kw)


def test_each_block_gets_a_breakpoint():
    param = _client()._build_system_param(["corpus", "node prompt"], cache=True)
    assert [b["text"] for b in param] == ["corpus", "node prompt"]
    assert all(b["cache_control"] == {"type": "ephemeral"} for b in param)


def test_cache_off_joins_blocks():
    param = _client()._build_system_param(["corpus", "node prompt"], cache=False)
    assert param == "corpus\n\nnode prompt"


def test_extra_blocks_merged_to_respect_breakpoint_budget():
    # 4 breakpoints per request, one held by the message rolling breakpoint →
    # at most 3 system blocks are marked; overflow merges, nothing is dropped.
    param = _client()._build_system_param(["a", "b", "c", "d"], cache=True)
    assert len(param) == 3
    assert param[2]["text"] == "c\n\nd"


def test_ttl_marks_system_blocks_and_adds_beta_header():
    c = _client(cache_ttl="1h")
    param = c._build_system_param(["corpus"], cache=True)
    assert param[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "extended-cache-ttl" in str(
        c.client._custom_headers.get("anthropic-beta", ""))


def test_system_list_content_becomes_blocks():
    blocks, _ = _client()._convert_messages(
        [ChatMessage(Role.SYSTEM, ["corpus", "node prompt"]),
         ChatMessage(Role.USER, "hi")])
    assert blocks == ["corpus", "node prompt"]


def test_system_str_content_stays_single_block():
    blocks, _ = _client()._convert_messages(
        [ChatMessage(Role.SYSTEM, "prompt"), ChatMessage(Role.USER, "hi")])
    assert blocks == ["prompt"]
