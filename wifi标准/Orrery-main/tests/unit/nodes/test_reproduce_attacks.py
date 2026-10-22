"""The attack reproduction step end to end on a small run (tests/fixtures/
attack_run): the toy protocol's claims, three scenarios, four false cells, and
a solver stand-in that draws a real attack graph (Lowe's attack on NSPK)."""

import asyncio
import json
from pathlib import Path

import pytest

from orrery.infra.proverif.runner import RawRun
from orrery.modules.attacks.reproduce import LONG
from orrery.nodes.base import NodeError
from orrery.nodes.reproduce_attacks import node as step
from orrery.nodes.reproduce_attacks.node import ReproduceAttacksNode
from orrery.services.store.atomic import write_json, write_text
from tests.fixtures import ATTACK_GRAPHS
from tests.fixtures.attack_run import Solver as _Runner
from tests.fixtures.attack_run import Writer as _Writer
from tests.fixtures.attack_run import attack_env as _env
from tests.fixtures.attack_run import build_run as _run


def _go(env, runner, monkeypatch):
    monkeypatch.setattr(step, "make_runner", lambda config: runner)
    asyncio.run(ReproduceAttacksNode().run(env))
    d = env.layout.node_dir("reproduce_attacks")
    return (json.loads((d / "targets.json").read_text()),
            json.loads((d / "attacks.json").read_text()))


def test_every_false_cell_is_replayed_when_there_are_few(tmp_path, monkeypatch):
    lay = _run(tmp_path)
    env = _env(lay)
    runner = _Runner()
    targets, attacks = _go(env, runner, monkeypatch)
    cells = {(c["label"], c["goal"]): c for c in attacks["cells"]}
    assert set(cells) == {("peer_key_attacker_supplied", "secrecy_i_a"),
                          ("peer_key_attacker_supplied", "secrecy_i_b"),
                          ("peer_key_attacker_supplied", "auth_b_to_a"),
                          ("shared_key_leaked", "auth_b_to_a")}
    assert {c["decision"] for c in cells.values()} == {"auto"}
    assert {c["status"] for c in cells.values()} == {"ok"}
    assert len(runner.calls) == 4 and all(pv.startswith(LONG) for pv in runner.calls)
    one = cells[("shared_key_leaked", "auth_b_to_a")]
    assert one["weakened"] == ["ltk_reveal_kab = disclosed"]
    assert one["display"] == "long" and one["replay"] is False
    script = json.loads((lay.run_dir / one["script"]).read_text())
    assert script["outcome"]["kind"] == "event" and len(script["steps"]) == one["steps"]
    # said before and after each cell
    said = [(e.label, e.goal, e.status) for e in env.bus.events
            if type(e).__name__ == "AttackStatus"]
    assert said.count(("shared_key_leaked", "auth_b_to_a", "running")) == 1
    assert said.count(("shared_key_leaked", "auth_b_to_a", "ok")) == 1
    assert all(e.node == "reproduce_attacks" and e.scenario is None
               for e in env.bus.events if type(e).__name__ == "AttackStatus")
    assert ReproduceAttacksNode().is_done(env)
    assert ReproduceAttacksNode().artifacts(env) == ["targets.json", "attacks.json"]


def test_ground_truth_decides_what_enters(tmp_path, monkeypatch):
    lay = _run(tmp_path)
    peer = [{"id": "admission_peer_auth", "subtype": "open"},
            {"id": "ltk_reveal_kab", "subtype": "none"}]
    write_json(lay.cross_check_json, {"cells": [
        {"id": "secrecy_i_a", "scenario": peer, "ours": "false",
         "expected": "false", "match": True},
        {"id": "secrecy_i_b", "scenario": peer, "ours": "false",
         "expected": "true", "match": False},
        {"id": "auth_b_to_a", "scenario": peer, "ours": "false",
         "expected": "false", "match": True},
    ]})
    runner = _Runner()
    targets, attacks = _go(_env(lay, ground_truth=tmp_path), runner, monkeypatch)
    got = {(c["label"], c["goal"]): (c["decision"], c["reason"]) for c in attacks["cells"]}
    assert got == {
        ("peer_key_attacker_supplied", "secrecy_i_a"): ("auto", ""),
        ("peer_key_attacker_supplied", "secrecy_i_b"): ("skipped", "ground_truth_differs"),
        ("peer_key_attacker_supplied", "auth_b_to_a"): ("auto", ""),
        ("shared_key_leaked", "auth_b_to_a"): ("skipped", "not_compared"),
    }
    assert len(runner.calls) == 2 and attacks["ground_truth"] is True


