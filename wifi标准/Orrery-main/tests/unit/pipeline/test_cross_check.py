"""cross_check compared over the intersection of run and ground truth: a full
match, a mismatch, scenarios the corpus has but the run does not, and a run
that names everything in its own words yet asks about the same cells."""

import asyncio
import json

import pytest

from orrery.nodes.base import CheckFailed, RunEnv
from orrery.nodes.cross_check.node import CrossCheckNode, compare
from orrery.services.store.atomic import write_json
from orrery.services.store.layout import RunLayout

S1 = [{"id": "k", "subtype": "none"}]
S2 = [{"id": "k", "subtype": "disclosed"}]
V = {"vocab_version": "2.2.0"}


def _vocab(key="k", goal="g1", extra=()):
    """One variable data assumption about K, one secrecy goal about N, and
    ``extra`` fixed data assumptions, each about the object it is named for."""
    assumptions = {**V, "world": [], "variable": [
        {"id": key, "axis": "data", "target": {"of": "K"},
         "subtypes": ["none", "disclosed"]}],
        "fixed": [{"id": x, "axis": "data", "target": {"of": x.upper()},
                   "subtype": "disclosed"} for x in extra]}
    properties = {**V, "properties": [
        {"id": goal, "type": "Secrecy", "subtype": "basic", "values": ["N"],
         "parties": {"holders": ["A", "B"]}}]}
    return assumptions, properties


def _docs(v1, v2=None, goal="g1", s1=S1, s2=S2):
    cases = [{"id": goal, "by_scenario":
              [{"scenario": s1, "verdict": v1}]
              + ([{"scenario": s2, "verdict": v2}] if v2 else [])}]
    results = [{"id": goal, "verdict": v1}]
    return {"cases": cases}, {"results": results}


def _compare(ours, theirs, ours_vocab=None, gt_vocab=None):
    (oc, orr), (lc, lr) = ours, theirs
    return compare(orr, oc, lr, lc, ours_vocab=ours_vocab or _vocab(),
                   gt_vocab=gt_vocab or _vocab())


def test_compare_full_match_and_intersection():
    rep = _compare(_docs("true"), _docs("true", v2="false"))  # corpus has one more
    assert rep["cases_compared"] == 1 and rep["cases_matched"] == 1
    assert rep["acc"] == 1.0 and not rep["cases_mismatches"]


def test_compare_mismatch_reported():
    rep = _compare(_docs("true"), _docs("false"))
    assert rep["cases_mismatches"][0]["expected"] == "false"
    assert rep["results_mismatches"][0]["id"] == "g1"
    # every compared cell is kept, keyed by the run's own assignment the way
    # cases_results writes it, so work.md can show the scenario beside its cell
    assert rep["cells"] == [{"id": "g1", "scenario": S1, "corpus_id": "g1",
                             "corpus_scenario": S1, "ours": "true",
                             "expected": "false", "match": False}]


def test_cells_pair_by_what_they_are_about_not_by_name():
    """The run calls the goal and the assumption something else, and also
    speaks about an object the corpus leaves unsaid: the cells still pair,
    goal by type and target, scenario by its answer on the shared objects."""
    mine = [{"id": "data_k_leak", "subtype": "disclosed"},
            {"id": "data_id_a", "subtype": "disclosed"}]
    ours = _docs("true", goal="secrecy_n",
                 s1=[{"id": "data_k_leak", "subtype": "none"},
                     {"id": "data_id_a", "subtype": "disclosed"}], s2=mine,
                 v2="false")
    rep = _compare(ours, _docs("true", v2="false"),
                   ours_vocab=_vocab(key="data_k_leak", goal="secrecy_n",
                                     extra=("data_id_a",)))
    assert rep["cases_compared"] == 2 and rep["acc"] == 1.0
    leaked = next(c for c in rep["cells"] if c["expected"] == "false")
    assert leaked["id"] == "secrecy_n" and leaked["corpus_id"] == "g1"
    assert leaked["scenario"] == sorted(mine, key=lambda p: p["id"])
    assert leaked["corpus_scenario"] == S2
    assert rep["results"] == [{"id": "secrecy_n", "corpus_id": "g1",
                               "ours": "true", "expected": "true", "match": True}]


def test_a_scenario_that_matches_two_pairs_with_neither():
    """Two run scenarios that differ only on an object the corpus never
    mentions both look like the corpus's one: there is no saying which is it."""
    ours = _docs("true", v2="true",
                 s1=[{"id": "k", "subtype": "none"}, {"id": "j", "subtype": "none"}],
                 s2=[{"id": "k", "subtype": "none"}, {"id": "j", "subtype": "disclosed"}])
    assumptions, properties = _vocab()
    assumptions["variable"].append(
        {"id": "j", "axis": "data", "target": {"of": "J"},
         "subtypes": ["none", "disclosed"]})
    rep = _compare(ours, _docs("true"), ours_vocab=(assumptions, properties))
    assert rep["cases_produced"] == 2 and rep["cases_compared"] == 0


