"""Inject batching and submission shape.

A batch is one session and one .pv. Which subtypes may share it is decided by
perturbs_model, not by type alone, and the submission is one set of fragments
for the whole batch."""

from orrery.nodes.inject.node import parse_batch
from orrery.pipeline.scenarios import family_batches
from types import SimpleNamespace

C_SEC = ("Secrecy", "basic", ["g1"])
C_FS = ("Secrecy", "forward_secrecy", ["g2"])
C_NI = ("Authentication", "non_injective_agreement", ["g3"])
C_IN = ("Authentication", "injective_agreement", ["g4"])


def test_batches_group_by_what_may_share_a_file():
    """Subtypes that only add queries share a file: the two Authentication
    strengths emit the same events and differ in the query line, which is what
    makes their verdicts comparable. A subtype that changes the model does not
    share: forward_secrecy's phase-1 leak would answer plain secrecy's question
    for it."""
    batches = family_batches([C_IN, C_SEC, C_NI, C_FS], cap=4)
    assert [(fam, chunk, [c[1] for c in cells])
            for fam, chunk, cells in batches] == [
        ("Authentication", None,
         ["injective_agreement", "non_injective_agreement"]),
        ("Secrecy", None, ["basic"]),
        ("Secrecy.forward_secrecy", None, ["forward_secrecy"]),
    ]


def test_a_perturbing_subtype_is_never_joined():
    """It splits off even from a sibling of its own type, and even under a cap
    that would fit both."""
    batches = family_batches([C_SEC, C_FS], cap=8)
    assert len(batches) == 2
    assert all(len(cells) == 1 for _, _, cells in batches)


def test_cap_splits_within_family_into_numbered_chunks():
    batches = family_batches([C_IN, C_NI], cap=1)
    assert [(fam, chunk) for fam, chunk, _ in batches] == [
        ("Authentication", 1), ("Authentication", 2)]


def test_cap_one_degrades_to_per_cell_calls():
    batches = family_batches([C_SEC, C_FS, C_NI], cap=1)
    assert all(len(cells) == 1 for _, _, cells in batches)
    assert len(batches) == 3


def test_unlinkability_puts_each_goal_in_its_own_file():
    goals = [
        SimpleNamespace(id="unlink_a", type="Privacy", subtype="unlinkability"),
        SimpleNamespace(id="unlink_b", type="Privacy", subtype="unlinkability"),
    ]
    batches = family_batches(
        [("Privacy", "unlinkability", goals)], cap=8)
    assert [(family, [g.id for _, _, gs in cells for g in gs])
            for family, _, cells in batches] == [
        ("Privacy.unlinkability.unlink_a", ["unlink_a"]),
        ("Privacy.unlinkability.unlink_b", ["unlink_b"]),
    ]


GOALS = ["g1", "g2"]


def _sub(decls=("d.",), edits=()):
    return {"declarations": list(decls), "edits": list(edits)}


def test_a_full_submission_passes_shape():
    active, problems = parse_batch(_sub(), GOALS)
    assert problems == []
    assert active == GOALS


def test_nothing_submitted_and_nothing_failed_is_a_finding():
    _, problems = parse_batch(_sub(decls=(), edits=()), GOALS)
    assert any("both empty" in p for p in problems)


def test_submission_has_no_model_declared_failure_exit():
    from orrery.nodes.inject.node import _SCHEMA

    assert set(_SCHEMA["properties"]) == {"declarations", "edits"}
    active, problems = parse_batch(_sub(), GOALS)
    assert problems == [] and active == GOALS


def test_the_submission_is_one_set_of_fragments_not_one_per_cell():
    """A batch is one file, so the two Authentication strengths write their
    common events once; a per-cell submission would insert them twice and the
    file would not compile."""
    from orrery.nodes.inject.node import _SCHEMA

    assert set(_SCHEMA["properties"]) == {"declarations", "edits"}
    assert _SCHEMA["required"] == ["declarations", "edits"]
