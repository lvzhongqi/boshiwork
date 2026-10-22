"""The runner mechanism: ordering, skipping and verifying on re-entry, archiving
on a re-run, and stopping on failure. Stub nodes, no LLM."""

import asyncio

import pytest
import yaml

from orrery.nodes.base import CheckFailed, Node, NodeError
from orrery.pipeline import main
from orrery.pipeline.main import Run
from orrery.services.store.atomic import write_text


def _overrides(tmp_path):
    return {
        "llm": {"backend": "stub",
                "profiles": {"stub": {"api_key": "k", "model": "x"}}},
        "proverif": {"executable": "/bin/true"},
        "paths": {"work_root": str(tmp_path / "wr")},
    }


class MemNode(Node):
    name = "load_document"
    always_run = True

    def is_done(self, env):
        return True

    async def run(self, env):
        env.doc_set = "fake document set"


class ProductNode(Node):
    always_run = False

    def __init__(self, name, log):
        self.name = name
        self.log = log
        self.calls = 0

    def _path(self, env):
        return env.layout.node_dir(self.name) / "out.txt"

    def is_done(self, env):
        return env.layout.has(self.name, "out.txt")

    async def run(self, env):
        self.calls += 1
        self.log.append(self.name)
        write_text(self._path(env), f"{self.name} call{self.calls}")


class FailNode(ProductNode):
    async def run(self, env):
        raise NodeError(f"{self.name}: failed on purpose")


class ParallelProductNode(ProductNode):
    def __init__(self, name, log, entered, both_entered):
        super().__init__(name, log)
        self.entered = entered
        self.both_entered = both_entered

    async def run(self, env):
        self.entered.append(self.name)
        if len(self.entered) == 2:
            self.both_entered.set()
        # both nodes have to be in flight at once, so a serial runner would
        # time out waiting here
        await asyncio.wait_for(self.both_entered.wait(), timeout=1)
        await super().run(env)


class FanOutFailNode(ProductNode):
    """A composite step in miniature: several branches at once, one of them
    failing. Each branch names itself, so the failure carries an address."""

    async def run(self, env):
        from orrery.services.concurrency import at, run_capped

        async def ok():
            return 1

        async def boom():
            raise NodeError("repair rounds exhausted")

        await run_capped([lambda: at("a/one", ok()),
                          lambda: at("a/two/inject/Secrecy", boom())],
                         limit=2)


class CheckFailNode(ProductNode):
    """A node that runs to the end, writes its product, and whose check then
    says no."""

    async def run(self, env):
        await super().run(env)
        raise CheckFailed(f"{self.name}: does not match ground truth")


def test_sequential_and_run_json(tmp_path):
    log = []
    table = [MemNode(), ProductNode("a", log), ProductNode("b", log)]
    r = asyncio.run(Run("P", tmp_path, _overrides(tmp_path), table=table).start())
    assert r.status == "ok" and log == ["a", "b"]
    assert r.node_statuses == {"load_document": "ok", "a": "ok", "b": "ok"}
    assert (r.run_dir / "run.json").exists()
    saved_config = yaml.safe_load(
        (r.run_dir / "config.yaml").read_text(encoding="utf-8"))
    assert saved_config["llm"]["api_key"] == "********"
    assert saved_config["llm"]["profiles"]["stub"]["api_key"] == "********"
    assert "url" not in saved_config["llm"]
    assert "url" not in saved_config["llm"]["profiles"]["stub"]
    assert saved_config["llm"]["model"] == "x"


def test_assumptions_and_properties_run_in_one_task_group(tmp_path):
    async def go():
        log, entered, both_entered = [], [], asyncio.Event()
        table = [
            MemNode(),
            ParallelProductNode(
                "extract_assumptions", log, entered, both_entered),
            ParallelProductNode(
                "extract_properties", log, entered, both_entered),
            ProductNode("extract_claims", log),
        ]
        result = await Run(
            "P", tmp_path, _overrides(tmp_path), table=table).start()
        return result, log, entered

    result, log, entered = asyncio.run(go())
    assert result.status == "ok"
    assert entered == ["extract_assumptions", "extract_properties"]
    assert set(log[:2]) == {"extract_assumptions", "extract_properties"}
    assert log[2] == "extract_claims"