def test_goals_of_another_kind_do_not_pair():
    theirs_vocab = _vocab()
    theirs_vocab[1]["properties"][0]["values"] = ["M"]
    rep = _compare(_docs("true"), _docs("true"), gt_vocab=theirs_vocab)
    assert rep["cases_compared"] == 0 and rep["results_total"] == 0


def _write_run(tmp_path, ours, *, vocab=None):
    """A run with its cells and its own declarations on disk."""
    lay = RunLayout(tmp_path / "wr", "P", "r1")
    lay.run_dir.mkdir(parents=True)
    claims = lay.open_node("extract_claims")
    assumptions, properties = vocab or _vocab()
    write_json(claims / "assumptions.json", assumptions)
    write_json(claims / "properties.json", properties)
    lay.open_node("aggregate")
    lay.open_node("cross_check")
    oc, orr = ours
    write_json(lay.cases_results_json, {**V, **oc})
    write_json(lay.results_json, {**V, **orr})
    return lay


def _write_truth(tmp_path, theirs, *, vocab=None):
    gt = tmp_path / "gt"
    lc, lr = theirs
    write_json(gt / "results" / "cases_results.json", {**V, **lc})
    write_json(gt / "results" / "results.json", {**V, **lr})
    assumptions, properties = vocab or _vocab()
    write_json(gt / "claims" / "assumptions.json", assumptions)
    write_json(gt / "claims" / "properties.json", properties)
    return gt


def test_node_paths(tmp_path):
    """The node end to end: disabled, matching, results-only disagreement, and
    a differing cell, which is the only one that fails the run."""
    lay = _write_run(tmp_path, _docs("true"))
    env = RunEnv(protocol_dir=tmp_path, layout=lay, config={})
    # not enabled: nothing to do, and is_done reads as finished
    node = CrossCheckNode()
    assert node.is_done(env)
    asyncio.run(node.run(env))

    # enabled and fully matching: cross_check.json is written and nothing raises
    gt = _write_truth(tmp_path, _docs("true"))
    env.ground_truth = gt
    asyncio.run(node.run(env))
    rep = json.loads(lay.cross_check_json.read_text())
    assert rep["acc"] == 1.0

    # A results-level disagreement on its own does not fail the check: a
    # results row is the conjunction of its own cells, so a ground truth whose
    # results contradict its cells is inconsistent with itself, and the cells
    # are the observations.
    write_json(gt / "results" / "results.json",
               {**V, "results": [{"id": "g1", "verdict": "false"}]})
    lay.cross_check_json.unlink()
    asyncio.run(node.run(env))
    rep = json.loads(lay.cross_check_json.read_text())
    assert rep["results_mismatches"] and not rep["cases_mismatches"]

    # a differing cell raises CheckFailed rather than NodeError: the node ran
    # fine, the comparison is what says no
    gt_cells, _ = _docs("false")
    write_json(gt / "results" / "cases_results.json", {**V, **gt_cells})
    lay.cross_check_json.unlink()
    with pytest.raises(CheckFailed, match="cells differ"):
        asyncio.run(node.run(env))
    assert lay.cross_check_json.exists()   # the report is still written


def test_an_empty_intersection_is_not_agreement(tmp_path):
    """A run whose cells share no scenario with the corpus compared nothing, so
    it has no accuracy and must not report one.

    Measured once in 254 recorded runs: acc was null, no cell disagreed, the
    node passed and the run said ok — while a recomputation against today's
    corpus scores that same run 18 of 18. Nothing in the artifact said the
    comparison had not happened.
    """
    lay = _write_run(tmp_path, _docs("true"))
    # The assumptions vocabulary was supplied, so the cells are written in the
    # corpus's own vocabulary and nothing lining up is an encoding mismatch
    # (see the test after this one).
    env = RunEnv(protocol_dir=tmp_path, layout=lay, config={},
                 assumptions_input="supplied")
    assert "extract_assumptions" in env.pinned()
    # the same goal and the same verdict, under a scenario that answers the
    # one shared object differently
    env.ground_truth = _write_truth(tmp_path, _docs("true", s1=S2))

    with pytest.raises(CheckFailed, match="share no scenario"):
        asyncio.run(CrossCheckNode().run(env))
    rep = json.loads(lay.cross_check_json.read_text())
    # the report is written and says which half of the denominator vanished
    assert rep["cases_produced"] == 1 and rep["cases_compared"] == 0
    assert rep["acc"] is None
    # and the results rows still matched, which is exactly why it stayed silent
    assert rep["results_total"] == 1 and not rep["results_mismatches"]


