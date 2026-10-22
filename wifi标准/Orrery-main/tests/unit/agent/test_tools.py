"""Tool handlers: a smoke test over a real document set and a temporary run
directory, pinning down the artifact visibility rules and the paging contract."""

import asyncio
import re
from pathlib import Path

import pytest

from orrery.agent.tools.artifact_tools import ARTIFACT_TOOLS
from orrery.agent.tools.context import ToolContext
from orrery.agent.tools.document_tools import DOCUMENT_TOOLS
from orrery.agent.tools.model_tools import MODEL_TOOLS
from orrery.agent.tools.registry import clip, dispatch, to_function_tools
from orrery.modules.document import DocumentLoaderService, ProtocolSource
from orrery.services.transcript.writer import TranscriptWriter
from tests.fixtures import TOY_PROTOCOL

_ALL = DOCUMENT_TOOLS + ARTIFACT_TOOLS + MODEL_TOOLS
_H = {d.name: d.handler for d in _ALL}


@pytest.fixture(scope="module")
def doc_set():
    src = ProtocolSource.from_directory(TOY_PROTOCOL)
    return asyncio.run(DocumentLoaderService().load(src))


def _ctx(doc_set=None, tmp=None, **kw):
    return ToolContext(node="t", doc_set=doc_set, artifacts_root=tmp, **kw)


def test_document_tools(doc_set):
    ctx = _ctx(doc_set)
    first = doc_set.get_sections()[0].number
    assert _H["read_section"](ctx, number=first, doc_id=None)
    # the fixture ships annotations, so the reference resolves
    assert "unresolved" not in _H["get_reference"](ctx, number=first)
    assert "no matches" in _H["grep_document"](ctx, pattern="definitely_absent_xyzzy",
                                               max_matches=5)


def test_artifact_visibility_red_lines(tmp_path):
    (tmp_path / "flow").mkdir()
    (tmp_path / "flow" / "output.pv").write_text("free c: channel.")
    (tmp_path / "_expert").mkdir(parents=True)
    (tmp_path / "_expert" / "notes.md").write_text("expert domain")
    (tmp_path / "10_cross_check").mkdir()
    (tmp_path / "10_cross_check" / "cross_check.json").write_text("{}")
    ctx = _ctx(tmp=tmp_path)

    listed = _H["list_artifacts"](ctx)
    assert "flow/output.pv" in listed
    assert "10_cross_check/cross_check.json" in listed   # an ordinary artifact
    assert "_expert" not in listed                        # hidden domains are not listed

    assert "free c" in _H["read_artifact"](ctx, path="flow/output.pv")
    assert "{}" in _H["read_artifact"](ctx, path="10_cross_check/cross_check.json")
    with pytest.raises(RuntimeError, match="invisible domain"):
        _H["read_artifact"](ctx, path="_expert/notes.md")
    with pytest.raises(RuntimeError, match="escapes the run directory"):
        _H["read_artifact"](ctx, path="../../etc/passwd")
    # a directory is answered, not raised out of the session
    with pytest.raises(RuntimeError, match="is a directory"):
        _H["read_artifact"](ctx, path="flow")
    # a session's filed prompts are its record, behind read_prompt's door
    (tmp_path / "flow" / "rounds").mkdir()
    (tmp_path / "flow" / "rounds" / "00_prompt.md").write_text("the corpus")
    assert "rounds" not in _H["list_artifacts"](ctx)
    with pytest.raises(RuntimeError, match="not an artifact"):
        _H["read_artifact"](ctx, path="flow/rounds/00_prompt.md")


