"""Unit tests for semantic principals/value checks."""

import asyncio

from orrery.checks.registry import must_failures, run_checks
from orrery.checks.rules.entities import ENTITY_CHECK_NAMES
from orrery.checks.rules.init_knowledge import IK_CHECK_NAMES


def _payload(**over):
    payload = {
        "principals": [
            {"name": "A", "description": "initiator"},
            {"name": "B", "description": "responder"},
        ],
        "values": [
            {"name": "SKA", "derived_from": [],
             "description": "A's private key"},
            {"name": "PKA", "derived_from": ["SKA"],
             "description": "A's corresponding public key"},
        ],
    }
    payload.update(over)
    return payload


def _failures(payload):
    return must_failures(asyncio.run(run_checks(IK_CHECK_NAMES, payload)))


def test_semantic_value_inventory_happy_path():
    assert _failures(_payload()) == []


def test_malformed_names_descriptions_and_dependencies_are_loud():
    text = "\n".join(_failures(_payload(values=[
        {"name": "bad name", "derived_from": [], "description": ""},
        {"name": "PKA", "derived_from": ["missing", "missing"],
         "description": "public key"},
    ])))
    assert "may use only letters" in text
    assert "description must be" in text
    assert "repeats a source" in text


def test_dependency_must_name_a_declared_value():
    text = "\n".join(_failures(_payload(values=[
        {"name": "PKA", "derived_from": ["SKA"],
         "description": "public key"},
    ])))
    assert "not another declared value" in text


def test_dependency_graph_must_be_acyclic():
    text = "\n".join(_failures(_payload(values=[
        {"name": "A1", "derived_from": ["B1"], "description": "one"},
        {"name": "B1", "derived_from": ["A1"], "description": "two"},
    ])))
    assert "contains a cycle" in text


def test_duplicate_value_names_are_caught():
    text = "\n".join(_failures(_payload(values=[
        {"name": "K", "derived_from": [], "description": "one"},
        {"name": "K", "derived_from": [], "description": "two"},
    ])))
    assert "already defined" in text


def test_removed_schema_fields_are_rejected_loudly():
    payload = _payload(signing_keypairs=[])
    payload["values"][0]["held_by"] = ["A"]
    text = "\n".join(_failures(payload))
    assert "unsupported top-level" in text
    assert "unsupported fields" in text


def _principals_payload(principals):
    return {"entities": {p["name"]: p["description"] for p in principals},
            "principals": principals}


def test_duplicate_principal_names_are_caught():
    dupe = [{"name": "A", "description": "initiator"},
            {"name": "B", "description": "responder"},
            {"name": "A", "description": "initiator again"}]
    text = "\n".join(must_failures(asyncio.run(
        run_checks(ENTITY_CHECK_NAMES, _principals_payload(dupe)))))
    assert "'A'" in text and "more than once" in text
