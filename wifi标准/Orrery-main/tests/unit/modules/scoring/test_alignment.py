"""Alignment of a candidate principals model onto the corpus one:
validate_alignment enforces a bijection that carries dependency edges whole,
apply_alignment rewrites names and edges, and align_principals makes the
bilingual LLM call and leaves a transcript behind."""
import asyncio
import json

import pytest

from orrery.modules.scoring.alignment import apply_alignment, validate_alignment
from orrery.pipeline.evaluation.principals import align_principals
from orrery.infra.llm.client import ChatClient, ChatResponse, TokenUsage
from orrery.services.transcript.writer import TranscriptWriter


def _doc(prefix=""):
    return {
        "principals": [{"name": f"{prefix}I"}, {"name": f"{prefix}R"}],
        "values": [
            {"name": f"{prefix}SKI", "derived_from": [],
             "description": "private signing key"},
            {"name": f"{prefix}PKI", "derived_from": [f"{prefix}SKI"],
             "description": "matching verification key"},
            {"name": f"{prefix}ID", "derived_from": [],
             "description": "protocol identity"},
        ],
    }


def _alignment():
    row = lambda c, g: {"candidate": c, "gold": g, "evidence": ["same use"]}
    return {
        "principal_mappings": [row("xI", "I"), row("xR", "R")],
        "symbol_mappings": [
            row("xSKI", "SKI"), row("xPKI", "PKI"), row("xID", "ID")],
    }


def test_validated_alignment_rewrites_names_and_dependency_edges():
    cand, gold = _doc("x"), _doc()
    cand["values"][1]["description"] = "different wording, same key"
    maps = validate_alignment(cand, gold, _alignment())
    got = apply_alignment(cand, maps)
    assert got["values"][0]["name"] == "SKI"
    assert got["values"][1]["name"] == "PKI"
    assert got["values"][1]["derived_from"] == ["SKI"]
    assert got["values"][1]["description"] == "different wording, same key"


def test_alignment_is_a_bijection():
    alignment = _alignment()
    alignment["symbol_mappings"].append(
        {"candidate": "xID", "gold": "PKI", "evidence": []})
    with pytest.raises(ValueError, match="more than once"):
        validate_alignment(_doc("x"), _doc(), alignment)


def test_dependency_must_map_as_one_edge():
    alignment = _alignment()
    alignment["symbol_mappings"] = alignment["symbol_mappings"][1:2]
    with pytest.raises(ValueError, match="must also map its sources"):
        validate_alignment(_doc("x"), _doc(), alignment)


def test_related_but_different_categories_cannot_be_mapped():
    alignment = _alignment()
    alignment["symbol_mappings"] = [{
        "candidate": "xID", "gold": "PKI", "evidence": ["both identify I"]}
    ]
    with pytest.raises(ValueError, match="crosses dependency categories"):
        validate_alignment(_doc("x"), _doc(), alignment)


def test_an_additional_derived_relation_maps_as_one_edge():
    cand, gold = _doc("x"), _doc()
    cand["values"] += [
        {"name": "xh", "derived_from": [], "description": "DH secret"},
        {"name": "xp", "derived_from": ["xh"], "description": "DH public"},
    ]
    gold["values"] += [
        {"name": "h", "derived_from": [], "description": "DH secret"},
        {"name": "p", "derived_from": ["h"], "description": "DH public"},
    ]
    alignment = _alignment()
    row = lambda c, g: {"candidate": c, "gold": g, "evidence": ["same relation"]}
    alignment["symbol_mappings"] += [row("xh", "h"), row("xp", "p")]
    maps = validate_alignment(cand, gold, alignment)
    got = apply_alignment(cand, maps)
    assert got["values"][-2:] == gold["values"][-2:]


class _FakeChat(ChatClient):
    def __init__(self, answer):
        self.answer = answer
        self.efforts = []

    async def invoke(self, messages, tools=None, tool_choice=None,
                     temperature=None, response_format=None, json_schema=None,
                     **kwargs):
        assert json_schema is not None
        self.efforts.append(kwargs.get("effort"))
        return ChatResponse(content=json.dumps(self.answer), usage=TokenUsage())


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_alignment_call_uses_bilingual_prompt_and_leaves_a_trace(tmp_path, lang):
    alignment = _alignment()
    transcript = tmp_path / lang / "transcript.jsonl"
    llm = _FakeChat(alignment)
    got, maps = asyncio.run(align_principals(
        llm, candidate=_doc("x"), gold=_doc(),
        writer=TranscriptWriter(transcript), model="fake", lang=lang))
    assert got == alignment and maps["symbols"]["xSKI"] == "SKI"
    assert [effort.value for effort in llm.efforts] == ["low"]
    assert transcript.is_file()
    assert next((transcript.parent / "rounds").glob("*_prompt.md")).is_file()
