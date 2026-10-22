"""Unlinkability goals: injector isolation flags, biprocess contract, parsing."""

from types import SimpleNamespace

from orrery.infra.proverif.outcome import parse_verdicts
from orrery.nodes.inject.injectors import injector_for
from orrery.nodes.inject.node import unlinkability_contract_problems


GOAL = SimpleNamespace(
    id="unlink_a", type="Privacy", subtype="unlinkability")


def test_unlinkability_is_implemented_and_isolated():
    injector = injector_for("Privacy", "unlinkability")
    assert injector.perturbs_model
    assert injector.one_goal_per_file


def test_unlinkability_contract_accepts_one_marked_biprocess():
    pv = """free A: host [private].
free A2: host [private].
(* @orrery-unlinkability unlink_a *)
process Session(A) | Session(choice[A,A2])
"""
    assert unlinkability_contract_problems(pv, [GOAL]) == []


def test_unlinkability_contract_rejects_a_reachability_query():
    pv = """free A: host [private].
free A2: host [private].
query attacker(A).
(* @orrery-unlinkability unlink_a *)
process Session(A) | Session(choice[A,A2])
"""
    problems = unlinkability_contract_problems(pv, [GOAL])
    assert any("do not add a reachability query" in p for p in problems)


def test_proverif_observational_equivalence_output_is_parsed():
    verdicts = parse_verdicts("RESULT Observational equivalence is true.\n")
    assert [(v.query, v.verdict) for v in verdicts] == [
        ("Observational equivalence", "true")]
