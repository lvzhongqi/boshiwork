"""Tests for facts: each step's messages live in the step's own directory, the
directory tree is the delivery rule, and RunEnv reads a step's chain when it
builds the prompt. The failure guarded against is a message written but never
read back, so a fix or an accepted gap reaches nobody."""

from orrery.nodes.base import RunEnv
from orrery.services import facts
from orrery.services.store.layout import RunLayout


def _env(tmp_path, run="r1", *, steps=("extract_principals", "extract_flow",
                                       "scenarios")) -> RunEnv:
    """A RunEnv with the given steps opened. Opening is what creates each
    step's directory, and a step's facts live in that directory."""
    lay = RunLayout(tmp_path / "wr", "NSPK", run)
    lay.run_dir.mkdir(parents=True, exist_ok=True)
    for s in steps:
        lay.open_node(s)
    return RunEnv(protocol_dir=tmp_path / "NSPK", layout=lay, config={})


def test_a_fact_reaches_its_own_subtree_only(tmp_path):
    run = tmp_path / "run"
    facts.append(run / "03_extract_principals", source="user", text="add S")
    facts.append(run / "08_scenarios", source="user", text="guard both")
    facts.append(run / "08_scenarios" / "lowe", source="user", text="only here")

    assert [x.text for x in facts.collect(run, "03_extract_principals")] == ["add S"]
    assert facts.collect(run, "04_extract_flow") == []
    # an ancestor's fact reaches the subtree under it; a sibling's does not
    assert [x.text for x in facts.collect(run, "08_scenarios/lowe")] == [
        "guard both", "only here"]
    assert [x.text for x in facts.collect(run, "08_scenarios/other")] == ["guard both"]


def test_source_order_and_multiline_text_survive(tmp_path):
    d = tmp_path / "04_extract_flow"
    facts.append(d, source="user", text="line one\n\nline two")
    facts.append(d, source="gap:apply:s1", text="missing K_bs")
    got = facts.read(d)
    assert [x.source for x in got] == ["user", "gap:apply:s1"]
    assert got[0].text == "line one\n\nline two"


def test_an_unreadable_line_is_an_error(tmp_path):
    """A skipped line is a message silently dropped, so an unreadable line
    raises instead."""
    d = tmp_path / "04_extract_flow"
    d.mkdir()
    (d / facts.FILENAME).write_text('{"ts": "t"}\n', encoding="utf-8")
    try:
        facts.read(d)
    except RuntimeError as e:
        assert "reach no step" in str(e)
    else:
        raise AssertionError("a dropped fact must not pass silently")


def test_runenv_inlines_only_matching_facts(tmp_path):
    env = _env(tmp_path)
    facts.append(env.layout.node_dir("extract_principals"),
                 source="user", text="add S")

    section = env.facts("extract_principals")
    assert "add S" in section and "<step_messages>" in section
    assert env.facts("extract_flow") == ""      # another step: nothing


def test_scenario_scope_is_the_directory_chain(tmp_path):
    """env.facts("scenarios", label) reads the stage directory plus the
    scenario directory under it. The tree is the delivery rule, so addresses
    can deepen down to a single apply point without a schema change."""
    env = _env(tmp_path)
    facts.append(env.layout.scenarios_root, source="user", text="guard both")
    env.layout.open_scenario("lowe")
    env.layout.open_scenario("other")
    facts.append(env.layout.scenario_dir("lowe"), source="user", text="only here")
    lowe = env.facts("scenarios", "lowe")
    assert "guard both" in lowe and "only here" in lowe
    assert "only here" not in env.facts("scenarios", "other")


def test_facts_at_reaches_a_deep_step(tmp_path):
    env = _env(tmp_path)
    env.layout.open_scenario("lowe")
    point = env.layout.open_apply_point(env.layout.scenario_dir("lowe"),
                                        "ltk_reveal_A")
    facts.append(point, source="user", text="the guard is wrong")
    section = env.facts_at(env.layout.rel(point))
    assert "the guard is wrong" in section


def test_facts_belong_to_one_run(tmp_path):
    """The files sit in the run directory, so the next run of the same
    protocol starts clean; a fact does not outlive the run it was about."""
    env = _env(tmp_path)
    facts.append(env.layout.node_dir("extract_principals"),
                 source="user", text="add S")
    assert env.layout.node_dir("extract_principals").is_relative_to(env.layout.run_dir)

    other = _env(tmp_path, "r2")
    assert other.facts("extract_principals") == ""