def test_run_identity_uses_the_only_subprotocol_by_default(tmp_path):
    (tmp_path / "subprotocols" / "AKA").mkdir(parents=True)
    run = Run("P", tmp_path, _overrides(tmp_path), version="v1",
              table=[MemNode()])
    assert run.subprotocol == "AKA"
    assert run.protocol_id == "P-v1-AKA"


def test_reentry_skips_done_and_validates_upstream(tmp_path):
    log = []
    table = [MemNode(), ProductNode("a", log), ProductNode("b", log)]
    ov = _overrides(tmp_path)
    first = asyncio.run(Run("P", tmp_path, ov, table=table).start())
    log.clear()
    r = asyncio.run(Run("P", tmp_path, ov, table=table, from_node="b",
                        run_name=first.run_dir.name).start())
    assert log == ["b"]                                # a did not re-run
    assert r.node_statuses["a"] == "skipped"
    # b ran into a directory of its own; the first attempt stays where it was
    assert [d.name for d in sorted(r.run_dir.iterdir()) if d.is_dir()] == [
        "01_a", "02_b", "03_b"]
    assert "call1" in (r.run_dir / "02_b" / "out.txt").read_text()
    assert "call2" in (r.run_dir / "03_b" / "out.txt").read_text()


def test_reentry_with_missing_upstream_is_loud(tmp_path):
    table = [MemNode(), ProductNode("a", []), ProductNode("b", [])]
    with pytest.raises(RuntimeError, match="no artifact"):
        asyncio.run(Run("P", tmp_path, _overrides(tmp_path), run_name="R",
                        table=table, from_node="b").start())


def test_a_reentry_aimed_below_a_node_keeps_the_directory_it_has(tmp_path):
    """A re-work appends a directory at the level it was aimed at and nowhere
    else. A node the pipeline only passes through on its way to something
    inside it carries on in the directory it already has."""
    log = []
    table = [MemNode(), ProductNode("a", log), ProductNode("b", log)]
    ov = _overrides(tmp_path)
    first = asyncio.run(Run("P", tmp_path, ov, table=table).start())
    r = asyncio.run(Run("P", tmp_path, ov, table=table, from_node="b",
                        from_step="b/inner", run_name=first.run_dir.name).start())
    assert r.status == "ok"
    assert [d.name for d in sorted(r.run_dir.iterdir()) if d.is_dir()] == [
        "01_a", "02_b"]                       # no 03_b: b carried on in its own


def test_reentry_without_a_name_is_refused(tmp_path):
    # an allocated name is a fresh directory, so re-entering it would find
    # nothing to skip
    table = [MemNode(), ProductNode("a", []), ProductNode("b", [])]
    with pytest.raises(ValueError, match="from_node needs run_name"):
        Run("P", tmp_path, _overrides(tmp_path), table=table, from_node="b")


def test_failure_stops_and_records(tmp_path):
    log = []
    table = [MemNode(), FailNode("a", log), ProductNode("b", log)]
    r = asyncio.run(Run("P", tmp_path, _overrides(tmp_path), table=table).start())
    assert r.status == "failed" and r.failed_node == "a"
    assert "b" not in r.node_statuses                  # nothing after it ran
    import json
    assert json.loads((r.run_dir / "run.json").read_text())["status"] == "failed"


def test_a_failure_inside_a_fan_out_says_which_branch(tmp_path):
    """The run stops at the node, and the ledger names which branch failed, as
    the branch's identity path — the same address a fix is aimed by."""
    import json
    log = []
    table = [MemNode(), FanOutFailNode("a", log), ProductNode("b", log)]
    r = asyncio.run(Run("P", tmp_path, _overrides(tmp_path), table=table).start())
    assert r.status == "failed" and r.failed_node == "a"
    events = [json.loads(x) for x in
              (r.run_dir / "events.jsonl").read_text().splitlines()]
    failed = [e for e in events if e["t"] == "run_failed"][0]
    assert failed["data"]["where"] == "a/two/inject/Secrecy"
    assert failed["data"]["reason"] == "repair rounds exhausted"


