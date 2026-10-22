"""Every request the pipeline can send still assembles.

orrery.utils.prompts (the `orrery prompt` command) calls each node's
build_prompt, and for some builders it is the only caller outside a live run —
so a broken builder would otherwise stay green until a run hit it.

These tests assert assembly, not wording, and write nothing; pinning rendered
bytes here would turn every prompt edit into a test failure.
"""

import inspect
from pathlib import Path

import pytest

from orrery.utils import prompts as rp


ALL_REQUESTS = [
    (stem, prompt)
    for group in (rp.extraction_requests, rp.apply_requests,
                  rp.inject_requests, rp.expert_requests)
    for stem, prompt in group()
]


def test_every_group_contributes():
    """A group that yields nothing would silently drop whole nodes from the
    preview."""
    for group in (rp.extraction_requests, rp.apply_requests,
                  rp.inject_requests, rp.expert_requests):
        assert list(group()), f"{group.__name__} produced no request"


def test_stems_are_unique():
    """Two requests sharing a stem would overwrite each other's file."""
    stems = [s for s, _ in ALL_REQUESTS]
    assert len(stems) == len(set(stems))


@pytest.mark.parametrize("stem,prompt", ALL_REQUESTS,
                         ids=[s for s, _ in ALL_REQUESTS])
def test_request_renders(stem, prompt):
    text = rp.as_markdown(prompt)
    assert prompt.system and all(b.strip() for b in prompt.system), \
        f"{stem}: an empty system block"
    assert prompt.user.strip(), f"{stem}: empty user message"
    assert prompt.label, f"{stem}: no label"
    # A jinja placeholder that survived rendering reaches the model verbatim.
    assert "{{" not in text and "}}" not in text, f"{stem}: unrendered placeholder"
    # The delivery format is appended on the way out, never by the node.
    assert text.count("<output_format>") == 1, f"{stem}: output_format not appended once"


def test_claims_prompt_accepts_declarations_and_flow_not_full_vocabulary():
    """Claims pairs the two upstream products and takes flow for canonical
    model names; the full vocabulary catalogues stay out of its prompt."""
    from orrery.nodes.claims.node import build_prompt

    params = inspect.signature(build_prompt).parameters
    assert "assumptions_json" in params and "properties_json" in params
    assert "flow_pv" in params
    assert "assumption_reference" not in params
    assert "property_reference" not in params


def test_claims_prompt_inlines_flow_for_name_alignment():
    from orrery.nodes.claims.node import build_prompt

    prompt = build_prompt(
        corpus="document claim", protocol="P",
        assumptions_json="{}", properties_json="{}",
        flow_pv="free exact_flow_name: bitstring.",
    )
    assert "document claim" in "\n".join(prompt.system)
    assert "free exact_flow_name: bitstring." in prompt.user


def test_assumption_and_claim_prompts_preserve_variable_flow_default():
    """A variable domain may need its noop value for the ordinary document
    world to be representable; only fixed entries are redundant defaults."""
    from orrery.nodes.assumptions.node import build_prompt as assumptions_prompt
    from orrery.nodes.claims.node import build_prompt as claims_prompt

    assumptions = assumptions_prompt(corpus="doc", protocol="P")
    claims = claims_prompt(
        corpus="doc", protocol="P", assumptions_json="{}",
        properties_json="{}", flow_pv="process 0")

    assumption_system = " ".join("\n".join(assumptions.system).split())
    claims_system = " ".join("\n".join(claims.system).split())
    assert "Include the flow-state subtype" in assumption_system
    assert "A **fixed** entry that matches it is redundant" in assumption_system
    assert "only when every omitted variable declares its flow-state subtype" in claims_system
    assert "name the variable id and the missing flow-state subtype" in claims_system


def test_broken_primitive_prompt_keeps_complete_mechanism_examples():
    """The broken-primitive realizer keeps executable examples without
    declaring the inverse destructor a second time as a function."""
    prompt_dir = (
        Path(__file__).resolve().parents[3]
        / "orrery/nodes/apply/realizers/primitive/broken"
    )
    for name in ("rules.sys.md", "rules_zh.sys.md"):
        text = (prompt_dir / name).read_text(encoding="utf-8")
        assert "target.family" in text
        assert "<examples>" in text
        assert "reduc forall" in text
        assert "fun discreteLog" not in text


def test_assumed_secure_uses_one_not_attacker_premise():
    prompt_dir = (
        Path(__file__).resolve().parents[3]
        / "orrery/nodes/apply/realizers/data/assumed_secure"
    )
    for name in ("rules.sys.md", "rules_zh.sys.md"):
        text = (prompt_dir / name).read_text(encoding="utf-8")
        assert "not attacker(new K)." in text
        assert "not attacker(K)." in text
        assert "restriction attacker(" not in text
        assert "nounif" not in text
        assert "query attacker(" not in text
