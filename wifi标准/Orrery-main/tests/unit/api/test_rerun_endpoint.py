"""Tests for POST /api/runs/{name}/rerun, the console's retry at every depth.

``from_step`` is a step's identity path and a node name is its shortest form.
The endpoint resolves it through steps.resolve rather than trusting the
browser, refuses what names nothing, and hands the engine both halves.
``registry.start`` is replaced, so what is under test is everything the
endpoint does before the run begins.
"""

import json

import pytest
from fastapi.testclient import TestClient

from orrery.web import server
from orrery.services.store.layout import RunLayout

CHAIN = ("load_document", "tag_sections", "extract_principals", "extract_flow",
         "claims", "build_world", "build_root", "scenarios")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A work root with one finished-then-stopped run in it, and a registry
    that records what it was asked to start instead of starting it."""
    work = tmp_path / "wr"
    lay = RunLayout(work, "NSPK", "NSPK01")
    lay.run_dir.mkdir(parents=True)
    for name in CHAIN:
        lay.open_node(name)
    lay.open_scenario("baseline")
    lay.open_inject_family("baseline", "Secrecy")
    (lay.run_dir / "run.json").write_text(json.dumps({
        "protocol": "NSPK", "protocol_id": "NSPK", "run_name": "NSPK01",
        "protocol_dir": str(tmp_path / "corpus" / "NSPK"),
        "version": None, "subprotocol": None, "ground_truth": None,
        "assumptions": None, "properties": None, "claims": None,
        "status": "failed",
    }), encoding="utf-8")
    (tmp_path / "corpus" / "NSPK").mkdir(parents=True)

    asked: dict = {}

    def fake_start(name, host, protocol, directory, **kw):
        asked.update(name=name, protocol=protocol, **kw)
        return None

    monkeypatch.setattr(server.app.state, "work_root", work.resolve())
    # The console opens in playback mode, which refuses re-entry as a write.
    # This file tests the live path, so it turns playback off explicitly.
    monkeypatch.setattr(server.app.state.playback, "on", False)
    monkeypatch.setattr(server.app.state.registry, "start", fake_start)
    c = TestClient(server.app)
    c.asked = asked
    return c


def _post(c, step):
    return c.post("/api/runs/NSPK01/rerun", json={"from_step": step})


def test_a_node_resolves_to_itself(client):
    r = _post(client, "scenarios")
    assert r.status_code == 200, r.text
    assert r.json() == {"name": "NSPK01", "from_node": "scenarios",
                        "from_step": "scenarios", "interrupted": False}
    assert client.asked["from_node"] == "scenarios"
    assert client.asked["from_step"] == "scenarios"


def test_a_step_deep_inside_resolves_to_the_node_that_owns_it(client):
    """The browser sends the row it drew, numbers and all, and gets back both
    the node the engine re-enters at and the numberless address it compares
    against. Which node that is, is not the browser's to compute."""
    r = _post(client, "08_scenarios/00_baseline/inject/00_Secrecy")
    assert r.status_code == 200, r.text
    assert r.json()["from_node"] == "scenarios"
    assert r.json()["from_step"] == "scenarios/baseline/inject/Secrecy"


@pytest.mark.parametrize("step,says", [
    ("", "from_step is required"),
    ("nonsense", "does not start with a pipeline step"),
    ("scenarios/nope", "which this run does not have"),
    ("scenarios/baseline/inject/Secrecy/basic", "not a re-workable step"),
])
def test_an_address_that_names_nothing_is_refused_before_anything_starts(
        client, step, says, monkeypatch):
    """Refused before the run in flight is touched: a mistyped address must
    not cost the work being bought."""
    stopped = []

    async def watched_stop(name, *, timeout=None):
        stopped.append(name)
        return True

    monkeypatch.setattr(client.app.state.registry, "stop", watched_stop)
    r = _post(client, step)
    assert r.status_code == 400 and says in r.json()["detail"]
    assert client.asked == {}
    assert stopped == []