def test_a_failed_check_is_not_a_failed_node(tmp_path):
    # the node ran and wrote its product; its check says no. That stops the run
    # too, but is recorded as its own outcome, artifacts included.
    import json
    log = []
    table = [MemNode(), CheckFailNode("a", log), ProductNode("b", log)]
    r = asyncio.run(Run("P", tmp_path, _overrides(tmp_path), table=table).start())
    assert r.status == "check_failed" and r.failed_node == "a"
    assert r.node_statuses["a"] == "check_failed" and "b" not in r.node_statuses
    assert json.loads((r.run_dir / "run.json").read_text())["status"] == "check_failed"
    events = [json.loads(x) for x in
              (r.run_dir / "events.jsonl").read_text().splitlines()]
    done = [e for e in events if e["t"] == "node_finished" and e["node"] == "a"]
    assert done[0]["data"]["status"] == "check_failed" and done[0]["data"]["artifacts"]
    assert [e for e in events
            if e["t"] == "run_failed"][0]["data"]["kind"] == "check"


class ExplainNode(ProductNode):
    """A step that explains the run's answers, so it runs after a failed
    check too."""
    runs_after_check_failure = True


class ExplainFailNode(ExplainNode):
    async def run(self, env):
        raise NodeError(f"{self.name}: could not explain")


class ExplainCrashNode(ExplainNode):
    async def run(self, env):
        raise ValueError("model service answered 503")


def _events(run_dir):
    import json
    return [json.loads(x) for x in
            (run_dir / "events.jsonl").read_text().splitlines()]


def test_an_explaining_step_runs_after_a_failed_check_like_any_step(tmp_path):
    """It used to be called straight from the failure handler: no stage of its
    own, no approval gate, no events of its own beyond two. Now it goes through
    the loop, and the run still closes as the failed check."""
    log = []
    table = [MemNode(), CheckFailNode("a", log), ProductNode("b", log),
             ExplainNode("explain", log)]
    r = asyncio.run(Run("P", tmp_path, _overrides(tmp_path), table=table).start())
    assert log == ["a", "explain"]
    assert r.status == "check_failed" and r.failed_node == "a"
    assert r.failure == "a: does not match ground truth"
    assert r.node_statuses == {"load_document": "ok", "a": "check_failed",
                               "explain": "ok"}
    # its own stage directory, which it could not have written into before
    assert [p.name for p in r.run_dir.glob("*_explain")]
    assert next(r.run_dir.glob("*_explain")).joinpath("out.txt").is_file()
    events = _events(r.run_dir)
    kinds = [(e["t"], e["node"]) for e in events
             if e["t"] in ("node_started", "node_finished", "run_failed",
                           "run_finished")]
    assert kinds[-4:] == [("node_finished", "a"), ("node_started", "explain"),
                          ("node_finished", "explain"), ("run_failed", None)]
    said = [e["data"]["text"] for e in events
            if e["t"] == "node_progress" and e["node"] == "a"]
    assert said[-1] == "did not pass: a: does not match ground truth"
    failed = [e for e in events if e["t"] == "run_failed"][0]["data"]
    assert failed["kind"] == "check"
    assert failed["reason"] == "a: does not match ground truth"


def test_an_explaining_step_that_fails_fails_the_run_and_keeps_the_check(tmp_path):
    log = []
    table = [MemNode(), CheckFailNode("a", log), ExplainFailNode("explain", log)]
    r = asyncio.run(Run("P", tmp_path, _overrides(tmp_path), table=table).start())
    assert r.status == "failed" and r.failed_node == "explain"
    assert r.node_statuses["a"] == "check_failed"
    assert r.node_statuses["explain"] == "failed"
    assert r.failure == ("explain: could not explain (earlier, a did not pass: "
                         "a: does not match ground truth)")
    failed = [e for e in _events(r.run_dir) if e["t"] == "run_failed"]
    assert len(failed) == 1 and failed[0]["data"]["kind"] == "crash"
    assert "a did not pass" in failed[0]["data"]["reason"]


def test_an_explaining_step_that_crashes_names_the_check_too(tmp_path):
    log = []
    table = [MemNode(), CheckFailNode("a", log), ExplainCrashNode("explain", log)]
    run = Run("P", tmp_path, _overrides(tmp_path), table=table)
    with pytest.raises(ValueError, match="503"):
        asyncio.run(run.start())
    failed = [e for e in _events(run.run_dir) if e["t"] == "run_failed"]
    assert len(failed) == 1
    assert "model service answered 503" in failed[0]["data"]["reason"]
    assert "earlier, a did not pass" in failed[0]["data"]["reason"]


