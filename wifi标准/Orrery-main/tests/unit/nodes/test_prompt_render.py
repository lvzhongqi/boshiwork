"""Every prompt in the project renders under jinja2 StrictUndefined with no
placeholder left behind.

Node sys and user templates, realizers, world builders, injectors and expert
all go through the same gate, so a newly added prompt with an undeclared
variable fails here rather than reaching a model verbatim.
"""

from pathlib import Path

import pytest
from jinja2 import UndefinedError

from orrery.agent.compose import render_prompt, render_system
from orrery.nodes.apply.realizers import REALIZERS
from orrery.nodes.inject.injectors import INJECTORS

ROOT = Path(__file__).resolve().parents[3] / "orrery"

# Every node prompt, with the variables its node supplies. The list is written
# out by hand so a template added without declaring what feeds it fails the
# completeness test below.
NODE_PROMPTS = {
    # Framework-injected placeholders ({{ document }} for the corpus block,
    # {{ step_messages }} for the filed messages, {{ form_note }} for the
    # classification result) render to empty here; what matters is that the
    # template declares where they land.
    "nodes/principals/prompts/main.sys.md": {"document": ""},
    "nodes/principals/prompts/main.user.md": {
        "protocol": "P", "gap_targets": "a, b", "step_messages": ""},
    # The document readers. {{ reference }} is the vocabulary the node inlines
    # rather than exposing through a tool; a stand-in stands for it here.
    "nodes/preprocess/prompts/tag_sections.sys.md": {"document": ""},
    "nodes/preprocess/prompts/tag_sections.user.md": {
        "protocol": "P", "step_messages": ""},
    "nodes/assumptions/prompts/main.sys.md": {
        "document": "", "reference": "**data**",
        "world_reference": "**role_binding**"},
    "nodes/assumptions/prompts/main.user.md": {
        "protocol": "P", "knowledge_json": "{}", "flow_pv": "process 0",
        "step_messages": ""},
    "nodes/properties/prompts/main.sys.md": {"document": "", "reference": "**Secrecy**"},
    "nodes/properties/prompts/main.user.md": {
        "protocol": "P", "knowledge_json": "{}", "flow_pv": "process 0",
        "step_messages": ""},
    "nodes/claims/prompts/main.sys.md": {
        "document": "",
        "couplings": "- Secrecy.forward_secrecy: axis data, one of [disclosed]"},
    "nodes/claims/prompts/main.user.md": {
        "protocol": "P", "assumptions_json": "{}", "properties_json": "{}",
        "flow_pv": "process 0", "step_messages": ""},
    "nodes/claims/prompts/alignment.sys.md": {"flow_pv": "process 0"},
    "nodes/claims/prompts/alignment.user.md": {
        "unresolved_json": "{}", "assumptions_json": "{}",
        "properties_json": "{}"},
    "nodes/flow/prompts/main.sys.md": {"document": ""},
    "nodes/flow/prompts/main.user.md": {
        "protocol": "P", "knowledge_json": "{}", "template": "process 0",
        "reference": "Types: host.", "step_messages": ""},
    "nodes/apply/prompts/encode.sys.md": {
        "pv": "process 0", "rules": "<task>rewrite it</task>"},
    "nodes/apply/prompts/encode.user.md": {
        "protocol": "P", "scenario": "s", "target": "of = kAS",
        "step_messages": ""},
    "nodes/apply/prompts/encode_batch.sys.md": {
        "pv": "process 0", "rules": "<task>rewrite all targets</task>"},
    "nodes/apply/prompts/encode_batch.user.md": {
        "assumptions_json": "[]", "step_messages": ""},
    # The world builders share the apply engine's shape: the current model as
    # block 0, the builder's rules block, then a user turn stating the field.
    "nodes/world/prompts/build.sys.md": {
        "pv": "process 0", "rules": "<task>build it</task>"},
    "nodes/world/prompts/build.user.md": {
        "statement": "population = unbounded; principals = A, B",
        "step_messages": ""},
    # The inject node prompts carry the model and this batch's goals, and
    # nothing about the assumptions the model was built under.
    "nodes/inject/prompts/main.sys.md": {
        "pv": "process 0", "rules": "<task>inject them</task>"},
    # {{ unresolved_json }} carries the declaration names extract_claims could
    # not place in the model text. It renders empty whenever every name
    # resolved, which is the common case declared here.
    "nodes/inject/prompts/main.user.md": {
        "goals_json": "[]", "unresolved_json": "", "step_messages": ""},
    "pipeline/evaluation/prompts/principals_alignment.sys.md": {},
    "pipeline/evaluation/prompts/principals_alignment.user.md": {
        "candidate": "{}", "gold": "{}", "schema": "{}"},
    "pipeline/evaluation/prompts/reference_alignment.sys.md": {},
    "pipeline/evaluation/prompts/reference_alignment.user.md": {
        "kind": "assumptions", "candidate": "{}", "gold": "{}",
        "candidate_symbols": "[]", "gold_symbols": "[]", "schema": "{}"},
    # The attack explanations: the script and the scenario's assumptions are
    # rendered by the node; stand-ins stand for them here.
    "nodes/reproduce_attacks/prompts/explain.sys.md": {},
    "nodes/reproduce_attacks/prompts/explain.user.md": {
        "protocol": "P", "scenario": "s", "assumptions": "- k = disclosed",
        "goal": "g (Secrecy.basic): the attacker never obtains v",
        "script": "1. S1 -> X  send  m", "replay": True, "step_messages": ""},
    "nodes/reproduce_attacks/prompts/summary.sys.md": {},
    "nodes/reproduce_attacks/prompts/summary.user.md": {
        "protocol": "P", "cells": "s/g\ng fails", "pending": 2},
    "expert/prompts/session.sys.md": {},
    "expert/prompts/overview.md": {
        "run_name": "r1", "protocol": "P", "subprotocol": None,
        "status": "ok", "from_node": None, "steps": "claims=ok",
        "scenarios": ["honest: g1=true"], "answers": ["g1=true"],
        "gaps": "", "facts": [], "sessions": ["extract_flow"]},
}


