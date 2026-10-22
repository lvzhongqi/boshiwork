"""The work.md projector: ledger → a readable account. The ledger is the only
data source, and with no agent-domain events it degrades to a skeleton."""

import json

from orrery.pipeline.journey import generate
from orrery.services.events import (
    CheckReport, CrossChecked, EventBus, FrameworkAction, GapReported,
    GapVerdict, NodeFinished, NodeProgress, NodeStarted, RoundStarted,
    RunFailed, RunFinished, ScenarioFinished, ScenarioStarted, ToolCalled,
)
from orrery.services.store.atomic import write_json


def _bus_with_full_journey(run_dir):
    bus = EventBus(run_dir / "events.jsonl")
    r = "P1"
    bus.emit(NodeStarted(run=r, node="extract_principals", dir="03_extract_principals"))
    bus.emit(RoundStarted(run=r, node="extract_principals", round_no=1))
    bus.emit(ToolCalled(run=r, node="extract_principals",
                        tool="read_section", args_digest="number=2"))
    bus.emit(FrameworkAction(run=r, node="extract_principals",
                             text="spliced 2 edit(s) into the model"))
    bus.emit(CheckReport(run=r, node="extract_principals", passed=True, attempt=1))
    bus.emit(NodeFinished(run=r, node="extract_principals",
                          artifacts=["principals.json"]))
    bus.emit(NodeStarted(run=r, node="scenarios", dir="08_scenarios"))
    bus.emit(ScenarioStarted(run=r, node="scenarios", scenario="sc_a",
                             assignment=[{"id": "k_ab", "axis": "ltk_reveal",
                                     "subtype": "lkr_from_start",
                                     "target": {"of": "B", "phase": 1},
                                     "from": "condition"},
                                    {"id": "rb", "axis": "role_binding",
                                     "subtype": "any_roles",
                                     "target": {"principals": ["A", "B"]},
                                     "from": "fixed"}]))
    bus.emit(GapReported(run=r, node="apply", scenario="sc_a",
                         target="extract_principals", missing="K_bs"))
    bus.emit(GapVerdict(run=r, node="extract_principals", accepted=False,
                        reason="the artifact already has this value"))
    bus.emit(ScenarioFinished(run=r, node="scenarios", scenario="sc_a",
                              verdicts={"g1": "true"}))
    bus.emit(NodeFinished(run=r, node="scenarios"))
    bus.emit(RunFinished(run=r))
    return bus


def test_generate_full_journey(tmp_path):
    _bus_with_full_journey(tmp_path)
    write_json(tmp_path / "run.json", {
        "protocol": "P1", "run_name": "P1", "status": "ok",
        "nodes": {"extract_principals": "ok"}})
    text = generate(tmp_path).read_text()
    assert "## 03_extract_principals" in text
    assert "**Round 1**" in text and "**Task**:" in text
    assert "**Called**" in text and "`read_section(number=2)`" in text
    assert "**Framework**: spliced 2 edit(s) into the model" in text
    assert "**Checks**: ✅" in text
    assert "principals.json" in text
    assert "### 08_01 · Scenario sc_a" in text
    # a verdict is an answer, not a judgement: coloured dot, never a tick
    assert "| `g1` | 🟢 <span" in text and "✅ `g1" not in text
    assert "**Scenario verdict** — under `k_ab=lkr_from_start`" in text
    # its assignment, fixed dimensions included
    assert "**Assumptions in force**" in text
    assert "| `k_ab` | ltk_reveal | of=B, phase=1 | `lkr_from_start` |" in text
    assert "fixed — every scenario carries it" in text
    # no ground truth: no empty columns
    assert "ground truth" not in text
    assert "✅ done" in text
    assert "gap reported" in text and "rejected" in text


def test_ground_truth_lands_next_to_each_scenario_verdict(tmp_path):
    # work.md is projected once the run is over, so each scenario's verdict can
    # carry the ground truth cross_check computed later, with nothing written back
    bus = EventBus(tmp_path / "events.jsonl")
    r = "P"
    assignment = [{"id": "k", "axis": "ltk_reveal", "subtype": "secret",
              "target": {"of": "K"}, "from": "default"}]
    bus.emit(NodeStarted(run=r, node="scenarios", dir="08_scenarios"))
    bus.emit(ScenarioStarted(run=r, node="scenarios", scenario="sc", assignment=assignment))
    bus.emit(ScenarioFinished(run=r, node="scenarios", scenario="sc",
                              verdicts={"g1": "false", "g2": "true"}))
    bus.emit(NodeFinished(run=r, node="scenarios"))
    bus.emit(NodeStarted(run=r, node="cross_check", dir="10_cross_check"))
    bus.emit(CrossChecked(run=r, node="cross_check", cells=[
        {"id": "g1", "scenario": [{"id": "k", "subtype": "secret"}],
         "ours": "false", "expected": "false", "match": True},
        {"id": "g2", "scenario": [{"id": "k", "subtype": "secret"}],
         "ours": "true", "expected": "false", "match": False},
    ]))
    bus.emit(NodeFinished(run=r, node="cross_check"))
    write_json(tmp_path / "run.json", {"protocol": "P", "run_name": "P",
                                       "status": "failed", "nodes": {}})
    text = generate(tmp_path).read_text()
    assert "| goal | verdict | ground truth | agrees |" in text
    assert "✅ yes |" in text and "❌ **no** |" in text
    assert "· 1/2 cell(s) agree with ground truth" in text


