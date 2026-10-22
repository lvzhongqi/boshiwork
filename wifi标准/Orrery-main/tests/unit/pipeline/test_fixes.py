"""fixes: path addressing, pricing, the fact filed at the step's own directory,
and the live-session delivery.

A fix destroys nothing — it files a message and names a re-entry point. Only a
model-driven step can be targeted; a pure-code step or a path matching nothing
is refused before anything is written.
"""

import pytest

from orrery.agent.tools.expert_tools import FixPlan
from orrery.pipeline.control import fixes
from orrery.services import facts
from orrery.services.store.atomic import write_text
from orrery.services.store.layout import RunLayout
from orrery.services.transcript.reader import TranscriptReader
from orrery.services.transcript.writer import TranscriptWriter

CHAIN = ("load_document", "tag_sections", "extract_principals", "extract_flow",
         "claims", "build_world", "build_root", "scenarios", "aggregate")


def _layout(tmp_path, *, upto="aggregate"):
    """A run that got as far as ``upto``, one directory per step that ran."""
    lay = RunLayout(tmp_path / "wr", "NSPK", "r1")
    lay.run_dir.mkdir(parents=True)
    for name in CHAIN[:CHAIN.index(upto) + 1]:
        lay.open_node(name)
    TranscriptWriter(lay.node_transcript("extract_principals")).meta(node="e")
    write_text(lay.node_dir("extract_principals") / "principals.json", "[]")
    write_text(lay.node_dir("extract_flow") / "flow.pv", "process 0")
    if lay.find_node_dir("aggregate") is not None:
        write_text(lay.results_json, "{}")
    return lay


def _scenario(lay, label):
    """A finished scenario: three applied points, the scenario model, one
    injected family, the verdict."""
    home = lay.open_scenario(label)
    for rid in ("role_a", "leaked", "guessed"):
        d = lay.open_apply_point(home, rid)
        write_text(d / "applied.pv", f"pv after {rid}")
        write_text(d / "transcript.jsonl", "{}")
    lay.open_inject_family(label, "Secrecy")
    write_text(lay.scenario_pv(label), "process 0")
    write_text(lay.inject_model(label, "Secrecy"), "process 1")
    write_text(lay.scenario_verdict(label), "{}")
    return home


def test_estimate_names_what_stops_being_current(tmp_path):
    lay = _layout(tmp_path)
    cost = fixes.estimate(lay, FixPlan("extract_principals", "resume", "msg"))
    assert cost.heavy and cost.from_node == "extract_principals"
    # nothing is destroyed; superseded names the step directories the run
    # stops resolving to
    assert lay.rel(lay.node_dir("extract_principals")) in cost.superseded
    assert lay.rel(lay.node_dir("aggregate")) in cost.superseded
    assert lay.rel(lay.node_dir("tag_sections")) not in cost.superseded


def test_destroying_nothing_is_not_the_same_as_costing_nothing(tmp_path):
    """A run stopped before the scenario stage has nothing to supersede, so a
    count reads as free while the re-run buys every scenario, every model and
    every ProVerif call. estimate prices the work bought as well."""
    lay = _layout(tmp_path, upto="extract_flow")
    cost = fixes.estimate(lay, FixPlan("build_root", "redo",
                                       "the fixed layer is wrong"))
    assert cost.superseded == []
    assert cost.reruns == ["build_root", "scenarios", "aggregate",
                           "cross_check", "reproduce_attacks"]
    assert cost.heavy


def test_a_pure_code_step_is_refused(tmp_path):
    """A pure-code step reads no messages: its artifact is a function of its
    inputs, so the re-run would reproduce it unchanged. Refused at addressing,
    before any fact is filed."""
    lay = _layout(tmp_path)
    for name in ("aggregate", "load_document", "cross_check"):
        with pytest.raises(ValueError, match="reads no messages"):
            fixes.estimate(lay, FixPlan(name, "redo", "m"))
        with pytest.raises(ValueError, match="model-driven"):
            fixes.execute(lay, FixPlan(name, "resume", "m"))
    assert not list(lay.run_dir.rglob(facts.FILENAME))


def test_execute_files_the_fact_and_leaves_everything_standing(tmp_path):
    """The whole of what execute does: file the fact. The artifacts are still
    there and still current — they stop being current when the re-run writes
    past them, which is the engine's business."""
    lay = _layout(tmp_path)
    fn = fixes.execute(lay, FixPlan("extract_principals", "resume",
                                    "add S to A's description", directive=True))
    assert fn == "extract_principals"
    got = facts.read(lay.node_dir("extract_principals"))
    assert got and "add S" in got[0].text and got[0].source == "user"
    assert (lay.node_dir("extract_principals") / "principals.json").exists()
    assert (lay.node_dir("extract_flow") / "flow.pv").exists()
    assert lay.results_json.exists()


