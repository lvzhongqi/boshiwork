"""The console's side of attack reproduction: the index it reads
(api/attacks.index), the queue it asks through (api/attacks.Reproductions) and
the routes over both.

The step writes ``targets.json`` first, each cell's files as it finishes them,
and ``attacks.json`` last; the index has to read all three moments, and the
cells asked for after the run beside them.
"""

import asyncio
import json
import os

import pytest
from fastapi.testclient import TestClient

from orrery.api import attacks as api_attacks
from orrery.api.attacks import QueueBusy, Reproductions, index
from orrery.nodes.reproduce_attacks import node as step
from orrery.nodes.reproduce_attacks.node import ReproduceAttacksNode
from orrery.pipeline.config import load_config
from orrery.services.store.layout import RunLayout
from orrery.web import server
from tests.fixtures.attack_run import Solver, attack_env, build_run

AUTO = {"goal": "secrecy_na", "label": "open", "decision": "auto", "reason": "",
        "expected": "", "weakened": [], "round": 1}
WAITING = {"goal": "auth_b_a", "label": "open", "decision": "pending",
           "reason": "over_limit", "expected": "", "weakened": [], "round": 2}
PLAIN = {"manual": False, "stale": False}


def _layout(tmp_path) -> RunLayout:
    lay = RunLayout(tmp_path / "wr", "NSPK", "NSPK01")
    lay.run_dir.mkdir(parents=True)
    return lay


