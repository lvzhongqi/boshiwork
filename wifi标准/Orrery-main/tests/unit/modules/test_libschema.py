"""libschema over the fixture protocol's five JSON files: the full load chain,
then every gate — superseded key shapes, dangling references, dead scenarios,
flow-state conditions and incomplete world expansion all fail loudly."""

from pathlib import Path

import pytest

from orrery.modules.libschema import io as lio
from orrery.modules.libschema.model import AssumptionsDoc, CaseMatrix
from orrery.modules.libschema.resolve import expand_assignments, world_of
from orrery.modules.libschema.validate import (
    validate_assumptions, validate_cases_results, validate_claims,
)
from orrery.nodes.apply.realizers import VOCAB
from orrery.nodes.inject.injectors import PROP_VOCAB
from tests.fixtures import CLAIMS, RESULTS
from orrery.modules.libschema.version import (
    LibParseError, LibResolveError, LibValidationError,
)





def _noop(axis, subtype):
    """The flow states of the axes these tests touch, as the plain injected
    predicate libschema receives at run time. The vocabularies stay the real
    registry-built VOCAB / PROP_VOCAB, since the fixtures are real LIB files
    naming real axes."""
    return subtype in ("none", "closed")


def test_nspk_full_load_chain():
    assumptions = lio.load_assumptions(CLAIMS / "assumptions.json")
    props = lio.load_properties(CLAIMS / "properties.json")
    claims = lio.load_claims(CLAIMS / "claims.json", assumptions)
    results = lio.load_results(RESULTS / "results.json")
    cases = lio.load_cases_results(RESULTS / "cases_results.json", assumptions)
    assert props.properties and claims.claims and results.results and cases.cases
    # claims reference the scenario table by name, and every name closes
    table = {s.name for s in claims.scenarios}
    for c in claims.claims:
        assert set(c.scenarios) <= table
    # the claims name everything in the vocabulary, so nothing is unclaimed
    assert validate_claims(claims, assumptions, props, is_noop=_noop, vocab=VOCAB, prop_vocab=PROP_VOCAB) == []
    # a world is a complete assignment: fixed ∪ conditions ∪ noop defaults
    worlds, alias = expand_assignments(claims, assumptions, _noop)
    n = len(assumptions.entries())
    assert all(len(w) == n for _, w in worlds)
    assert set(alias.values()) == {name for name, _ in worlds}


# ── the document shapes, inline ─────────────────────────────────────────────

ASSUM = {
    "vocab_version": "2.2.0",
    "world": [], "fixed": [
        {"id": "ltk_reveal_K", "axis": "data",
         "target": {"of": "K", "phase": 1},
         "subtype": "leaked_after_session"},
    ],
    "variable": [
        {"id": "ltk_reveal_N", "axis": "data",
         "target": {"of": "NB"},
         "subtypes": ["none", "disclosed"]},
    ],
}

PROPS = {
    "vocab_version": "2.2.0",
    "properties": [
        {"id": "fs_a", "type": "Secrecy", "subtype": "forward_secrecy",
         "values": ["K"], "parties": {"holders": ["A"]}},
    ],
}


def _claims(scenarios, claims):
    return {"vocab_version": "2.2.0", "scenarios": scenarios, "claims": claims}


BASELINE = [{"name": "baseline", "conditions": []}]


def test_v8_top_level_keys_are_rejected():
    for old in ("assumptions", "replication", "axes"):
        with pytest.raises(LibParseError, match="v8 shape"):
            AssumptionsDoc.from_json({"world": [], "fixed": [], "variable": [], old: []})


def test_fixed_with_plural_subtypes_is_loud():
    with pytest.raises(LibParseError, match="variable"):
        lio.parse_assumptions({
            "vocab_version": "2.2.0", "variable": [],
            "world": [], "fixed": [{"id": "x", "axis": "data",
                       "target": {"of": "K"}, "subtypes": ["none"]}],
        })


def test_variable_needs_two_subtypes():
    for subs in ([], ["none"]):
        with pytest.raises(LibParseError, match="at least two"):
            lio.parse_assumptions({
                "vocab_version": "2.2.0", "world": [], "fixed": [],
                "variable": [{"id": "x", "axis": "data",
                              "target": {"of": "K"}, "subtypes": subs}],
            })


def test_id_and_axis_target_unique_across_sections():
    with pytest.raises(LibParseError, match="duplicate assumption id"):
        lio.parse_assumptions({
            "vocab_version": "2.2.0",
            "world": [], "fixed": [{"id": "x", "axis": "data",
                       "target": {"of": "K"}, "subtype": "none"}],
            "variable": [{"id": "x", "axis": "data", "target": {"of": "L"},
                          "subtypes": ["none", "disclosed"]}],
        })
    with pytest.raises(LibParseError, match="unique across both sections"):
        lio.parse_assumptions({
            "vocab_version": "2.2.0",
            "world": [], "fixed": [{"id": "x", "axis": "data",
                       "target": {"of": "K"}, "subtype": "none"}],
            "variable": [{"id": "y", "axis": "data", "target": {"of": "K"},
                          "subtypes": ["none", "disclosed"]}],
        })