def test_an_explaining_step_runs_after_a_passing_check_too(tmp_path):
    log = []
    table = [MemNode(), ProductNode("a", log), ExplainNode("explain", log)]
    r = asyncio.run(Run("P", tmp_path, _overrides(tmp_path), table=table).start())
    assert r.status == "ok" and log == ["a", "explain"]


def test_repeated_runs_stack_up_and_latest_follows(tmp_path):
    """A run directory is immutable: running again allocates the next name and
    leaves the earlier result in place, with `latest` pointing at the newest."""
    ov, log = _overrides(tmp_path), []
    table = [MemNode(), ProductNode("a", log), ProductNode("b", log)]
    r1 = asyncio.run(Run("P", tmp_path, ov, table=table).start())
    r2 = asyncio.run(Run("P", tmp_path, ov, table=table).start())

    assert r1.run_dir.name.endswith("01") and r2.run_dir.name.endswith("02")
    assert r1.run_dir.exists()                        # the first result survived
    assert (r1.run_dir / "01_a" / "out.txt").read_text() == "a call1"
    latest = r1.run_dir.parent / "latest"
    assert latest.is_symlink() and latest.resolve() == r2.run_dir.resolve()
    # `latest` is a pointer, not a run, so the allocator never hands out its name
    assert "latest" not in {r1.run_dir.name, r2.run_dir.name}


def test_an_existing_named_run_is_never_overwritten(tmp_path):
    ov, log = _overrides(tmp_path), []
    table = [MemNode(), ProductNode("a", log), ProductNode("b", log)]
    r1 = asyncio.run(Run("P", tmp_path, ov, run_name="R", table=table).start())
    old = (r1.run_dir / "01_a" / "out.txt").read_text()

    with pytest.raises(FileExistsError, match="never overwritten"):
        asyncio.run(Run("P", tmp_path, ov, run_name="R", table=table).start())
    assert (r1.run_dir / "01_a" / "out.txt").read_text() == old

    # from_node re-entry is the way back into an existing run: b runs again
    # into a directory of its own, while a is left untouched
    r3 = asyncio.run(Run("P", tmp_path, ov, run_name="R", table=table,
                         from_node="b").start())
    assert (r3.run_dir / "01_a" / "out.txt").read_text() == old
    assert (r3.run_dir / "02_b" / "out.txt").read_text() == "b call1"
    assert (r3.run_dir / "03_b" / "out.txt").read_text() == "b call2"


def test_latest_is_a_reserved_run_name(tmp_path):
    with pytest.raises(ValueError, match="reserved name"):
        Run("P", tmp_path, _overrides(tmp_path), run_name="latest", table=[MemNode()])


# --- fork: a second run seeded from the first, both kept side by side ---


def test_fork_copies_upstream_and_leaves_the_source_alone(tmp_path):
    ov, log = _overrides(tmp_path), []
    first = [MemNode(), ProductNode("a", log), ProductNode("b", log)]
    asyncio.run(Run("P", tmp_path, ov, run_name="R01", table=first).start())

    log2 = []
    second = [MemNode(), ProductNode("a", log2), ProductNode("b", log2)]
    r = asyncio.run(Run("P", tmp_path, ov, run_name="R02", table=second,
                        from_node="b", fork_from="R01").start())
    # a came from the fork and was not re-run; only b ran in the new run
    assert log2 == ["b"]
    assert r.node_statuses["a"] == "skipped" and r.node_statuses["b"] == "ok"
    assert (r.run_dir / "01_a" / "out.txt").read_text() == "a call1"
    # the source run is untouched: its own b is still the one it produced, and
    # the fork's copy kept the number it had, so the two listings line up
    src = tmp_path / "wr" / "P" / "R01"
    assert (src / "02_b" / "out.txt").read_text() == "b call1"
    assert [d.name for d in sorted(src.iterdir()) if d.is_dir()] == ["01_a", "02_b"]
    assert [d.name for d in sorted(r.run_dir.iterdir()) if d.is_dir()] == [
        "01_a", "02_b"]         # a copied in at its own number, b ran after it
    import json
    assert json.loads((r.run_dir / "run.json").read_text())["forked_from"] == "R01"