def test_an_empty_intersection_under_extracted_assumptions_is_a_note_not_a_failure(tmp_path):
    """The same run as above, but the assumptions were extracted rather than
    supplied: the run may simply have asked about other worlds than the
    corpus. That is no accuracy to report, not a check that failed, and the
    run finishes with the note on its ledger."""
    lay = _write_run(tmp_path, _docs("true"))
    env = RunEnv(protocol_dir=tmp_path, layout=lay, config={})
    assert "extract_assumptions" not in env.pinned()     # nothing was supplied
    env.ground_truth = _write_truth(tmp_path, _docs("true", s1=S2))

    asyncio.run(CrossCheckNode().run(env))              # no CheckFailed
    rep = json.loads(lay.cross_check_json.read_text())
    assert rep["cases_produced"] == 1 and rep["cases_compared"] == 0
    assert rep["acc"] is None


def _renamed_run(tmp_path, alignment):
    """A run that calls the corpus's K ``k_1``, with ``alignment`` (or none)
    filed as its assumptions symbol alignment. Every other symbol is as the
    corpus writes it and its properties alignment maps nothing."""
    assumptions, properties = _vocab()
    assumptions["variable"][0]["target"] = {"of": "k_1"}
    lay = _write_run(tmp_path, _docs("true", v2="false"),
                     vocab=(assumptions, properties))
    eval_dir = lay.run_dir / "eval"
    if alignment is not None:
        write_json(eval_dir / "03_assumptions_alignment.json", alignment)
    write_json(eval_dir / "04_properties_alignment.json",
               {"status": "ok", "mappings": []})
    env = RunEnv(protocol_dir=tmp_path, layout=lay, config={})
    env.ground_truth = _write_truth(tmp_path, _docs("true", v2="false"))
    return lay, env


class _Bus:
    def __init__(self):
        self.events = []

    def emit(self, ev):
        self.events.append(ev)


def test_symbols_are_renamed_through_the_alignment_before_pairing(tmp_path):
    lay, env = _renamed_run(tmp_path, {"status": "ok", "mappings": [
        {"candidate": "k_1", "gold": "K", "evidence": []}]})
    asyncio.run(CrossCheckNode().run(env))
    rep = json.loads(lay.cross_check_json.read_text())
    assert rep["cases_compared"] == 2 and rep["acc"] == 1.0
    assert rep["symbol_alignment"]["assumptions"] == {
        "source": "eval/03_assumptions_alignment.json", "mapping": {"k_1": "K"}}
    assert rep["warnings"] == []


def test_a_failed_alignment_compares_as_written_and_warns(tmp_path):
    lay, env = _renamed_run(tmp_path, {"status": "failed", "error": "boom",
                                       "mappings": []})
    env.bus = _Bus()
    asyncio.run(CrossCheckNode().run(env))      # a note, not a failure
    rep = json.loads(lay.cross_check_json.read_text())
    # k_1 and K are two objects, so both run scenarios look like both of the
    # corpus's and none pairs
    assert rep["cases_compared"] == 0
    assert "boom" in rep["symbol_alignment"]["assumptions"]["unavailable"]
    assert rep["warnings"] and rep["warnings"][0].startswith("warning:")
    said = [ev.text for ev in env.bus.events if type(ev).__name__ == "NodeProgress"]
    assert rep["warnings"][0] in said


def test_a_missing_alignment_warns_too(tmp_path):
    lay, env = _renamed_run(tmp_path, None)
    asyncio.run(CrossCheckNode().run(env))
    rep = json.loads(lay.cross_check_json.read_text())
    assert "no assumptions symbol alignment" in rep["warnings"][0]


def test_a_supplied_vocabulary_is_not_renamed(tmp_path):
    lay = _write_run(tmp_path, _docs("true"))
    env = RunEnv(protocol_dir=tmp_path, layout=lay, config={},
                 assumptions_input="supplied", properties_input="supplied")
    env.ground_truth = _write_truth(tmp_path, _docs("true"))
    asyncio.run(CrossCheckNode().run(env))
    rep = json.loads(lay.cross_check_json.read_text())
    assert rep["symbol_alignment"] == {"assumptions": {"supplied": True},
                                       "properties": {"supplied": True}}
    assert rep["warnings"] == [] and rep["acc"] == 1.0