def test_dangling_assumption_reference_is_loud():
    assumptions = lio.parse_assumptions(ASSUM)
    with pytest.raises(LibParseError, match="dangling"):
        lio.parse_claims(_claims(
            [{"name": "s1",
              "conditions": [{"id": "no_such_switch", "subtype": "secret"}]}],
            [{"property": "fs_a", "scenarios": ["s1"]}],
        ), assumptions)


def test_condition_on_fixed_fact_is_loud():
    assumptions = lio.parse_assumptions(ASSUM)
    with pytest.raises(LibParseError, match="fixed fact"):
        lio.parse_claims(_claims(
            [{"name": "s1",
              "conditions": [{"id": "ltk_reveal_K", "subtype": "leaked_after_session"}]}],
            [{"property": "fs_a", "scenarios": ["s1"]}],
        ), assumptions)


def test_cases_results_requires_complete_fixed_and_variable_assignment():
    assumptions = lio.parse_assumptions(ASSUM)
    matrix = CaseMatrix.from_json({
        "cases": [{
            "id": "fs_a",
            "by_scenario": [{
                "scenario": [
                    {"id": "ltk_reveal_N", "subtype": "none"},
                ],
                "verdict": "true",
            }],
        }],
    }, assumptions)

    with pytest.raises(LibResolveError, match="complete assignment.*ltk_reveal_K"):
        validate_cases_results(matrix, assumptions, VOCAB)


def test_condition_outside_domain_is_loud():
    assumptions = lio.parse_assumptions(ASSUM)
    with pytest.raises(LibParseError, match="declared domain"):
        lio.parse_claims(_claims(
            [{"name": "s1",
              "conditions": [{"id": "ltk_reveal_N", "subtype": "leaked_after_session"}]}],
            [{"property": "fs_a", "scenarios": ["s1"]}],
        ), assumptions)


def test_inline_scenario_array_is_the_v8_shape():
    assumptions = lio.parse_assumptions(ASSUM)
    with pytest.raises(LibParseError, match="v8 shape"):
        lio.parse_claims(_claims(
            BASELINE,
            [{"property": "fs_a",
              "scenarios": [[{"id": "ltk_reveal_N", "subtype": "none"}]]}],
        ), assumptions)


def test_scenario_table_gates():
    assumptions = lio.parse_assumptions(ASSUM)
    dup = BASELINE + [{"name": "baseline", "conditions": []}]
    with pytest.raises(LibParseError, match="duplicate scenario name"):
        lio.parse_claims(_claims(dup, [{"property": "fs_a", "scenarios": ["baseline"]}]),
                         assumptions)
    with pytest.raises(LibParseError, match="dangling scenario name"):
        lio.parse_claims(_claims(BASELINE, [{"property": "fs_a", "scenarios": ["nope"]}]),
                         assumptions)
    with pytest.raises(LibParseError, match="dead scenarios"):
        lio.parse_claims(_claims(
            BASELINE + [{"name": "unused", "conditions": [
                {"id": "ltk_reveal_N", "subtype": "disclosed"}]}],
            [{"property": "fs_a", "scenarios": ["baseline"]}],
        ), assumptions)
    with pytest.raises(LibParseError, match="at least one scenario name"):
        lio.parse_claims(_claims(BASELINE, [{"property": "fs_a", "scenarios": []}]),
                         assumptions)
    with pytest.raises(LibParseError, match="reserved"):
        lio.parse_claims(_claims(
            [{"name": "base", "conditions": []}],
            [{"property": "fs_a", "scenarios": ["base"]}],
        ), assumptions)


def test_condition_writing_flow_state_is_loud():
    assumptions = lio.parse_assumptions(ASSUM)
    props = lio.parse_properties(PROPS)
    claims = lio.parse_claims(_claims(
        [{"name": "s1",
          "conditions": [{"id": "ltk_reveal_N", "subtype": "none"}]}],
        [{"property": "fs_a", "scenarios": ["s1"]}],
    ), assumptions)
    with pytest.raises(LibValidationError, match="flow state"):
        validate_claims(claims, assumptions, props, is_noop=_noop, vocab=VOCAB, prop_vocab=PROP_VOCAB)


