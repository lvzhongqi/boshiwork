"""The monolithic baseline receives one complete, already-selected scenario."""

import pytest

from experiments.oneshot.prompt import build_prompt
from experiments.oneshot.reference import modeling_rules_reference
from experiments.oneshot.runner import prompt_lang
from orrery.modules.libschema.model import Goal, Point, Scenario, WorldEntry


def test_the_prompt_language_is_the_config_key_the_pipeline_reads():
    """The baseline reads the pipeline's prompt_lang key and has no flag of its
    own; an unknown value raises ValueError."""
    assert prompt_lang({}) == "en"
    assert prompt_lang({"prompt_lang": "zh"}) == "zh"
    with pytest.raises(ValueError, match="prompt_lang"):
        prompt_lang({"prompt_lang": "fr"})


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_prompt_carries_world_and_only_the_current_scenario(lang):
    system, user = build_prompt(
        corpus="document", protocol="P",
        world_json='[{"axis": "role_binding", "subtype": "any_roles"}]',
        scenario_name="baseline", scenario_json="[]",
        properties_json="[]", goal_ids=[], modeling_rules="selected rules",
        lang=lang,
    )

    rendered = "\n".join([*system, user])
    assert "role_binding" in rendered
    assert "any_roles" in rendered
    assert "<context>" in rendered
    assert "<input>" in rendered
    assert "assumption space" not in rendered
    assert "假设空间" not in rendered
    assert "never bound the number of sessions" not in rendered
    assert "Replicate every role" not in rendered
    assert "不要限制会话数量" not in rendered
    assert "复制每个角色" not in rendered
    assert "selected rules" in rendered
    assert "{{" not in rendered

    system_text = "\n".join(system)
    assert system_text.index("<flow_defaults>") < system_text.index("<selected_rules>")


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_modeling_rules_are_selected_from_mainline_registries(lang):
    rules = modeling_rules_reference(
        world=(WorldEntry("world_roles", "role_binding", "any_roles"),),
        scenario=Scenario((Point(
            "admission", "open", {"scope": "peer_auth"}, "admission_peer"),)),
        goals=[Goal(
            "auth", "Authentication", ("A",),
            {"subject": "A", "asserter": "B"}, "injective_agreement")],
        lang=lang,
    )

    assert '<rule id="role_binding.any_roles"' in rules
    assert '<rule id="admission.open"' in rules
    assert '<rule id="Authentication.injective_agreement"' in rules
    assert '<applies_to>\n{"scope": "peer_auth"}\n</applies_to>' in rules
    assert "<identity_modeling_library>" in rules
    assert "<time_variant_modeling_library>" in rules
    assert "<structure_modeling_library>" in rules


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_one_rule_text_carries_every_target_that_selected_it(lang):
    """The mainline batches same-subtype-same-writing points into one session;
    the monolithic request has one session, so the rule text appears once."""
    rules = modeling_rules_reference(
        world=(),
        scenario=Scenario((
            Point("data", "disclosed", {"of": "A"}, "d1"),
            Point("data", "disclosed", {"of": "B"}, "d2"),
            Point("data", "disclosed", {"of": "PKA"}, "d3"),
        )),
        goals=[],
        lang=lang)

    assert rules.count('<rule id="data.disclosed"') == 2  # one per writing
    for form, lifetime in (("branch_leak", "long_lived"),
                           ("draw_leak", "per_session")):
        head = (f'<rule id="data.disclosed" mode="llm" form="{form}" '
                f'lifetime="{lifetime}">')
        assert head in rules
    for name in ("A", "B", "PKA"):
        assert rules.count(f'{{"of": "{name}"}}') == 2