def test_fork_needs_a_reentry_point_and_a_free_name(tmp_path):
    ov, log = _overrides(tmp_path), []
    table = [MemNode(), ProductNode("a", log), ProductNode("b", log)]
    asyncio.run(Run("P", tmp_path, ov, run_name="R01", table=table).start())

    with pytest.raises(ValueError, match="needs from_node"):
        Run("P", tmp_path, ov, run_name="R02", table=table, fork_from="R01")
    with pytest.raises(FileNotFoundError, match="fork source"):
        asyncio.run(Run("P", tmp_path, ov, run_name="R03", table=table,
                        from_node="b", fork_from="nope").start())
    # forking onto a name that already exists would merge two runs silently
    with pytest.raises(FileExistsError, match="already exists"):
        asyncio.run(Run("P", tmp_path, ov, run_name="R01", table=table,
                        from_node="b", fork_from="R01").start())


def test_to_node_stops_after_it_and_still_closes_the_run(tmp_path):
    """A partial run is the same orchestration with the table's tail
    truncated, and it still closes the run out."""
    log = []
    table = [MemNode(), ProductNode("a", log), ProductNode("b", log)]
    r = asyncio.run(Run("P", tmp_path, _overrides(tmp_path), table=table,
                        to_node="a").start())
    assert r.status == "ok" and log == ["a"]           # b never ran
    assert "b" not in r.node_statuses
    import json
    assert json.loads((r.run_dir / "run.json").read_text())["status"] == "ok"


def test_to_node_composes_with_from_node_and_rejects_an_empty_span(tmp_path):
    log = []
    table = [MemNode(), ProductNode("a", log), ProductNode("b", log)]
    ov = _overrides(tmp_path)
    first = asyncio.run(Run("P", tmp_path, ov, table=table, to_node="a").start())
    log.clear()
    # re-enter the same run and run only b on top of a's artifact
    r = asyncio.run(Run("P", tmp_path, ov, table=table, from_node="b", to_node="b",
                        run_name=first.run_dir.name).start())
    assert r.status == "ok" and log == ["b"]
    with pytest.raises(ValueError, match="no node would run"):
        Run("P", tmp_path, ov, table=table, run_name="X", from_node="b", to_node="a")
    with pytest.raises(ValueError, match="not in the node table"):
        Run("P", tmp_path, ov, table=table, to_node="nonsense")


# ── where a failure happened ────────────────────────────────────────────────
# A fan-out step's own name is not an address when eight scenarios run at once.
# The branch tags the exception on its way out (services/concurrency.at), and
# these tests read the tag back off.

class _Boom(RuntimeError):
    pass


def _tagged(step: str, msg: str = "no closing period found") -> _Boom:
    e = _Boom(msg)
    setattr(e, "orrery_step", step)
    return e


def test_one_branch_failing_gives_the_run_a_place():
    e = _tagged("scenarios/baseline/inject/Secrecy")
    assert main._origin(e) == "scenarios/baseline/inject/Secrecy"
    # the place is a field of its own, so the reason stays a plain reason
    assert main._describe(e) == "_Boom: no closing period found"


def test_a_group_from_one_place_still_has_that_place():
    """Two cells of the same family failing the same way is one location."""
    where = "scenarios/baseline/inject/Secrecy"
    eg = BaseExceptionGroup("tg", [_tagged(where), _tagged(where)])
    assert main._origin(eg) == where
    assert "at " not in main._describe(eg)          # one field holds it
    assert "[x2]" in main._describe(eg)


def test_siblings_failing_in_different_places_are_named_in_the_reason():
    """No one path is the location, so the field stays empty and the message
    carries every place instead."""
    eg = BaseExceptionGroup("tg", [_tagged("scenarios/a", "x"),
                                   _tagged("scenarios/b", "y")])
    assert main._origin(eg) == ""
    said = main._describe(eg)
    assert "at scenarios/a" in said and "at scenarios/b" in said


def test_a_failure_on_the_serial_spine_claims_no_place():
    """Nothing tags a node that is not a fan-out; the node name in the envelope
    is already the whole address there."""
    assert main._origin(_Boom("x")) == ""


