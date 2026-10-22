"""Symbol alignment for assumptions and properties: renaming rewrites only the
reference leaves, the generic symbol map stays bijective, and align_references
makes its call at low effort."""
import asyncio
import json

from orrery.infra.llm.client import ChatClient, ChatResponse, TokenUsage
from orrery.modules.scoring import rules as R
from orrery.modules.scoring.symbols import (
    rename_assumptions, rename_properties, validate_symbol_mappings,
)
from orrery.pipeline.evaluation.symbols import align_references
from orrery.services.transcript.writer import TranscriptWriter


def test_assumption_target_is_renamed_before_the_existing_judgement():
    cand = {"world": [], "variable": [], "fixed": [{
        "id": "c", "axis": "data", "target": {"of": "sk_Initiator"},
        "subtype": "assumed_secure",
    }]}
    gold = {"world": [], "variable": [], "fixed": [{
        "id": "g", "axis": "data", "target": {"of": "SKi"},
        "subtype": "assumed_secure",
    }]}
    assert R.score_assumptions(cand, gold)["num"] == 0
    assert R.score_assumptions_aligned(
        cand, gold, {"sk_Initiator": "SKi"})["num"] == 1


def test_property_reference_is_renamed_before_the_existing_judgement():
    cand = {"properties": [{"id": "c", "type": "Secrecy", "subtype": "basic",
                            "values": ["session_key"], "parties": []}]}
    gold = {"properties": [{"id": "g", "type": "Secrecy", "subtype": "basic",
                            "values": ["SK"], "parties": []}]}
    assert R.score_properties(cand, gold)["num"] == 0
    assert R.score_properties_aligned(
        cand, gold, {"session_key": "SK"})["num"] == 1


def test_renaming_changes_only_reference_leaves():
    assumptions = {"world": [], "fixed": [{
        "id": "keep", "axis": "data", "target": {"of": "x"},
        "subtype": "none"}], "variable": []}
    properties = {"properties": [{
        "id": "keep", "type": "Secrecy", "subtype": "basic",
        "values": ["x"], "parties": ["A"]}]}
    assert rename_assumptions(assumptions, {"x": "y"})["fixed"][0] == {
        "id": "keep", "axis": "data", "target": {"of": "y"},
        "subtype": "none"}
    assert rename_properties(properties, {"x": "y", "A": "I"})[
        "properties"][0]["parties"] == ["I"]


def test_generic_symbol_map_is_bijective():
    rows = [
        {"candidate": "x", "gold": "a"},
        {"candidate": "y", "gold": "b"},
    ]
    assert validate_symbol_mappings(rows, {"x", "y"}, {"a", "b"}) == {
        "x": "a", "y": "b"}


class _Chat(ChatClient):
    def __init__(self):
        self.effort = None

    async def invoke(self, messages, tools=None, tool_choice=None,
                     temperature=None, response_format=None, json_schema=None,
                     effort=None, **kwargs):
        self.effort = effort
        return ChatResponse(content=json.dumps({"mappings": [{
            "candidate": "x", "gold": "y", "evidence": ["same key"]
        }]}), usage=TokenUsage())


def test_generic_alignment_call_uses_low_effort(tmp_path):
    llm = _Chat()
    alignment, mapping = asyncio.run(align_references(
        llm, kind="properties", candidate={"x": 1}, gold={"y": 1},
        candidate_symbols={"x"}, gold_symbols={"y"},
        writer=TranscriptWriter(tmp_path / "transcript.jsonl"),
        model="fake"))
    assert alignment["mappings"][0]["candidate"] == "x"
    assert mapping == {"x": "y"}
    assert llm.effort.value == "low"
