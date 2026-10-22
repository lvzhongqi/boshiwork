"""Contract tests for the semantic principals submission schema."""

from orrery.nodes.principals.node import _SCHEMA


def test_schema_has_only_principals_and_values():
    assert set(_SCHEMA["properties"]) == {"principals", "values"}
    assert set(_SCHEMA["required"]) == {"principals", "values"}


def test_each_value_is_name_dependency_and_description_only():
    value = _SCHEMA["properties"]["values"]["items"]
    assert set(value["properties"]) == {
        "name", "derived_from", "description",
    }
    assert set(value["required"]) == {
        "name", "derived_from", "description",
    }
    assert value["additionalProperties"] is False