def test_both_readers_failing_is_recorded_for_both(tmp_path):
    """The two document readers run side by side. When both fail, the ledger
    closes out both nodes: the console draws a step off node_finished, so a
    node that failed without one stays "running" for ever."""
    import json
    log = []
    table = [MemNode(), FailNode("extract_assumptions", log),
             FailNode("extract_properties", log), ProductNode("extract_claims", log)]
    r = asyncio.run(Run("P", tmp_path, _overrides(tmp_path), table=table).start())
    assert r.status == "failed"
    assert r.node_statuses["extract_assumptions"] == "failed"
    assert r.node_statuses["extract_properties"] == "failed"
    assert "extract_assumptions" in r.failure and "extract_properties" in r.failure
    events = [json.loads(x) for x in
              (r.run_dir / "events.jsonl").read_text().splitlines()]
    done = {e["node"]: e["data"]["status"] for e in events
            if e["t"] == "node_finished"}
    assert done["extract_assumptions"] == "failed"
    assert done["extract_properties"] == "failed"
    assert len([e for e in events if e["t"] == "run_failed"]) == 1


class ScenarioTreeNode(ProductNode):
    """A stage with work under it, the shape the scenario stage has: its
    artifact lives in a scenario directory that only the index can find."""

    def is_done(self, env):
        d = env.layout.find_scenario_dir("s1")
        return d is not None and (d / "verdict.json").exists()

    async def run(self, env):
        self.calls += 1
        self.log.append(self.name)
        env.layout.open_node(self.name)
        d = env.layout.open_scenario("s1")
        write_text(d / "verdict.json", "{}")


def test_fork_brings_the_index_rows_under_a_stage_along(tmp_path):
    """A stage copied by a fork carries its subtree: the scenario, apply point
    and goal family rows are what make the copied directories findable, and a
    fork re-entering after the stage finds its work only through them."""
    ov, log = _overrides(tmp_path), []
    first = [MemNode(), ProductNode("a", log), ScenarioTreeNode("scenarios", log),
             ProductNode("aggregate", log)]
    asyncio.run(Run("P", tmp_path, ov, run_name="R01", table=first).start())

    log2 = []
    second = [MemNode(), ProductNode("a", log2), ScenarioTreeNode("scenarios", log2),
              ProductNode("aggregate", log2)]
    r = asyncio.run(Run("P", tmp_path, ov, run_name="R02", table=second,
                        from_node="aggregate", fork_from="R01").start())
    assert r.status == "ok"
    assert log2 == ["aggregate"]                      # the stage was found, not re-run
    assert r.node_statuses["scenarios"] == "skipped"
    from orrery.services.store import stages as stage_index
    assert not stage_index.verify(r.run_dir, stage_index.load(r.run_dir))


def test_an_unknown_reentry_point_is_refused_before_anything_is_written(tmp_path):
    """A misspelt from_node is caught by the constructor: start() writes the
    run's config, moves the latest pointer and binds the ledger before the
    table is walked, and a name that is not in the table must not get that
    far."""
    ov, log = _overrides(tmp_path), []
    table = [MemNode(), ProductNode("a", log), ProductNode("b", log)]
    first = asyncio.run(Run("P", tmp_path, ov, table=table).start())
    with pytest.raises(ValueError, match="not in the node table"):
        Run("P", tmp_path, ov, table=table, from_node="bee",
            run_name=first.run_dir.name)


def test_a_run_that_needs_the_solver_refuses_to_start_without_one(tmp_path):
    """The solver is first called after the flow model has been paid for.
    Checked at construction instead: nothing is written, nothing is spent,
    and the message names the setting rather than a missing file."""
    from orrery.pipeline.config import MissingConfigError
    ov = {**_overrides(tmp_path),
          "proverif": {"executable": str(tmp_path / "proverif2.05")}}
    (tmp_path / "proverif2.05").mkdir()           # the directory, not the binary in it
    with pytest.raises(MissingConfigError, match=r"proverif\.executable.*is a directory"):
        Run("P", tmp_path, ov)
    assert not (tmp_path / "wr").exists()
    # a run that stops before any solving step does not need one
    Run("P", tmp_path, ov, to_node="extract_principals")