def _assert_clean(name: str, text: str) -> None:
    assert text.strip(), f"{name}: rendered to nothing"
    for marker in ("{{", "}}", "{%"):
        assert marker not in text, f"{name}: template marker {marker!r} survived rendering"


@pytest.mark.parametrize("rel", sorted(NODE_PROMPTS))
def test_node_prompt_renders(rel):
    path = ROOT / rel
    # render_prompt takes the *calling module's* file and looks in its
    # prompts/ dir, so hand it any filename inside the owning package.
    caller = path.parent.parent / "node.py"
    _assert_clean(rel, render_prompt(str(caller), path.name, **NODE_PROMPTS[rel]))


def test_every_prompt_file_is_covered():
    """A prompt file with no entry above is never rendered by any test, so a
    typo'd variable in it would go unnoticed."""
    on_disk = {str(p.relative_to(ROOT)) for p in ROOT.rglob("prompts/*.md")
               if "_zh." not in p.name}
    assert on_disk == set(NODE_PROMPTS), (
        f"missing from NODE_PROMPTS: {sorted(on_disk - set(NODE_PROMPTS))}; "
        f"listed but absent: {sorted(set(NODE_PROMPTS) - on_disk)}")


def _zh_of(rel: str) -> str:
    return rel.replace(".sys.md", "_zh.sys.md").replace(".user.md", "_zh.user.md")


@pytest.mark.parametrize("rel", sorted(NODE_PROMPTS))
def test_every_node_prompt_has_a_chinese_twin(rel):
    """`prompt_lang: zh` reads the `_zh` file through compose.localized, so a
    node prompt without a twin fails at run time under an offered config. The
    pairing also keeps the two from drifting, which shows up first as an
    insertion point present in one and not the other."""
    zh = ROOT / _zh_of(rel)
    assert zh.is_file(), f"{rel} has no Chinese twin at {_zh_of(rel)}"
    caller = ROOT / Path(rel).parent.parent / "node.py"
    _assert_clean(_zh_of(rel), render_prompt(str(caller), zh.name,
                                             **NODE_PROMPTS[rel]))


