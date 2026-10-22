"""The scaffold template handed to the flow model, and its fixed band."""

from orrery.nodes.flow.node import _fixed_lines
from orrery.nodes.flow.template import render_template, template_reference

KNOWLEDGE = {
    "principals": [
        {"name": "A", "description": "initiator"},
        {"name": "B", "description": "responder"},
    ],
    "values": [
        {"name": "SKA", "derived_from": [], "description": "A private key"},
        {"name": "PKA", "derived_from": ["SKA"],
         "description": "A encryption key"},
    ],
}


def test_channels_cover_every_ordered_pair_of_roles():
    pv = render_template(protocol_name="NSPK", knowledge=KNOWLEDGE)
    declared = {ln for ln in pv.splitlines() if ln.startswith("free channel_")}
    # named channels ship [private]; removing the probe puts them back to
    # public before anything downstream sees them
    assert declared == {"free channel_A_B: channel [private].",
                        "free channel_B_A: channel [private]."}
    assert "free c: channel." in pv


def test_the_fixed_band_is_only_channels_probe_queries_and_setting():
    # _fixed_lines picks out exactly what flow_fixed_parts enforces, so a
    # template line drifting into or out of this band changes the contract
    fixed = _fixed_lines(render_template(protocol_name="NSPK", knowledge=KNOWLEDGE))
    assert sorted(fixed) == [
        "free c: channel.",
        "free channel_A_B: channel [private].",
        "free channel_B_A: channel [private].",
        "query event(reached_A()).",
        "query event(reached_B()).",
        # the honest run is solved for a derivation, not a trace: rebuilding a
        # trace over the [private] channels above burns the gate's whole budget
        "set reconstructTrace = false.",
    ]


def test_the_probe_declarations_are_not_in_the_fixed_band():
    """`event reached_A().` is indistinguishable from a call at the end of a
    body, so a line-wise check would report a deleted declaration as present.
    A query naming an undeclared event is a typecheck error instead."""
    fixed = _fixed_lines(render_template(protocol_name="NSPK", knowledge=KNOWLEDGE))
    assert not any(ln.startswith("event ") for ln in fixed)


def test_the_template_carries_no_instruction_to_the_model():
    # the template text is copied into the base model and from there into every
    # scenario and cell file, so instructions belong in the prompt
    pv = render_template(protocol_name="NSPK", knowledge=KNOWLEDGE)
    for word in ("copy", "fill in", "verbatim", "declared on use"):
        assert word not in pv.lower(), f"instruction {word!r} left in the template"
    assert "fun aenc" not in pv                  # the primitive reference is not the template's
    assert "fun aenc" in template_reference(KNOWLEDGE)  # it travels with the task message


def test_the_template_says_nothing_about_the_message_flow():
    pv = render_template(protocol_name="NSPK", knowledge=KNOWLEDGE)
    # role bodies are left open: the flow is the model's to read out of the
    # document
    assert "(* @ROLE A *)" in pv and "(* @ROLE B *)" in pv
    assert "out(channel_" not in pv and "in(channel_" not in pv
    assert "skeleton" not in pv.lower()


def test_the_template_does_not_render_values_signatures_or_main():
    pv = render_template(protocol_name="NSPK", knowledge=KNOWLEDGE)
    assert "SKA" not in pv and "PKA" not in pv
    assert "let processA" not in pv
    assert "process\n" not in pv
    assert "(* @MAIN *)" in pv


def test_reference_offers_primitives_without_selecting_a_dependency_relation():
    reference = template_reference(KNOWLEDGE)
    assert "fun aenc(bitstring, pkey): bitstring." in reference
    assert "reduc" in reference
    assert "let PKA" not in reference
