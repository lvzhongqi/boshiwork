"""The scoring driver: what it writes, what it puts on the bus, and the three
cases where it stays quiet. The judgements themselves are tested on literals in
tests/unit/modules/scoring; here only the orchestration is under test.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from tests.fixtures import PROVERIF_STUB

from orrery.infra.llm.client import ChatClient, ChatResponse, TokenUsage
from orrery.pipeline.main import _score_node, _score_principals_node

GOLD_PRINCIPALS = {
    "principals": [{"name": "A"}, {"name": "B"}],
    "values": [
        {"name": "SKA", "derived_from": [], "description": "private key"},
        {"name": "PKA", "derived_from": ["SKA"], "description": "public key"},
        {"name": "A", "derived_from": [], "description": "identity"},
    ],
}


class _Bus:
    def __init__(self):
        self.events = []

    def emit(self, e):
        self.events.append(e)


class _AlignmentChat(ChatClient):
    async def invoke(self, messages, tools=None, tool_choice=None,
                     temperature=None, response_format=None, json_schema=None,
                     **kwargs):
        return ChatResponse(content=json.dumps({
            "principal_mappings": [], "symbol_mappings": [],
        }), usage=TokenUsage())


def _env(tmp_path, *, pinned=(), gt=True, principals=GOLD_PRINCIPALS):
    """A run with one step's directory on disk, and a corpus beside it."""
    run = tmp_path / "run"
    node_dir = run / "01_extract_principals"
    node_dir.mkdir(parents=True)
    if principals is not None:
        (node_dir / "principals.json").write_text(json.dumps(principals))
    corpus = tmp_path / "corpus"
    (corpus / "flow").mkdir(parents=True)
    (corpus / "flow" / "principals.json").write_text(json.dumps(GOLD_PRINCIPALS))
    layout = SimpleNamespace(
        run_dir=run, run_name="R01",
        find_node_dir=lambda name: (node_dir if name == "extract_principals"
                                    else None))
    return SimpleNamespace(layout=layout, protocol_id="P",
                           ground_truth=str(corpus) if gt else None,
                           pinned=lambda: frozenset(pinned))


def _summary(env):
    return json.loads((env.layout.run_dir / "eval" / "summary.json").read_text())


def test_a_scored_step_writes_its_file_and_says_the_numbers(tmp_path):
    env, bus = _env(tmp_path), _Bus()
    _score_node("extract_principals", env, bus)

    written = json.loads(
        (env.layout.run_dir / "eval" / "01_principals.json").read_text())
    assert (written["num"], written["den"]) == (3, 3)
    assert written["detail"], "the per-product file is where the detail belongs"

    e, = bus.events
    assert (e.node, e.slug, e.num, e.den) == ("extract_principals",
                                              "principals", 3, 3)
    assert not hasattr(e, "detail"), "the corpus's own entries stay off the bus"


def test_principals_async_alignment_writes_audited_result(tmp_path):
    env, bus = _env(tmp_path), _Bus()
    env.config = {"llm": {"model": "fake"}, "prompt_lang": "en"}
    env.llm = lambda: _AlignmentChat()
    here = env.layout.find_node_dir("extract_principals")
    asyncio.run(_score_principals_node(env, bus, here))

    alignment = json.loads(
        (env.layout.run_dir / "eval" / "01_principals_alignment.json").read_text())
    assert alignment["status"] == "ok"
    assert (env.layout.run_dir / "eval" / "01_principals_alignment"
            / "transcript.jsonl").is_file()
    e, = [event for event in bus.events if hasattr(event, "slug")]
    assert (e.num, e.den, e.alignment) == (3, 3, [])


def test_the_summary_carries_numbers_and_no_detail(tmp_path):
    env = _env(tmp_path)
    _score_node("extract_principals", env, _Bus())
    row = _summary(env)["products"]["extract_principals"]
    assert row["slug"] == "principals" and row["num"] == 3
    assert "detail" not in row


def test_an_imperfect_extraction_scores_below_the_corpus(tmp_path):
    """A missing stable value stays in the denominator."""
    env = _env(tmp_path, principals={
        "principals": [{"name": "A"}],
        "values": [GOLD_PRINCIPALS["values"][0],
                   GOLD_PRINCIPALS["values"][2]]})
    _score_node("extract_principals", env, _Bus())
    row = _summary(env)["products"]["extract_principals"]
    assert (row["num"], row["den"]) == (2, 3)


@pytest.mark.parametrize("case", ["no_corpus", "supplied", "no_product"])
def test_the_three_quiet_cases_write_nothing(tmp_path, case):
    env = _env(tmp_path,
               gt=case != "no_corpus",
               pinned=("extract_principals",) if case == "supplied" else (),
               principals=None if case == "no_product" else GOLD_PRINCIPALS)
    bus = _Bus()
    _score_node("extract_principals", env, bus)
    assert bus.events == []
    assert not (env.layout.run_dir / "eval").exists()


def test_a_step_the_corpus_does_not_answer_is_not_scored(tmp_path):
    env, bus = _env(tmp_path), _Bus()
    _score_node("build_root", env, bus)
    assert bus.events == [] and not (env.layout.run_dir / "eval").exists()


def test_a_broken_scorer_does_not_break_the_run(tmp_path, caplog):
    """Measuring the run is not part of doing it."""
    env, bus = _env(tmp_path, principals={"principals": "not a list"}), _Bus()
    _score_node("extract_principals", env, bus)
    assert bus.events == []
    assert "scoring extract_principals" in caplog.text


# ── the one-way pairing rule: principals may be supplied alone, flow may not ──
# Enough of a config to load: every backend talks to a vendor, so the live
# slot's key is required before a Run can be built at all, and so is a solver
# for a table that runs one.
_RUNNABLE = {"pipeline": {},
             "llm": {"profiles": {"remote-openai-responses": {"api_key": "k"}}},
             "proverif": {"executable": str(PROVERIF_STUB)}}


def test_a_mother_model_needs_its_principals(tmp_path):
    from orrery.pipeline.main import Run
    with pytest.raises(ValueError, match="flow supplied without principals"):
        Run("P", tmp_path, _RUNNABLE, flow="flow.pv")


def test_principals_may_be_supplied_on_their_own(tmp_path):
    """Principals without a flow is a measurement setup: the flow extraction is
    then the only thing the comparison is about."""
    from orrery.pipeline.main import Run
    run = Run("P", tmp_path, _RUNNABLE, principals="principals.json")
    assert run.principals == "principals.json" and run.flow is None
