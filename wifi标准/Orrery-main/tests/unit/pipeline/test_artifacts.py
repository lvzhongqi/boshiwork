"""What each node reports as its artifacts (Node.artifacts → NodeFinished →
work.md).

The default lists the node directory's own files, which is enough for aggregate
and cross_check. A node whose products land in a scenario tree has to override
it, or the run's most important files go unreported."""

from orrery.nodes.aggregate.node import AggregateNode
from orrery.nodes.base import RunEnv
from orrery.nodes.cross_check.node import CrossCheckNode
from orrery.pipeline.scenarios import ScenariosNode
from orrery.services.store.layout import RunLayout


def _env(tmp_path, *steps):
    lay = RunLayout(tmp_path, "NSPK", "run1")
    lay.run_dir.mkdir(parents=True, exist_ok=True)
    for s in steps:
        lay.open_node(s)
    return RunEnv(protocol_dir=tmp_path / "NSPK", layout=lay, config={})


def _touch(p, text=""):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_scenarios_reports_the_canonical_chain(tmp_path):
    env = _env(tmp_path, "build_root", "scenarios")
    lay = env.layout
    # the root model is build_root's product, so it is not reported here
    _touch(lay.root_pv)
    s1 = lay.open_scenario("s1")
    point = lay.open_apply_point(s1, "input_binding_A")
    lay.open_inject_family("s1", "Secrecy")
    _touch(lay.scenario_pv("s1"))
    _touch(lay.scenario_verdict("s1"))
    _touch(lay.inject_model("s1", "Secrecy"))
    # working files stay off the list: rounds, transcripts, solver logs
    _touch(point / "rounds" / "01_r1.pv")
    _touch(point / "rounds" / "00_prompt.md")
    _touch(lay.apply_transcript(s1, "input_binding_A"))
    _touch(lay.inject_family_dir("s1", "Secrecy") / "proverif.txt")
    assert ScenariosNode().artifacts(env) == [
        # each result is reported inside the numbered band that produced it
        "00_s1/apply/scenario.pv",
        "00_s1/inject/00_Secrecy/model.pv",
        "00_s1/verdict.json",
    ]


def test_aggregate_and_cross_check_report_their_real_paths(tmp_path):
    env = _env(tmp_path, "aggregate", "cross_check")
    assert AggregateNode().artifacts(env) == []
    _touch(env.layout.results_json, "{}")
    _touch(env.layout.cases_results_json, "{}")
    assert AggregateNode().artifacts(env) == ["cases_results.json",
                                              "results.json"]
    assert CrossCheckNode().artifacts(env) == []
    _touch(env.layout.cross_check_json, "{}")
    assert CrossCheckNode().artifacts(env) == ["cross_check.json"]


def test_a_step_that_never_ran_reports_nothing_rather_than_raising(tmp_path):
    """An artifact listing legitimately meets a step with no work, because a
    run that stopped early still has to render."""
    env = _env(tmp_path)
    assert ScenariosNode().artifacts(env) == []
    assert AggregateNode().artifacts(env) == []


def test_going_back_leaves_the_earlier_answers_where_they_are(tmp_path):
    """Supersession is positional: re-running aggregate opens a new directory,
    and the earlier answers stay on disk but stop being what the run resolves
    to."""
    env = _env(tmp_path, "aggregate")
    lay = env.layout
    _touch(lay.results_json, '{"v": 1}')
    first = lay.results_json

    lay.open_node("aggregate", cause="gap", by="scenarios")
    assert first.exists() and first.read_text() == '{"v": 1}'   # untouched
    assert lay.results_json != first                            # and not the answer
    assert not lay.results_json.exists()                        # nothing written yet
    assert AggregateNode().artifacts(env) == []
