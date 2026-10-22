"""Fixed data assumptions share calls only when their encodings are compatible."""

import asyncio
import json

from orrery.infra.llm.client import ChatClient, ChatResponse, TokenUsage
from orrery.modules.libschema.model import Point
from orrery.nodes.apply.node import (
    _batch_coverage_problems,
    apply_fixed_data_points,
    build_batch_encode_prompt,
    fixed_data_groups,
)
from orrery.nodes.apply.realizers import realizer_for
from orrery.nodes.base import RunEnv
from orrery.services.store.layout import RunLayout


def _point(name, *, subtype="disclosed"):
    return Point(axis="data", subtype=subtype, target={"of": name},
                 ref_id=f"data_{name.lower()}")


PV = """free c: channel.
type host.
process
  new A: host;
  new B: host;
  0
"""


def test_same_subtype_and_writing_share_one_group():
    groups = fixed_data_groups([_point("A"), _point("B")], PV)
    assert len(groups) == 1
    realizer, form, points = groups[0]
    assert realizer.id == "data.disclosed"
    assert form == "branch_leak"
    assert [point.ref_id for point in points] == ["data_a", "data_b"]


def test_different_subtypes_never_share_rules():
    groups = fixed_data_groups(
        [_point("A"), _point("B", subtype="assumed_secure")], PV)
    assert len(groups) == 2
    assert {realizer.id for realizer, _form, _points in groups} == {
        "data.disclosed", "data.assumed_secure"}


def test_batch_coverage_is_exact_and_complete():
    good = {"coverage": [
        {"assumption": "data_a"}, {"assumption": "data_b"}]}
    assert _batch_coverage_problems(good, ["data_a", "data_b"]) == []
    bad = {"coverage": [
        {"assumption": "data_a"}, {"assumption": "data_a"},
        {"assumption": "outside"}]}
    text = "\n".join(_batch_coverage_problems(bad, ["data_a", "data_b"]))
    assert "repeats" in text and "omits" in text and "outside" in text


def test_batch_prompt_carries_every_id_and_has_bilingual_templates():
    points = [_point("A"), _point("B")]
    realizer = realizer_for("data", "disclosed")
    en = build_batch_encode_prompt(
        PV, realizer, points, form="branch_leak", lang="en")
    zh = build_batch_encode_prompt(
        PV, realizer, points, form="branch_leak", lang="zh")
    assert all(name in en.user for name in ("data_a", "data_b"))
    assert "complete batch" in en.user
    assert "完整编码这一批" in zh.user
    assert set(en.submit.schema["required"]) == {"coverage", "edits"}


class _Chat(ChatClient):
    def __init__(self):
        self.calls = 0

    async def invoke(self, messages, tools=None, tool_choice=None, **kwargs):
        self.calls += 1
        submission = {
            "coverage": [
                {"assumption": "data_a", "model_term": "A",
                 "evidence": "new A: host"},
                {"assumption": "data_b", "model_term": "B",
                 "evidence": "new B: host"},
            ],
            "edits": [{
                "anchor": "  0",
                "position": "replace",
                "text": "  out(c, A); out(c, B)",
            }],
        }
        call = {"id": "submit_1", "type": "function", "name": "submit",
                "arguments": json.dumps(submission),
                "arguments_json": submission}
        return ChatResponse(content="", usage=TokenUsage(), tool_calls=[call])


def test_two_fixed_disclosures_use_one_model_call(tmp_path, monkeypatch):
    async def checks(_names, _payload, **_kwargs):
        return []

    monkeypatch.setattr("orrery.nodes.apply.node.run_checks", checks)
    layout = RunLayout(tmp_path / "wr", "P", "run1")
    layout.run_dir.mkdir(parents=True)
    layout.open_node("build_root")
    chat = _Chat()
    env = RunEnv(
        protocol_dir=tmp_path, layout=layout,
        config={
            "prompt_lang": "en",
            "llm": {"model": "fake"},
            "agent": {"max_rounds": 3, "max_tool_calls": 3,
                      "max_repairs": 2, "tool_return_chars": 1000},
        },
        _llm=chat,
    )
    notes = []
    got = asyncio.run(apply_fixed_data_points(
        env, [_point("A"), _point("B")], None, PV, notes,
        home=layout.node_dir("build_root"), step_path="build_root"))

    assert chat.calls == 1
    assert "out(c, A); out(c, B)" in got
    assert len(notes) == 2 and all("fixed_data_batch_disclosed" in n
                                   for n in notes)
    batch = layout.find_apply_point_dir(
        layout.node_dir("build_root"),
        "fixed_data_batch_disclosed_branch_leak")
    assert json.loads((batch / "members.json").read_text())["assumptions"] == [
        "data_a", "data_b"]
