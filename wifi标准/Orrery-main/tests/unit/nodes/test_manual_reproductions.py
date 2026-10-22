"""Reproductions asked for after the run (nodes/reproduce_attacks/manual): which
cells may be asked for, where they are written, when they go out of date, and
the summary rewritten over them."""

import asyncio
import json

from orrery.nodes.reproduce_attacks import manual
from orrery.nodes.reproduce_attacks import node as step
from orrery.nodes.reproduce_attacks.node import ReproduceAttacksNode
from orrery.services.store.atomic import write_text
from tests.fixtures.attack_run import Solver, Writer, attack_env, build_run, query

WAITING = ("shared_key_leaked", "auth_b_to_a")


def _step(tmp_path, monkeypatch, **env):
    """The run after its attack step replayed two cells and left two waiting."""
    lay = build_run(tmp_path)
    e = attack_env(lay, auto_cells=2, **env)
    monkeypatch.setattr(step, "make_runner", lambda config: Solver())
    asyncio.run(ReproduceAttacksNode().run(e))
    return lay, e


def _decisions(lay):
    return {k: t["decision"] for k, t in manual.targets(lay).items()}


def _ask(e, label, goal):
    return asyncio.run(manual.reproduce_asked(
        e, Solver(), label=label, goal=goal, emit=e.emitter("reproduce_attacks")))


def test_only_a_cell_the_step_left_waiting_can_be_asked_for(tmp_path, monkeypatch):
    lay, _ = _step(tmp_path, monkeypatch)
    decisions = _decisions(lay)
    assert decisions[WAITING] == "pending"
    auto = next(k for k, d in decisions.items() if d == "auto")
    assert manual.refusal(lay, *WAITING) is None
    assert "re-run the step" in manual.refusal(lay, *auto)
    assert "not a false cell" in manual.refusal(lay, "baseline", "secrecy_i_a")


def test_an_asked_cell_is_reproduced_and_explained_beside_the_run(tmp_path, monkeypatch):
    lay, e = _step(tmp_path, monkeypatch)
    e.bus.events.clear()
    outcome = _ask(e, *WAITING)
    home = lay.run_dir / "_attacks" / "shared_key_leaked" / "auth_b_to_a"
    assert outcome["status"] == "ok" and outcome["home"] == lay.rel(home)
    for name in ("trace.pv", "trace.dot", "msc.json", "reproduction.json",
                 "explanation.json"):
        assert (home / name).is_file(), name
    said = [(ev.status, ev.manual) for ev in e.bus.events
            if type(ev).__name__ == "AttackStatus"]
    assert said == [("running", True), ("ok", True)]
    # the explanation session is addressed by its directory under the run
    units = {ev.unit for ev in e.bus.events if type(ev).__name__ == "PromptFiled"}
    assert units == {"_attacks/shared_key_leaked/auth_b_to_a"}
    done = manual.manual_outcome(lay, *WAITING)
    assert done["manual"] and not done["stale"]
    assert done["explanation"] == lay.rel(home / "explanation.json")
    assert manual.refusal(lay, *WAITING) == "already reproduced"


def test_a_redone_scenario_leaves_the_reproduction_out_of_date(tmp_path, monkeypatch):
    lay, e = _step(tmp_path, monkeypatch)
    _ask(e, *WAITING)
    # the scenario runs again: its goal family lands in a new directory, and
    # the steps after it run again too
    fam = lay.open_inject_family("shared_key_leaked", "Authentication", cause="rerun")
    write_text(fam / "02_proverif_trace_auth_b_to_a.pv", "process 0\n")
    write_text(fam / "02_proverif_trace_auth_b_to_a.txt",
               f"RESULT {query('auth_b_to_a')} is false.\n")
    assert manual.targets(lay) == {}           # the step's work is not current
    lay.open_node("reproduce_attacks", cause="rerun")
    asyncio.run(ReproduceAttacksNode().run(e))
    assert _decisions(lay)[WAITING] == "pending"
    assert manual.manual_outcome(lay, *WAITING)["stale"] is True
    assert manual.refusal(lay, *WAITING) is None
    # asking again sets the first attempt aside, whole
    again = _ask(e, *WAITING)
    home = lay.attack_dir(*WAITING, manual=True)
    assert (home / "superseded-1" / "explanation.json").is_file()
    assert again["source"] == lay.rel(fam / "02_proverif_trace_auth_b_to_a.pv")
    assert manual.manual_outcome(lay, *WAITING)["stale"] is False


def test_a_failed_explanation_is_recorded_and_can_be_asked_again(tmp_path, monkeypatch):
    lay, e = _step(tmp_path, monkeypatch)
    e._llm = Writer(fail={"shared_key_leaked/auth_b_to_a"})
    e.config["agent"]["max_repairs"] = 1
    e.config["agent"]["max_rounds"] = 2
    outcome = _ask(e, *WAITING)
    assert outcome["status"] == "ok" and "explain_error" in outcome
    home = lay.attack_dir(*WAITING, manual=True)
    assert "explain_error" in json.loads((home / "reproduction.json").read_text())
    assert manual.refusal(lay, *WAITING) is None


def test_the_rewritten_summary_covers_the_step_and_the_asked_cells(tmp_path, monkeypatch):
    lay, e = _step(tmp_path, monkeypatch)
    before, waiting = manual.summary_input(lay)
    assert len(before) == 2 and waiting == 2
    _ask(e, *WAITING)
    e.bus.events.clear()
    doc = asyncio.run(manual.resummarize(e))
    assert len(doc["covered"]) == 3 and doc["pending"] == 1
    assert "shared_key_leaked/auth_b_to_a" in doc["covered"]
    path = manual.manual_summary(lay)
    assert path == lay.run_dir / "_attacks" / "summary" / "summary.json"
    assert json.loads(path.read_text())["covered"] == doc["covered"]
    units = {ev.unit for ev in e.bus.events if type(ev).__name__ == "PromptFiled"}
    assert units == {"_attacks/summary"}