def test_a_failed_check_never_reads_as_a_failed_node(tmp_path):
    # cross_check disagreeing with ground truth is an answer, not a breakage:
    # the words "node failed" are kept for a node that could not finish
    bus = EventBus(tmp_path / "events.jsonl")
    r = "P"
    bus.emit(NodeStarted(run=r, node="cross_check", dir="10_cross_check"))
    bus.emit(NodeFinished(run=r, node="cross_check", status="check_failed",
                          artifacts=["cross_check.json"]))
    bus.emit(RunFailed(run=r, node="cross_check", kind="check",
                       reason="1 of 8 cells differ from the ground truth"))
    write_json(tmp_path / "run.json", {"protocol": "P", "run_name": "P",
                                       "status": "check_failed", "nodes": {}})
    text = generate(tmp_path).read_text()
    assert "**Status**: ≠ differs from the corpus" in text
    assert "≠ done, differs from the corpus — artifacts: `cross_check.json`" in text
    assert "**differs from the corpus**: 1 of 8 cells differ" in text
    assert "node failed" not in text
    # the wording carries no failure at all: the run finished and wrote its report
    assert "did not pass" not in text
    assert "❌" not in text


def test_a_node_that_broke_says_so(tmp_path):
    bus = EventBus(tmp_path / "events.jsonl")
    bus.emit(NodeStarted(run="P", node="extract_flow"))
    bus.emit(NodeFinished(run="P", node="extract_flow", status="failed"))
    bus.emit(RunFailed(run="P", node="extract_flow",
                       reason="extract_flow: repair rounds exhausted"))
    write_json(tmp_path / "run.json", {"protocol": "P", "run_name": "P",
                                       "status": "failed", "nodes": {}})
    text = generate(tmp_path).read_text()
    assert "**Status**: 💥 failed" in text
    assert "💥 node failed" in text
    assert "**run failed**: extract_flow" in text


def test_generate_degrades_without_agent_events(tmp_path):
    # a pure-code node emits no agent events: the skeleton is still produced,
    # and no rounds are invented
    bus = EventBus(tmp_path / "events.jsonl")
    bus.emit(NodeStarted(run="P", node="claims", dir="05_claims"))
    bus.emit(NodeFinished(run="P", node="claims", artifacts=["assumptions.json"]))
    write_json(tmp_path / "run.json", {"protocol": "P", "run_name": "P",
                                       "status": "failed", "nodes": {}})
    text = generate(tmp_path).read_text()
    assert "## 05_claims" in text and "**Round 1**" not in text


def test_review_step_is_recorded_after_the_rounds(tmp_path):
    # the flow model node's independent review runs outside run_agent and reports
    # itself with NodeProgress; outside a round those render as node information
    # lines
    bus = EventBus(tmp_path / "events.jsonl")
    r = "P"
    bus.emit(NodeStarted(run=r, node="extract_flow", dir="04_extract_flow"))
    bus.emit(RoundStarted(run=r, node="extract_flow", round_no=1))
    bus.emit(CheckReport(run=r, node="extract_flow", passed=True, attempt=1))
    bus.emit(NodeProgress(run=r, node="extract_flow",
                          text="independent review (warning level, non-blocking): "
                               "reconciling the flow model against the six-item list"))
    bus.emit(NodeProgress(run=r, node="extract_flow",
                          text="independent review: 2 model call(s), 1 finding(s), "
                               "0 confirmed by mechanical search — full session in "
                               "z3_review.jsonl"))
    bus.emit(NodeFinished(run=r, node="extract_flow",
                          artifacts=["flow.pv", "z3_review.json",
                                     "z3_review.jsonl"]))
    write_json(tmp_path / "run.json", {"protocol": "P", "run_name": "P",
                                       "status": "ok", "nodes": {}})
    text = generate(tmp_path).read_text()
    body = text.split("## 04_extract_flow")[1]
    assert "· independent review (warning level, non-blocking)" in body
    assert "· independent review: 2 model call(s), 1 finding(s)" in body
    assert "z3_review.jsonl" in body
    # the review is not a repair round, so it is not rendered as one
    assert body.count("**Round") == 1


def test_emitter_stamps_envelope(tmp_path):
    from orrery.nodes.base import RunEnv
    from orrery.services.store.layout import RunLayout
    lay = RunLayout(tmp_path, "P", "r1")
    env = RunEnv(protocol_dir=tmp_path, layout=lay, config={})
    env.bus = EventBus(lay.events_path)
    emit = env.emitter("apply", scenario="sc_x")
    emit(RoundStarted(run="", node="apply:sc_x", round_no=2))
    line = json.loads((lay.events_path).read_text().splitlines()[0])
    assert line["run"] == "r1" and line["scenario"] == "sc_x"
    assert line["node"] == "apply:sc_x" and line["data"]["round_no"] == 2

    # an emitter bound to a unit stamps it too; a stage-wide emitter binds none,
    # which is how a summary line is told from a session's own
    env.emitter("apply", scenario="sc_x", unit="apply/03_x")(
        RoundStarted(run="", round_no=1))
    lines = [json.loads(x) for x in lay.events_path.read_text().splitlines()]
    assert lines[1]["unit"] == "apply/03_x" and lines[1]["node"] == "apply"
    assert lines[0]["unit"] is None