def test_a_ground_truth_without_its_comparison_is_an_error(tmp_path, monkeypatch):
    lay = _run(tmp_path)
    with pytest.raises(NodeError, match="no cross_check.json"):
        _go(_env(lay, ground_truth=tmp_path), _Runner(), monkeypatch)


def test_past_the_limit_the_rest_waits(tmp_path, monkeypatch):
    lay = _run(tmp_path)
    runner = _Runner()
    targets, attacks = _go(_env(lay, auto_cells=2), runner, monkeypatch)
    decisions = [(c["goal"], c["decision"]) for c in attacks["cells"]]
    # two goals get their first cell before any goal gets a second
    assert [d for _, d in decisions].count("auto") == 2
    assert ("secrecy_i_a", "auto") in decisions and ("secrecy_i_b", "auto") in decisions
    assert len(runner.calls) == 2
    assert all("status" not in c for c in attacks["cells"] if c["decision"] == "pending")


def test_switched_off_the_step_does_nothing(tmp_path, monkeypatch):
    lay = _run(tmp_path)
    runner = _Runner()
    monkeypatch.setattr(step, "make_runner", lambda config: runner)
    env = _env(lay, enabled=False)
    asyncio.run(ReproduceAttacksNode().run(env))
    d = lay.node_dir("reproduce_attacks")
    assert json.loads((d / "attacks.json").read_text()) == {
        "enabled": False, "complete": True, "cells": []}
    assert runner.calls == [] and ReproduceAttacksNode().is_done(env)


def test_a_slow_long_display_falls_back_to_the_default_one(tmp_path, monkeypatch):
    lay = _run(tmp_path)
    runner = _Runner(long_times_out=True)
    _, attacks = _go(_env(lay), runner, monkeypatch)
    assert {c["display"] for c in attacks["cells"]} == {"default"}
    assert {c["status"] for c in attacks["cells"]} == {"ok"}
    assert len(runner.calls) == 8


def test_an_unreadable_graph_is_recorded_on_its_cell(tmp_path, monkeypatch):
    lay = _run(tmp_path)
    _, attacks = _go(_env(lay), _Runner(graph=""), monkeypatch)
    assert {c["status"] for c in attacks["cells"]} == {"failed"}
    assert all(c["reason"].startswith("the attack graph could not be read")
               for c in attacks["cells"])


def test_a_false_cell_without_its_solver_file_fails_the_step(tmp_path, monkeypatch):
    lay = _run(tmp_path, missing="auth_b_to_a")
    with pytest.raises(NodeError, match="no goal-only solver file"):
        _go(_env(lay), _Runner(), monkeypatch)


def test_a_replay_is_read_off_the_solvers_own_words(tmp_path, monkeypatch):
    lay = _run(tmp_path, replay="auth_b_to_a")
    _, attacks = _go(_env(lay), _Runner(), monkeypatch)
    replays = {(c["label"], c["goal"]) for c in attacks["cells"] if c["replay"]}
    assert replays == {("peer_key_attacker_supplied", "auth_b_to_a"),
                       ("shared_key_leaked", "auth_b_to_a")}


def test_every_reproduced_cell_is_explained_and_summed_up(tmp_path, monkeypatch):
    lay = _run(tmp_path)
    writer = _Writer()
    env = _env(lay, writer=writer)
    _, attacks = _go(env, _Runner(), monkeypatch)
    assert attacks["complete"] is True
    for c in attacks["cells"]:
        exp = json.loads((lay.run_dir / c["explanation"]).read_text())
        script = json.loads((lay.run_dir / c["script"]).read_text())
        assert [s["n"] for s in exp["steps"]] == [s["n"] for s in script["steps"]]
        assert exp["conclusion"] == f"{c['goal']} fails in {c['label']}"
    summary = json.loads((lay.run_dir / attacks["summary"]).read_text())
    assert sorted(summary["covered"]) == sorted(
        f"{c['label']}/{c['goal']}" for c in attacks["cells"])
    assert summary["groups"][0]["cells"] == summary["covered"]
    # the prompt carries the scenario's assumptions and the goal's meaning
    first = next(u for u in writer.users if "shared_key_leaked" in u)
    assert "ltk_reveal_kab = disclosed (data, of KAB; chosen by this scenario)" in first
    assert "auth_b_to_a (Authentication." in first
    assert ReproduceAttacksNode().is_done(env)


