"""Which false cells are reproduced on their own, which wait, and which are
left out — on the matrix of a real run (ISO/IEC 11770-3 key agreement
mechanism 1: seven goals, a baseline and two leaked-key scenarios)."""

import pytest

from orrery.modules.attacks.targets import (
    AUTO, GROUND_TRUTH_DIFFERS, NOT_COMPARED, OVER_LIMIT, PENDING, SKIPPED,
    Cell, compared_cells, plan, weakened,
)

GOALS = ["secrecy_secreta_m1", "secrecy_secretb_m1", "secrecy_secdh",
         "use_a_m1_implies_use_b_m1", "inj_use_a_m1_implies_use_b_m1",
         "use_b_m1_implies_use_a_m1", "inj_use_b_m1_implies_use_a_m1"]
SCENARIOS = [("baseline", (("ltk_reveal_hA", "none"), ("ltk_reveal_hB", "none"))),
             ("leak_hA", (("ltk_reveal_hA", "disclosed"), ("ltk_reveal_hB", "none"))),
             ("leak_hB", (("ltk_reveal_hA", "none"), ("ltk_reveal_hB", "disclosed")))]
VARIABLES = {"ltk_reveal_hA": ("data", ("none", "disclosed")),
             "ltk_reveal_hB": ("data", ("none", "disclosed"))}


def _compare(axis, a, b):
    order = {"disclosed": 0, "none": 1}
    return (order[a] > order[b]) - (order[a] < order[b])


def _cells():
    out = []
    for g in GOALS:
        for col, (label, assignment) in enumerate(SCENARIOS):
            secrecy = g.startswith("secrecy")
            verdict = "true" if secrecy and label == "baseline" else "false"
            out.append(Cell(g, label, col, assignment, verdict))
    return out


def _weak(cell):
    return weakened(cell.assignment, VARIABLES, _compare)


def test_ten_of_eighteen_go_first_covering_every_goal():
    targets = plan(_cells(), compared=None, limit=10, weakened_of=_weak)
    assert len(targets) == 18
    auto = [(t.round, t.goal, t.label) for t in targets if t.decision == AUTO]
    assert sorted(auto) == sorted(
        [(1, g, "leak_hA") for g in GOALS[:3]]
        + [(1, g, "baseline") for g in GOALS[3:]]
        + [(2, g, "leak_hB") for g in GOALS[:3]])
    waiting = [t for t in targets if t.decision == PENDING]
    assert len(waiting) == 8
    assert {t.reason for t in waiting} == {OVER_LIMIT}
    # the baseline cells weaken nothing; a leak weakens one assumption
    by_cell = {(t.goal, t.label): t for t in targets}
    assert by_cell[("use_a_m1_implies_use_b_m1", "baseline")].weakened == []
    assert by_cell[("secrecy_secdh", "leak_hB")].weakened == ["ltk_reveal_hB = disclosed"]


def test_targets_keep_the_matrix_order():
    targets = plan(_cells(), compared=None, limit=10, weakened_of=_weak)
    expected = [(c.goal, c.label) for c in _cells() if c.verdict == "false"]
    assert [(t.goal, t.label) for t in targets] == expected


def test_a_small_run_does_everything():
    cells = [c for c in _cells() if c.goal == GOALS[0]]
    targets = plan(cells, compared=None, limit=10, weakened_of=_weak)
    assert [t.decision for t in targets] == [AUTO, AUTO]


def test_ground_truth_lets_through_only_what_it_agrees_with():
    cells = [c for c in _cells() if c.goal in (GOALS[0], GOALS[3])]
    cross = {"cells": [
        {"id": GOALS[0], "scenario": [{"id": i, "subtype": s} for i, s in SCENARIOS[1][1]],
         "ours": "false", "expected": "false", "match": True},
        {"id": GOALS[0], "scenario": [{"id": i, "subtype": s} for i, s in SCENARIOS[2][1]],
         "ours": "false", "expected": "true", "match": False},
        # GOALS[3] at baseline is compared; its two leak cells are not
        {"id": GOALS[3], "scenario": [{"id": i, "subtype": s} for i, s in SCENARIOS[0][1]],
         "ours": "false", "expected": "false", "match": True},
    ]}
    targets = plan(cells, compared=compared_cells(cross), limit=10, weakened_of=_weak)
    got = {(t.goal, t.label): (t.decision, t.reason, t.expected) for t in targets}
    assert got == {
        (GOALS[0], "leak_hA"): (AUTO, "", "false"),
        (GOALS[0], "leak_hB"): (SKIPPED, GROUND_TRUTH_DIFFERS, "true"),
        (GOALS[3], "baseline"): (AUTO, "", "false"),
        (GOALS[3], "leak_hA"): (SKIPPED, NOT_COMPARED, ""),
        (GOALS[3], "leak_hB"): (SKIPPED, NOT_COMPARED, ""),
    }


def test_a_channel_left_at_its_weakest_value_counts_as_weakened():
    variables = {"link_user": ("channel", ("secure", "public"))}

    def compare(axis, a, b):
        order = {"public": 0, "secure": 1}
        return (order[a] > order[b]) - (order[a] < order[b])

    assert weakened((("link_user", "public"),), variables, compare) == ["link_user = public"]
    assert weakened((("link_user", "secure"),), variables, compare) == []


def test_limit_zero_leaves_everything_waiting():
    targets = plan(_cells(), compared=None, limit=0, weakened_of=_weak)
    assert {t.decision for t in targets} == {PENDING}
    with pytest.raises(ValueError):
        plan(_cells(), compared=None, limit=-1, weakened_of=_weak)