def test_world_fills_unmentioned_variable_with_noop_default():
    assumptions = lio.parse_assumptions(ASSUM)
    claims = lio.parse_claims(_claims(
        BASELINE, [{"property": "fs_a", "scenarios": ["baseline"]}]), assumptions)
    worlds, _alias = expand_assignments(claims, assumptions, _noop)
    [(name, world)] = worlds
    coords = {p.ref_id: p.subtype for p in world.points}
    assert name == "baseline"
    assert coords == {"ltk_reveal_K": "leaked_after_session",
                      "ltk_reveal_N": "none"}


def test_variable_without_noop_must_be_assigned():
    assumptions = lio.parse_assumptions({
        "vocab_version": "2.2.0", "world": [], "fixed": [],
        "variable": [{"id": "ltk_reveal_N", "axis": "data",
                      "target": {"of": "NB"},
                      "subtypes": ["disclosed", "leaked_after_session"]}],
    })
    claims = lio.parse_claims(_claims(
        BASELINE, [{"property": "fs_a", "scenarios": ["baseline"]}]), assumptions)
    with pytest.raises(LibResolveError, match="no flow-state value"):
        world_of(claims.scenarios[0], assumptions, _noop)


def test_expand_assignments_dedups_by_condition_set():
    assumptions = lio.parse_assumptions(ASSUM)
    claims = lio.parse_claims(_claims(
        [{"name": "leak_n",
          "conditions": [{"id": "ltk_reveal_N", "subtype": "disclosed"}]},
         {"name": "leak_n_again",
          "conditions": [{"id": "ltk_reveal_N", "subtype": "disclosed"}]}],
        [{"property": "fs_a", "scenarios": ["leak_n", "leak_n_again"]}],
    ), assumptions)
    worlds, alias = expand_assignments(claims, assumptions, _noop)
    assert [n for n, _ in worlds] == ["leak_n"]     # first name is canonical
    assert alias == {"leak_n": "leak_n", "leak_n_again": "leak_n"}


def test_requires_assumption_satisfied_by_fixed_entry():
    """forward_secrecy demands a windowed data leak in the world, and a fixed
    entry supplies it exactly like a condition would."""
    assumptions = lio.parse_assumptions(ASSUM)
    props = lio.parse_properties(PROPS)
    claims = lio.parse_claims(_claims(
        BASELINE, [{"property": "fs_a", "scenarios": ["baseline"]}]), assumptions)
    assert validate_claims(claims, assumptions, props, is_noop=_noop, vocab=VOCAB, prop_vocab=PROP_VOCAB) == []

    bare = lio.parse_assumptions({
        "vocab_version": "2.2.0", "world": [], "fixed": [],
        "variable": [{"id": "ltk_reveal_N", "axis": "data",
                      "target": {"of": "NB"},
                      "subtypes": ["none", "disclosed"]}],
    })
    claims2 = lio.parse_claims(_claims(
        BASELINE, [{"property": "fs_a", "scenarios": ["baseline"]}]), bare)
    with pytest.raises(LibValidationError, match="must be paired"):
        validate_claims(claims2, bare, props, is_noop=_noop, vocab=VOCAB, prop_vocab=PROP_VOCAB)


def test_dangling_property_reference_is_loud():
    assumptions = lio.parse_assumptions(ASSUM)
    props = lio.parse_properties(PROPS)
    claims = lio.parse_claims(_claims(
        BASELINE, [{"property": "no_such_goal", "scenarios": ["baseline"]}]),
        assumptions)
    with pytest.raises(LibValidationError, match="dangling reference"):
        validate_claims(claims, assumptions, props, is_noop=_noop, vocab=VOCAB, prop_vocab=PROP_VOCAB)


def test_v7_requires_in_properties_is_loud():
    data = {
        "vocab_version": "2.2.0",
        "properties": [{
            "id": "x", "type": "Secrecy", "values": ["Na"],
            "parties": {"holders": ["A"]},
            "requires": [[{"id": "y", "subtype": "secret"}]],
        }],
    }
    with pytest.raises(LibParseError, match="old shape"):
        lio.parse_properties(data)


def test_unclaimed_vocabulary_is_allowed_and_reported():
    """A vocabulary larger than the question is legal, so validate_claims
    returns the unnamed goals for the caller to record instead of raising."""
    assumptions = lio.load_assumptions(CLAIMS / "assumptions.json")
    props = lio.load_properties(CLAIMS / "properties.json")
    one = lio.parse_claims({
        "vocab_version": "2.2.0",
        "scenarios": [{"name": "baseline", "conditions": []}],
        "claims": [{"property": "secrecy_i_a", "scenarios": ["baseline"]}],
    }, assumptions)
    unclaimed = validate_claims(one, assumptions, props, is_noop=_noop, vocab=VOCAB, prop_vocab=PROP_VOCAB)
    assert set(unclaimed) == {"secrecy_i_b", "auth_a_to_b", "auth_b_to_a"}