def test_a_run_in_flight_is_stopped_rather_than_refused(client, monkeypatch):
    """A retry on a live run stops it first, and the order is what is asserted:
    stopped before started. Two executions in one run directory is the state the
    store assumes cannot happen."""
    order = []

    async def fake_stop(name, *, timeout=None):
        order.append(f"stopped {name}")
        return True

    real_start = client.app.state.registry.start

    def watched_start(*a, **kw):
        order.append("started")
        return real_start(*a, **kw)

    monkeypatch.setattr(client.app.state.registry, "stop", fake_stop)
    monkeypatch.setattr(client.app.state.registry, "start", watched_start)

    r = _post(client, "scenarios")
    assert r.status_code == 200, r.text
    assert r.json()["interrupted"] is True
    assert order == ["stopped NSPK01", "started"]


def test_a_run_that_is_not_in_flight_is_not_reported_as_interrupted(client):
    """The reply says whether it had to stop anything, so the page can say so
    too rather than implying every retry killed something."""
    assert _post(client, "scenarios").json()["interrupted"] is False


def test_a_run_that_will_not_stop_is_reported_rather_than_waited_on(client,
                                                                    monkeypatch):
    """A stop that times out becomes a 409 saying so, rather than a request that
    hangs and hides every other retry on the page behind it."""
    async def wont_stop(name, *, timeout=None):
        raise TimeoutError(f"run {name!r} was asked to stop and has not "
                           f"finished unwinding after {timeout:g}s")

    monkeypatch.setattr(client.app.state.registry, "stop", wont_stop)
    r = _post(client, "scenarios")
    assert r.status_code == 409
    assert "has not finished unwinding" in r.json()["detail"]
    assert "Ask again in a moment" in r.json()["detail"]
    assert client.asked == {}          # and nothing was started beside it


def test_the_reply_is_json_on_every_path(client):
    """Every path answers JSON, refusals included: the console runs the body
    through JSON.parse whatever the status is."""
    for step in ("scenarios", "nonsense"):
        r = _post(client, step)
        assert r.headers["content-type"].startswith("application/json")
        assert isinstance(r.json(), dict)


def _asked(tmp_path, **fields) -> None:
    """Rewrite the run's record, so a test can say what this run was asked."""
    p = tmp_path / "wr" / "NSPK" / "NSPK01" / "run.json"
    p.write_text(json.dumps({**json.loads(p.read_text(encoding="utf-8")),
                             **fields}), encoding="utf-8")


def test_the_documents_a_run_was_handed_come_back(client, tmp_path):
    """A run started on a reader's own file, re-entered.

    load_document is always_run, so every re-entry rebuilds the document set.
    Dropped here, the re-run instead goes looking for a corpus layout under a
    folder that never had one — the reader's own — and a run that had started
    perfectly well dies at node 1.
    """
    doc = tmp_path / "Desktop" / "NSPK.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("# NSPK\n", encoding="utf-8")
    _asked(tmp_path, documents={"main": str(doc), "refs": []})

    assert _post(client, "scenarios").status_code == 200
    assert client.asked["documents"] == {"main": str(doc), "refs": []}


def test_where_the_run_was_told_to_stop_comes_back_too(client, tmp_path):
    """Both ends of the question, not just the near one: a run asked to stop
    after the flow model is re-entered as that same run, not as one that walks
    the whole table buying every node it was told to stop before."""
    _asked(tmp_path, to_node="extract_flow")

    assert _post(client, "extract_flow").status_code == 200
    assert client.asked["to_node"] == "extract_flow"


def test_a_recorded_input_that_no_longer_resolves_is_refused(client, tmp_path):
    """A corpus that moved is an answer, not a None. Silently dropping the
    input would turn a run that was handed its mother model into one that
    extracts its own — the same run name, a different measurement."""
    _asked(tmp_path, flow=str(tmp_path / "moved" / "flow.pv"),
           principals=str(tmp_path / "moved" / "principals.json"))

    r = _post(client, "scenarios")
    assert r.status_code == 400
    assert "does not resolve" in r.json()["detail"]
    assert client.asked == {}