def _write(path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_a_run_that_never_reached_the_step_has_nothing(tmp_path):
    lay = _layout(tmp_path)
    lay.open_node("cross_check")
    assert index(lay.run_dir) == {"step": None, "cells": [], "summary": None}


def test_a_step_at_work_reads_each_cell_back_as_it_finishes(tmp_path):
    lay = _layout(tmp_path)
    home = lay.open_node("reproduce_attacks")
    _write(home / "targets.json", {"limit": 1, "ground_truth": False,
                                   "targets": [AUTO, WAITING]})
    cell = home / "open" / "secrecy_na"
    _write(cell / "reproduction.json", {
        "goal": "secrecy_na", "label": "open", "status": "ok", "steps": 4,
        "script": f"{lay.rel(cell)}/msc.json", "home": lay.rel(cell)})
    out = index(lay.run_dir)
    assert out["step"] == {"dir": lay.rel(home), "enabled": True,
                           "complete": False, "ground_truth": False, "limit": 1}
    done, waiting = out["cells"]
    assert done["status"] == "ok" and done["steps"] == 4
    assert "explanation" not in done
    assert waiting == {**WAITING, **PLAIN}
    # the explanation lands later, and the next reading has it
    _write(cell / "explanation.json", {"opening": "o", "steps": [], "conclusion": "c"})
    assert index(lay.run_dir)["cells"][0]["explanation"] == \
        f"{lay.rel(cell)}/explanation.json"
    assert out["summary"] is None


def test_a_finished_step_is_its_attacks_file_with_the_summary_inlined(tmp_path):
    lay = _layout(tmp_path)
    home = lay.open_node("reproduce_attacks")
    _write(home / "targets.json", {"limit": 10, "ground_truth": True,
                                   "targets": [AUTO]})
    summary = {"covered": ["open/secrecy_na"], "pending": 0,
               "groups": [{"problem": "p", "cells": ["open/secrecy_na"]}],
               "summary": "s"}
    _write(home / "summary" / "summary.json", summary)
    _write(home / "attacks.json", {
        "enabled": True, "complete": True, "ground_truth": True,
        "cells": [{**AUTO, "status": "ok"}],
        "summary": f"{lay.rel(home)}/summary/summary.json"})
    out = index(lay.run_dir)
    assert out["step"]["complete"] and out["step"]["ground_truth"]
    assert out["cells"] == [{**AUTO, "status": "ok", **PLAIN}]
    assert out["summary"] == {"path": f"{lay.rel(home)}/summary/summary.json",
                              "manual": False, **summary}


def test_a_step_switched_off_says_so(tmp_path):
    lay = _layout(tmp_path)
    home = lay.open_node("reproduce_attacks")
    _write(home / "attacks.json", {"enabled": False, "complete": True, "cells": []})
    out = index(lay.run_dir)
    assert out["step"]["enabled"] is False and out["cells"] == []


# ── cells asked for after the run ───────────────────────────────────────

def _stepped(tmp_path, monkeypatch):
    """A real small run whose attack step replayed two cells and left two
    waiting, with the run.json a queue reads."""
    lay = build_run(tmp_path)
    env = attack_env(lay, auto_cells=2)
    monkeypatch.setattr(step, "make_runner", lambda config: Solver())
    asyncio.run(ReproduceAttacksNode().run(env))
    (lay.run_dir / "run.json").write_text(json.dumps({
        "protocol": "P", "protocol_id": "TOY", "protocol_dir": str(lay.root),
        "run_name": "r1", "status": "ok"}), encoding="utf-8")
    # the run was explained in English, whatever the console is set to now
    lay.write_config({**env.config, "prompt_lang": "en"})
    return lay, env


class _Host:
    """What the queue asks of a host: a complete config, the bus and a way to
    say something on it. The key is a placeholder: the model is a stand-in."""

    def __init__(self, env):
        backend = env.config["llm"]["backend"]
        self.cfg = load_config(env.config, {
            "llm": {"profiles": {backend: {"api_key": "stand-in"}}},
            "prompt_lang": "zh"})
        self.bus = env.bus

    def emit(self, ev):
        self.bus.emit(ev)


def _queue(lay, env, monkeypatch):
    monkeypatch.setattr(api_attacks, "solver_problem", lambda exe: None)
    monkeypatch.setattr(api_attacks, "make_runner", lambda config: Solver())
    q = Reproductions(lay.run_dir, _Host(env))
    assert q._env().config["prompt_lang"] == "en"
    real = q._env

    def with_writer():
        e = real()
        e._llm = env._llm
        return e

    q._env = with_writer
    return q


def _said(env):
    return [(e.label, e.goal, e.status) for e in env.bus.events
            if type(e).__name__ == "AttackStatus"]


def test_the_index_carries_an_asked_cell_and_the_newer_summary(tmp_path, monkeypatch):
    lay, env = _stepped(tmp_path, monkeypatch)
    waiting = [c for c in index(lay.run_dir)["cells"] if c["decision"] == "pending"]
    assert len(waiting) == 2 and all(c["reason"] == "over_limit" for c in waiting)
    q = _queue(lay, env, monkeypatch)

    async def ask_then_sum():
        q.enqueue([("shared_key_leaked", "auth_b_to_a")])
        await q.task
        q.summarize()
        await q.task

    asyncio.run(ask_then_sum())
    # the summary asked for is the newer one, so it is the one shown
    step_summary = lay.node_dir("reproduce_attacks") / "summary" / "summary.json"
    os.utime(step_summary, (1, 1))
    out = index(lay.run_dir)
    asked = next(c for c in out["cells"] if c["label"] == "shared_key_leaked")
    assert asked["manual"] and not asked["stale"] and asked["status"] == "ok"
    assert asked["decision"] == "pending" and asked["reason"] == ""
    assert asked["explanation"].startswith("_attacks/shared_key_leaked/")
    assert out["summary"]["manual"] is True
    assert "shared_key_leaked/auth_b_to_a" in out["summary"]["covered"]
    assert out["summary"]["path"] == "_attacks/summary/summary.json"


def test_the_queue_says_each_cell_and_refuses_what_cannot_be_asked(tmp_path, monkeypatch):
    lay, env = _stepped(tmp_path, monkeypatch)
    q = _queue(lay, env, monkeypatch)
    env.bus.events.clear()
    auto = next((c["label"], c["goal"]) for c in index(lay.run_dir)["cells"]
                if c["decision"] == "auto")

    async def go():
        out = q.enqueue([("shared_key_leaked", "auth_b_to_a"), auto,
                         ("shared_key_leaked", "auth_b_to_a")])
        assert q.state()["queue"] == ["shared_key_leaked|auth_b_to_a"]
        await q.task
        return out

    out = asyncio.run(go())
    assert out["queued"] == [{"scenario": "shared_key_leaked", "goal": "auth_b_to_a"}] * 2
    assert [r["goal"] for r in out["refused"]] == [auto[1]]
    assert "re-run the step" in out["refused"][0]["why"]
    assert _said(env) == [("shared_key_leaked", "auth_b_to_a", s)
                          for s in ("queued", "running", "ok")]
    assert q.state() == {"queue": [], "summarizing": False, "queue_error": ""}


def test_stopping_sends_every_cell_back_to_waiting(tmp_path, monkeypatch):
    lay, env = _stepped(tmp_path, monkeypatch)
    q = _queue(lay, env, monkeypatch)
    started = asyncio.Event()

    async def hang(env, runner, *, label, goal, emit):
        # halfway: the reproduction is written, the explanation is not
        home = env.layout.attack_dir(label, goal, manual=True)
        _write(home / "reproduction.json", {
            "goal": goal, "label": label, "status": "ok", "source": "x.pv"})
        started.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr(api_attacks, "reproduce_asked", hang)
    env.bus.events.clear()
    cells = [c for c in index(lay.run_dir)["cells"] if c["decision"] == "pending"]

    async def go():
        q.enqueue([(c["label"], c["goal"]) for c in cells])
        await started.wait()
        with pytest.raises(QueueBusy):
            q.summarize()
        return await q.stop()

    assert asyncio.run(go()) == 2
    statuses = [s for _, _, s in _said(env)]
    assert statuses == ["queued", "queued", "cancelled", "cancelled"]
    assert not q.busy and q.state()["queue"] == []
    # the cell stopped halfway is back to waiting, its attempt set aside
    first = next(c for c in index(lay.run_dir)["cells"]
                 if (c["label"], c["goal"]) == (cells[0]["label"], cells[0]["goal"]))
    assert "status" not in first and first["manual"] is False
    home = lay.attack_dir(first["label"], first["goal"], manual=True)
    assert (home / "superseded-1" / "reproduction.json").is_file()


# ── the routes ──────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    lay = _layout(tmp_path)
    home = lay.open_node("reproduce_attacks")
    _write(home / "targets.json", {"limit": 10, "ground_truth": False,
                                   "targets": [WAITING]})
    monkeypatch.setattr(server.app.state, "work_root", (tmp_path / "wr").resolve())
    monkeypatch.setattr(server.app.state.playback, "on", False)
    monkeypatch.setattr(server.app.state, "reproductions", {})
    return TestClient(server.app)


def test_the_route_answers_with_the_index(client):
    r = client.get("/api/runs/NSPK01/attacks")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cells"] == [{**WAITING, **PLAIN}]
    assert body["queue"] == [] and body["summarizing"] is False


class _Queue:
    def __init__(self, busy=False):
        self.busy, self.asked, self.summed = busy, [], 0

    def enqueue(self, cells):
        self.asked += cells
        return {"queued": [{"scenario": s, "goal": g} for s, g in cells
                           if g != "nope"],
                "refused": [{"scenario": s, "goal": g, "why": "no such cell"}
                            for s, g in cells if g == "nope"]}

    def summarize(self):
        if self.busy:
            raise QueueBusy("still working")
        self.summed += 1

    async def stop(self):
        return 3

    def state(self):
        return {"queue": [], "summarizing": False, "queue_error": ""}


def test_asking_goes_through_the_runs_queue(client, monkeypatch):
    q = _Queue()
    monkeypatch.setattr(server, "_reproductions", lambda name: q)
    r = client.post("/api/runs/NSPK01/attacks",
                    json={"cells": [{"scenario": "open", "goal": "auth_b_a"}]})
    assert r.status_code == 200, r.text
    assert q.asked == [("open", "auth_b_a")]
    # nothing that can be asked for is an answer in itself
    r = client.post("/api/runs/NSPK01/attacks",
                    json={"cells": [{"scenario": "open", "goal": "nope"}]})
    assert r.status_code == 400 and "no such cell" in r.json()["detail"]
    for bad in ({}, {"cells": []}, {"cells": [{"scenario": "open"}]},
                {"cells": "open/auth_b_a"}):
        assert client.post("/api/runs/NSPK01/attacks", json=bad).status_code == 400
    assert client.post("/api/runs/NSPK01/attacks/summary").status_code == 200
    assert q.summed == 1


def test_a_busy_queue_refuses_a_summary(client, monkeypatch):
    monkeypatch.setattr(server, "_reproductions", lambda name: _Queue(busy=True))
    r = client.post("/api/runs/NSPK01/attacks/summary")
    assert r.status_code == 409 and "still working" in r.json()["detail"]


def test_stopping_a_run_with_no_queue_stops_nothing(client):
    r = client.post("/api/runs/NSPK01/attacks/stop")
    assert r.status_code == 200 and r.json() == {"stopped": 0}


def test_asking_is_refused_while_playing_back(client, monkeypatch):
    monkeypatch.setattr(server.app.state.playback, "on", True)
    r = client.post("/api/runs/NSPK01/attacks",
                    json={"cells": [{"scenario": "open", "goal": "auth_b_a"}]})
    assert r.status_code == 409 and "playback" in r.json()["detail"]


def test_asking_is_refused_while_the_run_is_in_flight(client, monkeypatch):
    class _Busy:
        running = True
    monkeypatch.setattr(server.app.state.registry, "get", lambda name: _Busy())
    r = client.post("/api/runs/NSPK01/attacks",
                    json={"cells": [{"scenario": "open", "goal": "auth_b_a"}]})
    assert r.status_code == 409 and "in flight" in r.json()["detail"]
