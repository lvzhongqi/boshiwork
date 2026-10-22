"""The knowledge accessors over the principals artifact: they read the semantic
input in its declared order and add no formal types or holders of their own."""

from orrery.modules.pvtext.knowledge import (
    dependency_map, template_roles, value_names,
)


KNOWLEDGE = {
    "principals": [
        {"name": "A", "description": "initiator"},
        {"name": "B", "description": "responder"},
    ],
    "values": [
        {"name": "SKA", "derived_from": [],
         "description": "A's private decryption key"},
        {"name": "PKA", "derived_from": ["SKA"],
         "description": "A's corresponding encryption key"},
        {"name": "domain", "derived_from": [],
         "description": "the configured group domain"},
    ],
}


def test_accessors_preserve_the_semantic_artifact_order():
    assert template_roles(KNOWLEDGE) == ["A", "B"]
    assert value_names(KNOWLEDGE) == ["SKA", "PKA", "domain"]
    assert dependency_map(KNOWLEDGE) == {
        "SKA": (), "PKA": ("SKA",), "domain": (),
    }


def test_this_layer_does_not_invent_formal_types_or_holders():
    assert set(KNOWLEDGE) == {"principals", "values"}
    for value in KNOWLEDGE["values"]:
        assert set(value) == {"name", "derived_from", "description"}
