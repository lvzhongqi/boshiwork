"""Tests the transcript service: write-read round trips, recovery from a half
line left by a kill, round and thinking extraction, and the prompt.md layout."""

from orrery.infra.llm.client import (
    ChatMessage, ChatResponse, Role, TokenUsage,
)
from orrery.services.transcript.reader import TranscriptReader
from orrery.services.transcript.resume import load_messages
from orrery.services.transcript.writer import TranscriptWriter

TOOL_CALL = {"id": "call_1", "type": "function", "name": "read_section",
             "arguments": '{"sec": "3.3"}', "arguments_json": {"sec": "3.3"}}


def _write_session(path):
    w = TranscriptWriter(path)
    w.meta(node="init_knowledge", model="claude-opus-5")
    w.system("you are the extractor")
    w.user("extract each NSPK party's initial knowledge")
    w.assistant(ChatResponse(content="", usage=TokenUsage(input_tokens=10),
                             tool_calls=[TOOL_CALL], thinking="check §3.3 first"))
    w.tool_result("call_1", "read_section", "the body of §3.3 ...")
    w.assistant(ChatResponse(content="A holds skA, pkB", usage=TokenUsage(),
                             thinking=None))
    return w


def test_roundtrip_equals(tmp_path):
    path = tmp_path / "transcript.jsonl"
    _write_session(path)
    expected = [
        ChatMessage(Role.SYSTEM, "you are the extractor"),
        ChatMessage(Role.USER, "extract each NSPK party's initial knowledge"),
        ChatMessage(Role.ASSISTANT, "", tool_calls=[TOOL_CALL], thinking="check §3.3 first"),
        ChatMessage(Role.TOOL, "the body of §3.3 ...", tool_call_id="call_1"),
        ChatMessage(Role.ASSISTANT, "A holds skA, pkB"),
    ]
    assert load_messages(path) == expected


def test_a_dangling_call_is_padded_even_when_its_id_was_answered_before(tmp_path):
    """gemini synthesises call ids from the position in the reply, so the
    same id comes back round after round. Whether the last round's call was
    answered is decided by the results after that round's entry, not by any
    result anywhere in the session."""
    path = tmp_path / "transcript.jsonl"
    w = TranscriptWriter(path)
    w.system("s")
    w.user("u")
    call = dict(TOOL_CALL, id="call_0_read_section")
    w.assistant(ChatResponse(content="", usage=TokenUsage(), tool_calls=[call]))
    w.tool_result("call_0_read_section", "read_section", "the body")
    w.assistant(ChatResponse(content="", usage=TokenUsage(), tool_calls=[call]))
    # killed here: the second call never got its result
    msgs = load_messages(path)
    assert msgs[-1].role == Role.TOOL and msgs[-1].tool_call_id == "call_0_read_section"
    assert "interrupted" in msgs[-1].content


def test_truncated_tail_drops_only_last_line(tmp_path):
    path = tmp_path / "transcript.jsonl"
    _write_session(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write('{"t": "assistant", "content": "half a line before the kill')   # no trailing newline
    msgs = load_messages(path)
    assert len(msgs) == 5                       # the half line is dropped, everything before it survives
    assert msgs[-1].content == "A holds skA, pkB"


def test_rounds_and_thinking(tmp_path):
    path = tmp_path / "transcript.jsonl"
    w = _write_session(path)
    w.interrupted("user_abort")                 # marker lines affect neither restoration nor the round split
    r = TranscriptReader(path)
    rounds = r.rounds()
    assert len(rounds) == 2
    assert rounds[0].tool_results[0]["name"] == "read_section"
    assert rounds[1].tool_results == []
    assert r.thinking_only() == ["check §3.3 first"]   # the second round has no thinking and takes no slot
    assert len(load_messages(path)) == 5


def test_slice_reports_remaining(tmp_path):
    path = tmp_path / "transcript.jsonl"
    _write_session(path)
    text, rest = TranscriptReader(path).slice(max_chars=30)
    assert len(text) == 30 and rest is not None and "not shown" in rest
    full, rest2 = TranscriptReader(path).slice()
    assert rest2 is None and "read_section" in full


def test_prompt_md_holds_tools_system_and_user(tmp_path):
    """prompt.md is the readable half of a session: the transcript escapes each
    prompt into one JSON string and records no tool definitions at all."""
    from orrery.infra.llm.client import FunctionTool
    from orrery.services.transcript.prompt import band, is_session_file

    path = tmp_path / "transcript.jsonl"
    tool = FunctionTool(name="submit", description="deliver the product",
                        parameters={"type": "object",
                                    "properties": {"pv": {"type": "string"}}})
    out = TranscriptWriter(path).prompt(
        tools=[tool], system=["the corpus", "the rules"],
        user="build the model")

    assert out == tmp_path / "rounds" / "00_prompt.md"
    text = out.read_text(encoding="utf-8")
    for part in ("submit", "deliver the product", '"pv"',
                 "the corpus", "the rules", "build the model"):
        assert part in text
    assert text.index("submit") < text.index("the corpus") < text.index("build the model")
    # exactly three ruled bands: any non-payload line here reads as prompt text
    assert [ln for ln in text.splitlines() if ln.startswith("---")] == [
        band("TOOLS"), band("SYS"), band("USER")]
    assert "the corpus\n\nthe rules" in text          # blocks joined as the model reads them
    # a session file is a record, not an artifact, and is matched by exact name
    assert is_session_file(path.name)
    assert not is_session_file("output.pv")


def test_a_second_session_owns_a_directory_rather_than_a_stem(tmp_path):
    """A second session gets a directory of its own, because every rule about
    sessions keys on the exact name transcript.jsonl."""
    review = tmp_path / "review" / "transcript.jsonl"
    out = TranscriptWriter(review).prompt(tools=[], system="review it", user="here")
    assert out == tmp_path / "review" / "rounds" / "00_prompt.md"
    assert "```json\n[]\n```" in out.read_text(encoding="utf-8")   # a toolless session sends []


def test_a_full_slot_band_is_a_loud_error(tmp_path):
    """next_slot raises once the two-digit band is full: slot 100 would sort
    before its predecessors and wrap silently."""
    import pytest

    from orrery.services.transcript.prompt import next_slot

    (tmp_path / "99_last.pv").write_text("x")
    with pytest.raises(RuntimeError, match="band is full"):
        next_slot(tmp_path)
    # a wider prefix is parsed in full, so a stray 101 also fills the band
    (tmp_path / "99_last.pv").unlink()
    (tmp_path / "101_stray.pv").write_text("x")
    with pytest.raises(RuntimeError, match="band is full"):
        next_slot(tmp_path)