def test_the_root_model_is_rendered_under_its_own_step(tmp_path):
    """The root model's apply sessions carry a scenario-shaped identity, so the
    projector buffers them the way it buffers a scenario's. They flush at
    build_root's own boundary; under the scenario stage they would read as work
    that stage did."""
    bus = EventBus(tmp_path / "events.jsonl")
    r = "P1"
    bus.emit(NodeStarted(run=r, node="build_root", dir="07_build_root"))
    bus.emit(FrameworkAction(run=r, node="apply", scenario="root",
                             text="spliced 3 edit(s) into the model"))
    bus.emit(NodeFinished(run=r, node="build_root", artifacts=["z0_root.pv"]))
    bus.emit(NodeStarted(run=r, node="scenarios", dir="08_scenarios"))
    bus.emit(ScenarioStarted(run=r, node="scenarios", scenario="sc_a", assignment=[]))
    bus.emit(ScenarioFinished(run=r, node="scenarios", scenario="sc_a",
                              verdicts={"g1": "true"}))
    bus.emit(NodeFinished(run=r, node="scenarios"))
    bus.emit(RunFinished(run=r))
    write_json(tmp_path / "run.json", {
        "protocol": "P1", "run_name": "P1", "status": "ok",
        "nodes": {"build_root": "ok", "scenarios": "ok"}})
    text = generate(tmp_path).read_text()

    assert "### 07_01 · Root model" in text
    assert "Root model root" not in text        # it is not a scenario, and is not named as one
    # and it lands inside build_root's section, before the scenario stage opens
    assert text.index("### 07_01 · Root model") < text.index("## 08_scenarios")
    # the scenarios keep their own numbering, unshifted by the root model
    assert "### 08_01 · Scenario sc_a" in text


def test_concurrent_units_get_their_own_sections(tmp_path):
    """The scenario stage runs a session per applied assumption and per injected
    goal family, all at once and all stamped node="inject". The unit on the
    envelope is what keeps their rounds out of one pile."""
    run_dir = tmp_path / "run"
    bus = EventBus(run_dir / "events.jsonl")
    r = "P1"
    bus.emit(NodeStarted(run=r, node="scenarios", dir="08_scenarios"))
    bus.emit(ScenarioStarted(run=r, node="scenarios", scenario="sc_a"))
    for unit, tool in (("inject/Secrecy", "read_artifact"),
                       ("inject/Authentication", "grep_document")):
        bus.emit(RoundStarted(run=r, node="inject", scenario="sc_a",
                              unit=unit, round_no=1))
        bus.emit(ToolCalled(run=r, node="inject", scenario="sc_a", unit=unit,
                            tool=tool, args_digest="x"))
    bus.emit(ScenarioFinished(run=r, node="scenarios", scenario="sc_a",
                              verdicts={"g1": "true"}))
    bus.emit(NodeFinished(run=r, node="scenarios"))
    write_json(run_dir / "run.json", {"protocol": "P", "run_name": "r1",
                                      "status": "ok", "nodes": {}})

    text = generate(run_dir).read_text(encoding="utf-8")
    assert "**Inject family Secrecy**" in text
    assert "**Inject family Authentication**" in text
    # each session's tool call sits under its own heading, not in one pile
    head_s = text.index("**Inject family Secrecy**")
    head_a = text.index("**Inject family Authentication**")
    lo, hi = sorted((head_s, head_a))
    assert text.count("read_artifact", lo, hi) + text.count("grep_document", lo, hi) == 1


def test_a_ledger_without_units_still_renders(tmp_path):
    """A ledger with no ``unit`` field carries the composite in ``node``
    instead, and the projector still finds the session's heading there."""
    run_dir = tmp_path / "run"
    bus = EventBus(run_dir / "events.jsonl")
    r = "P1"
    bus.emit(NodeStarted(run=r, node="scenarios", dir="08_scenarios"))
    bus.emit(ScenarioStarted(run=r, node="scenarios", scenario="sc_a"))
    bus.emit(RoundStarted(run=r, node="apply:sc_a:03_lkr_from_start",
                          scenario="sc_a", round_no=1))
    bus.emit(ScenarioFinished(run=r, node="scenarios", scenario="sc_a"))
    bus.emit(NodeFinished(run=r, node="scenarios"))
    write_json(run_dir / "run.json", {"protocol": "P", "run_name": "r1",
                                      "status": "ok", "nodes": {}})

    text = generate(run_dir).read_text(encoding="utf-8")
    assert "**Apply 03_lkr_from_start**" in text