def test_a_failed_explanation_fails_the_step_but_keeps_the_scripts(tmp_path, monkeypatch):
    lay = _run(tmp_path)
    env = _env(lay, writer=_Writer(fail={"shared_key_leaked/auth_b_to_a"}),)
    env.config["agent"]["max_repairs"] = 1
    env.config["agent"]["max_rounds"] = 2
    with pytest.raises(NodeError, match="1 explanation"):
        _go(env, _Runner(), monkeypatch)
    d = lay.node_dir("reproduce_attacks")
    attacks = json.loads((d / "attacks.json").read_text())
    assert attacks["complete"] is False
    bad = next(c for c in attacks["cells"] if c["label"] == "shared_key_leaked")
    assert "explain_error" in bad and (lay.run_dir / bad["script"]).is_file()
    good = [c for c in attacks["cells"] if c["label"] != "shared_key_leaked"]
    assert all("explanation" in c for c in good)
    assert "summary" in attacks            # the explained cells are still summed up
    assert not ReproduceAttacksNode().is_done(env)


def test_carrying_on_reads_back_what_is_there(tmp_path, monkeypatch):
    lay = _run(tmp_path)
    env = _env(lay, writer=_Writer(fail={"shared_key_leaked/auth_b_to_a"}))
    env.config["agent"]["max_repairs"] = 1
    env.config["agent"]["max_rounds"] = 2
    runner = _Runner()
    with pytest.raises(NodeError):
        _go(env, runner, monkeypatch)
    assert len(runner.calls) == 4
    writer = _Writer()
    env._llm = writer
    _, attacks = _go(env, runner, monkeypatch)
    assert attacks["complete"] is True
    assert len(runner.calls) == 4          # no cell was re-run
    explained = [u for u in writer.users if "Explain this attack" in u]
    assert len(explained) == 1             # only the one that had failed


def test_a_weak_secret_cell_is_reproduced_as_an_offline_guess(tmp_path, monkeypatch):
    lay = _run(tmp_path)
    fam = lay.find_inject_family_dir("shared_key_leaked", "Authentication")
    write_text(fam / "02_proverif_trace_auth_b_to_a.pv",
               "free k: password [private].\nweaksecret k.\nprocess 0\n")
    write_text(fam / "02_proverif_trace_auth_b_to_a.txt",
               "RESULT Weak secret k is false.\n")

    class _Weak(_Runner):
        async def run(self, pv, log_to, extra_args=(), timeout_s=None):
            if "weaksecret" not in pv:
                return await super().run(pv, log_to, extra_args, timeout_s)
            self.calls.append(pv)
            write_text(Path(f"{log_to}.pv"), pv)
            write_text(Path(f"{log_to}.txt"), "RESULT Weak secret k is false.\n")
            where = Path(extra_args[extra_args.index("-graph") + 1])
            write_text(where / "trace1.dot",
                       (ATTACK_GRAPHS / "weak_offline_guess.dot").read_text())
            return RawRun(stdout="RESULT Weak secret k is false.\n", stderr="",
                          returncode=0, duration_s=0.1, timed_out=False)

    _, attacks = _go(_env(lay), _Weak(), monkeypatch)
    weak = next(c for c in attacks["cells"] if c["label"] == "shared_key_leaked")
    assert weak["status"] == "ok" and weak["steps"] == 3
    script = json.loads((lay.run_dir / weak["script"]).read_text())
    assert script["outcome"]["kind"] == "guess"
    assert "explanation" in weak
    assert (lay.run_dir / weak["home"] / "trace.txt").is_file()
    others = [c for c in attacks["cells"] if c["label"] != "shared_key_leaked"]
    assert {c["status"] for c in others} == {"ok"} and attacks["complete"]
