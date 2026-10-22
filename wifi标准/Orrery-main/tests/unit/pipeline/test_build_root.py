"""build_root and build_world as steps of their own: where they sit in the
table, their completion contract, and the free path where no assumption changes
the text.

The paid path goes through the same apply_points as the scenario stage and is
covered with that; only fixed data points are checked here, since they take a
separate batch engine.
"""

import asyncio
import json

import pytest

from orrery.version import VOCAB_VERSION
from orrery.nodes.base import NodeError, RunEnv
from orrery.nodes.root.node import BuildRootNode
from orrery.pipeline.table import build_table, index_of
from orrery.services.store.layout import RunLayout


def _env(tmp_path, *steps):
    """A run with the pipeline's steps plus the named extras already opened. A
    step has no directory until the runner opens it, which is what this stands
    in for."""
    lay = RunLayout(tmp_path, "NSPK", "run1")
    lay.run_dir.mkdir(parents=True, exist_ok=True)
    for s in ("extract_principals", "extract_flow", "extract_claims",
              "build_world", "build_root", "scenarios", *steps):
        lay.open_node(s)
    return RunEnv(protocol_dir=tmp_path / "NSPK", layout=lay, config={})


def _declare_world(env):
    """The world declaration build_world reads, out of extract_claims'
    assumptions.json. Empty here: every world axis at its flow state, which is
    NSPK's shape."""
    _write(env.layout.node_dir("extract_claims") / "assumptions.json",
           json.dumps({"vocab_version": VOCAB_VERSION,
                       "world": [], "fixed": [], "variable": []}))
    _write(env.layout.node_dir("extract_principals") / "principals.json",
           json.dumps({"principals": [{"name": "A"}, {"name": "B"}]}))


def _write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_the_root_model_sits_between_claims_and_the_scenarios(tmp_path):
    """build_root reads the claims and every scenario reads build_root, so it
    is one row between them. Re-entry, supersession and fix pricing all key on
    that position."""
    table = build_table()
    assert index_of(table, "extract_claims") < index_of(table, "build_root") \
        < index_of(table, "scenarios")


def test_done_is_the_root_model_on_disk(tmp_path):
    """is_done is the presence of root.pv, which is how a re-entry tells a run
    that built the root model from one that never got there."""
    env = _env(tmp_path)
    node = BuildRootNode()
    assert not node.is_done(env)
    _write(env.layout.root_pv, "process 0\n")
    assert node.is_done(env)


def test_no_fixed_assumption_still_writes_the_root_model(tmp_path):
    """A protocol with no fixed assumption still gets a root model: the world
    model verbatim. The file always exists, so no downstream reader has to
    handle its absence."""
    env = _env(tmp_path)
    _declare_world(env)
    _write(env.layout.world_pv, "process 0 (* world *)\n")
    _write(env.layout.node_dir("extract_claims") / "assumptions.json",
           json.dumps({"vocab_version": "2.2.0", "world": [], "fixed": [], "variable": []}))

    asyncio.run(BuildRootNode().run(env))

    assert env.layout.root_pv.read_text(encoding="utf-8") == "process 0 (* world *)\n"
    assert "world model verbatim" in env.layout.root_notes.read_text(encoding="utf-8")


def test_the_world_model_sits_between_claims_and_build_root(tmp_path):
    table = build_table()
    assert index_of(table, "extract_claims") < index_of(table, "build_world") \
        < index_of(table, "build_root")


def test_a_default_world_still_writes_the_world_model(tmp_path):
    """NSPK's shape: an empty world section still writes the world model, the
    flow model verbatim, so the file always exists."""
    from orrery.nodes.world.node import BuildWorldNode
    env = _env(tmp_path)
    _declare_world(env)
    _write(env.layout.flow_pv, "process 0 (* flow *)\n")

    asyncio.run(BuildWorldNode().run(env))

    assert env.layout.world_pv.read_text(encoding="utf-8") == "process 0 (* flow *)\n"
    assert "flow model verbatim" in env.layout.world_notes.read_text(encoding="utf-8")


def test_a_missing_world_model_is_named_as_such(tmp_path):
    env = _env(tmp_path)
    _write(env.layout.node_dir("extract_claims") / "assumptions.json",
           json.dumps({"vocab_version": "2.2.0", "world": [], "fixed": [], "variable": []}))
    with pytest.raises(NodeError, match="world model does not exist"):
        asyncio.run(BuildRootNode().run(env))


def test_a_missing_flow_is_named_as_such(tmp_path):
    """A missing upstream product is named as such, rather than surfacing as a
    FileNotFoundError from inside an apply session."""
    from orrery.nodes.world.node import BuildWorldNode
    env = _env(tmp_path)
    with pytest.raises(NodeError, match="flow model does not exist"):
        asyncio.run(BuildWorldNode().run(env))


def test_root_routes_fixed_data_through_the_batch_engine(tmp_path, monkeypatch):
    """Fixed points split by axis: data points go to the batch engine in one
    call, everything else through the ordinary apply_points chain first."""
    env = _env(tmp_path)
    env.config = {
        "proverif": {"executable": "/bin/true", "timeout_s": 1},
    }
    _write(env.layout.world_pv, "process 0\n")
    _write(
        env.layout.node_dir("extract_claims") / "assumptions.json",
        json.dumps({
            "vocab_version": VOCAB_VERSION,
            "world": [],
            "fixed": [
                {"id": "reuse_k", "axis": "key_reuse",
                 "target": {"of": "K"}, "subtype": "observed"},
                {"id": "public_a", "axis": "data",
                 "target": {"of": "A"}, "subtype": "disclosed"},
                {"id": "public_b", "axis": "data",
                 "target": {"of": "B"}, "subtype": "disclosed"},
            ],
            "variable": [],
        }),
    )
    seen = []

    async def ordinary(_env, points, _runner, pv, _notes, **_kwargs):
        seen.append(("ordinary", [point.ref_id for point in points]))
        return pv + "(* ordinary *)\n"

    async def batched(_env, points, _runner, pv, _notes, **_kwargs):
        seen.append(("batch", [point.ref_id for point in points]))
        return pv + "(* batch *)\n"

    monkeypatch.setattr("orrery.nodes.root.node.apply_points", ordinary)
    monkeypatch.setattr("orrery.nodes.root.node.apply_fixed_data_points", batched)

    asyncio.run(BuildRootNode().run(env))

    assert seen == [
        ("ordinary", ["reuse_k"]),
        ("batch", ["public_a", "public_b"]),
    ]
    assert "(* batch *)" in env.layout.root_pv.read_text(encoding="utf-8")