def test_trace_tools(tmp_path, doc_set):
    from orrery.agent.tools.trace_tools import TRACE_TOOLS
    from orrery.infra.llm.client import ChatResponse, TokenUsage
    th = {d.name: d.handler for d in TRACE_TOOLS}
    p = tmp_path / "up.jsonl"
    w = TranscriptWriter(p)
    w.system("upstream sys"); w.user("upstream user")
    w.assistant(ChatResponse(content="answer", usage=TokenUsage(), thinking="pondering"))
    ctx = _ctx(transcript_paths={"init_knowledge": p})
    assert "answer" in th["read_transcript"](ctx, node="init_knowledge",
                                             from_round=1, to_round=None)
    prompt = th["read_prompt"](ctx, node="init_knowledge",
                               from_line=None, to_line=None)
    assert "upstream sys" in prompt
    # the call's own task first, the standing rules after: the system half is
    # the long one (a whole document corpus)
    assert prompt.index("upstream user") < prompt.index("upstream sys")
    with pytest.raises(RuntimeError, match="the readable ones are"):
        th["read_transcript"](ctx, node="no_such_node", from_round=1, to_round=None)
    # the schema allows null for "the default", the way page() takes it
    assert "answer" in th["read_transcript"](ctx, node="init_knowledge",
                                             from_round=None, to_round=None)


def test_reading_pages_by_line_and_never_drops_the_rest(tmp_path):
    """Silent truncation is the danger: a model that cannot tell it saw two
    thirds of a file answers as if it saw all of it. Every window says how much
    is missing and which line fetches the rest."""
    (tmp_path / "big.pv").write_text(
        "\n".join(f"line {i}" for i in range(1, 51)), encoding="utf-8")
    ctx = _ctx(tmp=tmp_path, tool_return_chars=40)

    first = _H["read_artifact"](ctx, path="big.pv", from_line=None, to_line=None)
    assert "lines 1-" in first and "more line(s)" in first
    # the window continues exactly where this one stopped, with no line skipped
    nxt = int(re.search(r"from_line=(\d+)", first).group(1))
    assert f"line {nxt - 1}" in first and f"line {nxt}" not in first
    assert f"line {nxt}" in _H["read_artifact"](ctx, path="big.pv",
                                                from_line=nxt, to_line=None)
    # an explicit window is honoured on both ends
    w = _H["read_artifact"](ctx, path="big.pv", from_line=3, to_line=4)
    assert "line 3" in w and "line 4" in w and "line 5" not in w


def test_page_edges():
    from orrery.agent.tools.registry import page

    # a single over-budget line comes back whole rather than split, so paging
    # always advances instead of re-serving the same first line
    huge = "x" * 100
    assert huge in page(huge, from_line=None, to_line=None, budget=10, label="f")
    # asking past the end says so instead of returning nothing
    assert "past the end" in page("a\nb", from_line=9, to_line=None,
                                  budget=100, label="f")
    short = page("a\nb", from_line=None, to_line=None, budget=100, label="f")
    assert "lines 1-2 of 2" in short and "more line(s)" not in short
    # an inverted window says so, instead of an empty page inviting a re-read
    back = page("a\nb\nc", from_line=3, to_line=2, budget=100, label="f")
    assert "before from_line" in back and "Read on" not in back


def test_model_tools_lookup():
    assert "equation" in _H["lookup_function_signature"](_ctx(), name="ECDH")
    assert "is not in the primitive catalog" in _H["lookup_function_signature"](_ctx(), name="hallucinated_primitive")
    # no self-check tools: submission runs the same checks anyway, and
    # run_proverif would hand query verdicts to the model
    assert set(_H) & {"check_model", "run_proverif"} == set()


def test_dispatch_tolerates_model_typos(tmp_path):
    async def main():
        out = await dispatch(_ALL, _ctx(), {"name": "no_such_tool"})
        # "tool " first: the ledger reads a return starting that way as a
        # failed call, and an unknown tool is one
        assert out.startswith("tool ") and "is unknown" in out
        bad = {"name": "read_section", "arguments_json": None, "arguments": "oops"}
        assert "not a valid JSON object" in await dispatch(_ALL, _ctx(doc_set=None), bad)
    asyncio.run(main())


def test_clip_and_schema_shapes():
    clipped = clip("x" * 100, 40, hint="page through it with from_round.")
    assert "60 not shown" in clipped and "from_round" in clipped
    fts = to_function_tools(_ALL)
    assert {t.name for t in fts} == {d.name for d in _ALL}