def test_a_resume_reaches_the_session_as_well_as_the_file(tmp_path):
    """A resumed session replays its transcript, not the fact file, so a fix
    meant for one has to be written into it too."""
    lay = _layout(tmp_path)
    fixes.execute(lay, FixPlan("extract_principals", "resume",
                               "add S", directive=True))
    entries = TranscriptReader(lay.node_transcript("extract_principals")).entries()
    assert any("directive" in e.get("content", "") for e in entries
               if e["t"] == "user")


def test_a_redo_leaves_the_session_alone(tmp_path):
    """A redo starts fresh, and a fresh session reads the fact file — writing
    into the transcript as well would deliver the message twice."""
    lay = _layout(tmp_path)
    fixes.execute(lay, FixPlan("extract_principals", "redo",
                               "extract it all again"))
    entries = TranscriptReader(lay.node_transcript("extract_principals")).entries()
    assert not [e for e in entries if e["t"] == "user"]
    assert [f.text for f in facts.read(lay.node_dir("extract_principals"))] == [
        "[user instruction]\nextract it all again"]


def test_resume_without_a_session_creates_no_ghost(tmp_path):
    """The composite steps keep their sessions deeper down and none at the
    node path, so a resume aimed at one writes no transcript."""
    lay = _layout(tmp_path)
    fn = fixes.execute(lay, FixPlan("build_root", "resume",
                                    "reapply the fixed layer"))
    assert fn == "build_root"
    assert not (lay.node_dir("build_root") / "transcript.jsonl").exists()
    assert facts.read(lay.node_dir("build_root"))


def test_a_path_that_matches_nothing_is_refused(tmp_path):
    """Nothing superseded is not a no-op: the re-entry would find the stage
    complete and re-buy it whole. Pricing and execution both refuse a mistyped
    label, before anything is written."""
    lay = _layout(tmp_path)
    _scenario(lay, "lowe")
    for step in ("scenarios/lowr", "scenarios/base",
                 "scenarios/lowe/apply/nothing",
                 "scenarios/lowe/inject/Nope", "no_such_node"):
        with pytest.raises(ValueError):
            fixes.estimate(lay, FixPlan(step, "resume", "m"))
        with pytest.raises(ValueError):
            fixes.execute(lay, FixPlan(step, "resume", "m"))
    assert not list(lay.run_dir.rglob(facts.FILENAME))
    fixes.estimate(lay, FixPlan("scenarios/lowe", "resume", "m"))


def test_a_step_is_addressed_by_its_identity_not_by_its_number(tmp_path):
    """The number a directory carries is when it ran. A scenario or a point is
    addressed by what it is, and the directory currently holding it is looked
    up — the only way an address survives a re-work."""
    lay = _layout(tmp_path)
    _scenario(lay, "lowe")
    ref = fixes.estimate(lay, FixPlan("08_scenarios/lowe/apply/leaked",
                                      "resume", "m"))
    assert ref.from_node == "scenarios"
    # the same step named through its directory numbers resolves identically
    same = fixes.estimate(lay, FixPlan("scenarios/00_lowe/apply/02_leaked",
                                       "resume", "m"))
    assert same.superseded == ref.superseded


def test_a_scenario_fix_scopes_the_fact_to_that_scenario(tmp_path):
    """The tree is the delivery rule: the fact lives in the scenario's own
    directory, so it reaches that scenario's sessions and no others."""
    lay = _layout(tmp_path)
    _scenario(lay, "lowe")
    _scenario(lay, "other")
    fn = fixes.execute(lay, FixPlan("scenarios/lowe", "resume", "guard the peer"))
    assert fn == "scenarios"
    assert facts.read(lay.scenario_dir("lowe"))
    assert facts.read(lay.scenario_dir("other")) == []
    assert facts.read(lay.node_dir("extract_principals")) == []


def test_an_apply_point_fix_files_at_the_point(tmp_path):
    """A fix aimed inside a step is delivered inside it. What the re-run then
    reuses and what it redoes belongs to the chain's numbering, tested in
    test_apply_reuse."""
    lay = _layout(tmp_path)
    home = _scenario(lay, "lowe")
    _scenario(lay, "other")
    fn = fixes.execute(lay, FixPlan("scenarios/lowe/apply/leaked",
                                    "resume", "wrong guard"))
    assert fn == "scenarios"
    assert facts.read(lay.apply_point_dir(home, "leaked"))
    assert facts.read(lay.apply_point_dir(home, "role_a")) == []
    assert facts.read(lay.scenario_dir("other")) == []


def test_an_inject_family_fix_files_at_the_family(tmp_path):
    lay = _layout(tmp_path)
    _scenario(lay, "lowe")
    fn = fixes.execute(lay, FixPlan("scenarios/lowe/inject/Secrecy",
                                    "resume", "query the wrong pair"))
    assert fn == "scenarios"
    assert facts.read(lay.inject_family_dir("lowe", "Secrecy"))
    assert facts.read(lay.scenario_dir("lowe")) == []