def test_missing_variable_is_an_error_not_a_silent_blank():
    with pytest.raises(UndefinedError):
        render_prompt(str(ROOT / "nodes/principals/node.py"), "main.user.md",
                      protocol="P")


def test_all_realizer_prompts_render():
    n = 0
    for key, cls in sorted(REALIZERS.items()):
        r = cls()
        if r.is_noop or r.is_stub or r.is_code:  # none of them opens a session
            continue
        if r.writings:                       # one .md per writing form
            for form in sorted(r.writings):
                _assert_clean(f"{key}:{form}", r.sys_prompt(form))
        else:
            _assert_clean(str(key), r.sys_prompt())
        n += 1
    assert n >= 10


def test_all_world_builder_prompts_render():
    """Builder prompts live at nodes/world/builders/<axis>/<subtype>/
    rules.sys.md, outside the prompts/ glob above, so they get the same two
    gates enumerated from the registry: every non-noop builder renders clean,
    and a rules file off the registry is an orphan nothing would render."""
    from orrery.nodes.world.builders import BUILDERS

    live = {b for b in BUILDERS.values() if not b.noop}
    d = ROOT / "nodes" / "world" / "builders"
    on_disk = {p.parent for p in d.glob("*/*/rules.sys.md")}
    declared = {b._dir() for b in live}
    assert on_disk == declared, (
        f"rules files without a builder: {sorted(str(x) for x in on_disk - declared)}; "
        f"builders without a rules file: {sorted(str(x) for x in declared - on_disk)}")
    for b in sorted(live, key=lambda x: x.id):
        _assert_clean(b.id, b.sys_prompt())


def test_all_injector_prompts_render():
    n = 0
    for key, cls in sorted(INJECTORS.items()):
        i = cls()
        if i.unimplemented:
            continue
        _assert_clean(str(key), i.sys_prompt())
        n += 1
    assert n >= 6


def test_untagged_prefix_is_its_own_system_block():
    """A leading model needs no semantic wrapper merely to mark a cache cut."""
    from orrery.nodes.apply.realizers import realizer_for

    r = realizer_for("data", "assumed_secure")
    blocks = render_system(str(ROOT / "nodes/apply/node.py"), "encode.sys.md",
                           cut_after=[], cut_after_prefix=True, pv="process 0",
                           rules=r.sys_prompt())
    assert blocks[0] == "```proverif\nprocess 0\n```"
    assert "current_model" not in "".join(blocks)


def test_apply_sessions_share_the_model_block():
    """Every encoding session that starts from the same text carries that text
    as block 0, byte-identical — which is what the prompt cache keys on."""
    from orrery.nodes.apply.node import build_encode_prompt
    from orrery.nodes.apply.realizers import realizer_for

    pv = "(* a model *)\nprocess 0"
    a = build_encode_prompt(pv, realizer_for("data", "assumed_secure"),
                            {"of": "kAS"})
    b = build_encode_prompt(pv, realizer_for("key_reuse", "observed"),
                            {"of": "kAS"})
    assert a.system[0] == b.system[0]


def test_admission_prompt_sees_the_complete_model_and_names_only_the_capability():
    """Admission is interpreted globally in one session: the complete model is
    block 0 and the rules name only the capability."""
    from orrery.nodes.apply.node import build_encode_prompt
    from orrery.nodes.apply.realizers import realizer_for

    pv = "(* producer *)\nlet issue = 0.\n(* consumer *)\nprocess 0"
    prompt = build_encode_prompt(
        pv, realizer_for("admission", "open"), {"scope": "peer_auth"})
    assert prompt.system[0] == f"```proverif\n{pv}\n```"
    rules = "\n".join(prompt.system[1:])
    assert "every consumer" in rules and "Read the whole model" in rules
    assert "table_registration" not in rules
    assert "certificate_enrolment" not in rules
