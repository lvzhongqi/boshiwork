"""aggregate's three-valued conjunction, driven by fabricated per-scenario
verdicts over the fixture's NSPK claims.

All true gives true, any false gives false, an unknown with no false gives
unknown. "vacuous" ranks between false and the no-answer kinds, so a property
never actually tested in one scenario does not read "true".
"""

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from orrery.modules.libschema.io import load_assumptions, load_claims
from orrery.modules.libschema.resolve import expand_assignments
from orrery.nodes.aggregate.node import AggregateNode
from orrery.nodes.apply.realizers import subtype_is_noop
from orrery.nodes.base import RunEnv
from orrery.services.store.atomic import write_json
from orrery.services.store.layout import RunLayout
from tests.fixtures import CLAIMS, TOY_PROTOCOL

# the scenario names the fixture's claims table declares
HONEST = "baseline"
ATTACK = "peer_key_attacker_supplied"
LEAKED = "shared_key_leaked"

# fabricated verdicts per cell: goal → {scenario label → verdict}
FABRICATED = {
    "secrecy_i_a": {HONEST: "true", ATTACK: "true", LEAKED: "true"},      # all true → true
    "secrecy_i_b": {HONEST: "true", ATTACK: "false", LEAKED: "true"},     # any false → false
    "auth_a_to_b": {HONEST: "true", ATTACK: "unknown", LEAKED: "true"},   # an unknown with no false → unknown
    "auth_b_to_a": {HONEST: "unknown", ATTACK: "false", LEAKED: "true"},  # false wins over unknown
}

# the same table with one scenario never tested. Only auth_b_to_a is claimed in
# LEAKED, so the other three are decided by the first two scenarios alone.
VACUOUS = {
    "secrecy_i_a": {HONEST: "true", ATTACK: "vacuous", LEAKED: "true"},     # a true nobody asked → vacuous
    "secrecy_i_b": {HONEST: "false", ATTACK: "vacuous", LEAKED: "true"},    # a real counterexample still wins
    "auth_a_to_b": {HONEST: "vacuous", ATTACK: "timeout", LEAKED: "true"},  # vacuous is reported ahead of timeout
    "auth_b_to_a": {HONEST: "true", ATTACK: "true", LEAKED: "true"},        # untouched
}


def _lay(tmp_path):
    """A run whose claims step has left the corpus's three files, which is what
    aggregate reads."""
    lay = RunLayout(tmp_path / "wr", "TAP", "r1")
    lay.run_dir.mkdir(parents=True, exist_ok=True)
    # Opened in run order: aggregate reads the scenarios' verdicts, so opening
    # it before they exist would make the index call it stale.
    for step in ("extract_claims", "scenarios"):
        lay.open_node(step)
    d = lay.node_dir("extract_claims")
    for f in ("assumptions.json", "properties.json", "claims.json"):
        shutil.copy(CLAIMS / f, d / f)
    return lay


def test_conjunction_direction(tmp_path):
    lay = _lay(tmp_path)
    d = lay.node_dir("extract_claims")
    a = load_assumptions(d / "assumptions.json")
    claims = load_claims(d / "claims.json", a)
    worlds, _alias = expand_assignments(claims, a, subtype_is_noop)
    for name, _world in worlds:
        lay.open_scenario(name)
        write_json(lay.scenario_verdict(name), {
            "verdicts": {g: vs[name] for g, vs in FABRICATED.items()},
            "solver_notes": {"t": "fabricated"},
        })
    lay.open_node("aggregate")          # …and only then the step that reads them

    env = RunEnv(protocol_dir=TOY_PROTOCOL, layout=lay, config={})
    asyncio.run(AggregateNode().run(env))

    results = {r["id"]: r for r in json.loads(
        lay.results_json.read_text())["results"]}
    assert results["secrecy_i_a"]["verdict"] == "true"
    assert results["secrecy_i_b"]["verdict"] == "false"
    assert ATTACK in results["secrecy_i_b"]["description"]
    assert results["auth_a_to_b"]["verdict"] == "unknown"
    assert "solver_notes" in results["auth_a_to_b"]["description"]
    assert results["auth_b_to_a"]["verdict"] == "false"     # not unknown

    # cases_results serialises each scenario back to its complete assignment as
    # {id, subtype}: every declared assumption, not only the condition's own
    cases = {c["id"]: c for c in json.loads(
        lay.cases_results_json.read_text())["cases"]}
    grid = [({c["id"]: c["subtype"] for c in b["scenario"]}, b["verdict"])
            for b in cases["auth_b_to_a"]["by_scenario"]]
    assert grid == [
        ({"ltk_reveal_kab": "none", "admission_peer_auth": "closed"}, "unknown"),
        ({"ltk_reveal_kab": "none", "admission_peer_auth": "open"}, "false"),
        ({"ltk_reveal_kab": "disclosed", "admission_peer_auth": "closed"}, "true"),
    ]


def test_a_scenario_that_never_tested_the_goal_is_not_a_proof(tmp_path):
    lay = _lay(tmp_path)
    d = lay.node_dir("extract_claims")
    a = load_assumptions(d / "assumptions.json")
    claims = load_claims(d / "claims.json", a)
    worlds, _alias = expand_assignments(claims, a, subtype_is_noop)
    for name, _world in worlds:
        lay.open_scenario(name)
        write_json(lay.scenario_verdict(name), {
            "verdicts": {g: vs[name] for g, vs in VACUOUS.items()},
            "solver_notes": {"t": "fabricated"},
        })
    lay.open_node("aggregate")

    env = RunEnv(protocol_dir=TOY_PROTOCOL, layout=lay, config={})
    asyncio.run(AggregateNode().run(env))
    results = {r["id"]: r for r in json.loads(
        lay.results_json.read_text())["results"]}

    assert results["secrecy_i_a"]["verdict"] == "vacuous"   # not true
    assert ATTACK in results["secrecy_i_a"]["description"]
    assert "never tested" in results["secrecy_i_a"]["description"]
    assert results["secrecy_i_b"]["verdict"] == "false"     # a counterexample outranks it
    assert results["auth_a_to_b"]["verdict"] == "vacuous"   # ahead of timeout
    assert results["auth_b_to_a"]["verdict"] == "true"      # untouched


def test_missing_scenario_verdict_is_loud(tmp_path):
    lay = _lay(tmp_path)
    env = RunEnv(protocol_dir=TOY_PROTOCOL, layout=lay, config={})
    with pytest.raises(Exception, match="no verdict"):
        asyncio.run(AggregateNode().run(env))
