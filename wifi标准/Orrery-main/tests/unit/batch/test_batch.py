import json
import os
import signal
import asyncio
import subprocess
import sys
from pathlib import Path

import yaml
import pytest

from orrery.pipeline.config import MissingConfigError

from experiments.batch.common import (
    CATALOG_PATH, Protocol, Runner, Suite, _catalog, is_pending, is_running,
    load_suite, preflight, protocol_claim, read_state, report_status, run_many,
    write_state,
)
from experiments.batches import BATCHES
from experiments.batch import baseline as baseline_batch
from experiments.batch.baseline import build as build_baseline
from experiments.batch.orrery import (
    artifact_status, build as build_orrery, child as child_orrery, line_hook,
)


def _runner(build, line_hook=lambda *args: None,
            artifact_status=artifact_status) -> Runner:
    """A Runner for a test that cares about one of its hooks."""
    def no_child(suite, protocol, run_name):
        raise AssertionError("this test does not spawn a child")
    return Runner(build, no_child, line_hook, artifact_status)


def _suite(tmp_path: Path) -> Suite:
    return Suite(
        name="main",
        config=tmp_path / "config.yaml",
        overrides=BATCHES["main"],
        work_root=tmp_path / "runs",
        lib_root=tmp_path / "corpus",
        max_runs=2,
        protocols=(),
    )


def _config(tmp_path: Path, **extra) -> Path:
    """The batch runner's one config file, written fresh rather than taken off
    the machine running the tests."""
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(
        {"paths": {"work_root": str(tmp_path / "runs"),
                   "lib_root": str(tmp_path / "lib")},
         "max_runs_concurrency": 1, **extra}))
    return path


def test_server_catalog_and_suite_selections_load(tmp_path):
    document = yaml.safe_load(CATALOG_PATH.read_text())
    catalog = document["protocols"]
    selected = document["selected_protocols"]
    assert len(catalog) == 101
    assert selected
    assert set(selected) <= set(catalog)
    assert len(selected) == len(set(selected))
    assert set(catalog) >= {
        "5G-AKA-TS33.501-v15.0.0-AKA",
        "ISO-11770-2-key-establishment-mechanism-1",
        "ISO-9798-6-mechanism-8b", "Denning-Sacco",
        "FIDO-UAF-registration", "Signal-PQXDH-revision2",
        "EDHOC-draft-08-symmetric", "IKEv2-signature",
        "OAuth-2.0-draft22-mac", "TLS13-draft18-zero-rtt",
    }
    config = _config(tmp_path)
    for name in BATCHES:
        suite = load_suite(name, config)
        assert [p.id for p in suite.protocols] == selected
        assert len(suite.protocols) == len(selected)
        assert suite.max_runs > 0
        assert suite.work_root == tmp_path / "runs" / name


def test_load_suite_rejects_non_positive_run_concurrency(tmp_path):
    config = _config(tmp_path)
    config.write_text(config.read_text().replace(
        "max_runs_concurrency: 1", "max_runs_concurrency: 0"))
    with pytest.raises(ValueError, match="positive integer"):
        load_suite("main", config)


def test_load_suite_rejects_an_unknown_batch(tmp_path):
    with pytest.raises(ValueError, match="unknown batch 'nosuch'"):
        load_suite("nosuch", _config(tmp_path))


def test_catalog_rejects_an_unknown_selected_protocol(tmp_path):
    path = tmp_path / "protocols.yaml"
    path.write_text(yaml.safe_dump({
        "selected_protocols": ["TYPO"],
        "protocols": {"NSPK": {"protocol_name": "NSPK",
                               "path": "academic/NSPK"}}}))
    with pytest.raises(ValueError, match="unknown selected protocol ids.*TYPO"):
        _catalog(path)


def test_the_batch_config_refuses_to_hold_an_experiment(tmp_path):
    """Engine settings belong to batches.py, so an experiment key written in
    the batch config is refused rather than merged."""
    config = _config(tmp_path, inputs={"lib_claims": False})
    with pytest.raises(ValueError, match="batches.py"):
        load_suite("main", config)


def test_work_root_is_the_configured_root_plus_the_batch_name(tmp_path):
    """A batch contributes its name to the work root and nothing else, so
    no absolute path of one machine gets baked into a shipped file."""
    config = _config(tmp_path)
    suite = load_suite("main", config)
    assert suite.work_root == tmp_path / "runs" / "main"
    # One file, not a stack: `--config` replaces the user level outright, so
    # this is the whole of what a child reads.
    assert suite.config == config
    assert suite.overrides == BATCHES["main"]


def test_a_batch_states_no_credential_and_no_path(tmp_path):
    """Which model answers and where the output goes belong to the machine
    running the batch, so a batch may pin neither."""
    for name, overrides in BATCHES.items():
        assert "llm" not in overrides, name
        assert "paths" not in overrides, name


def test_preflight_refuses_before_the_first_child(tmp_path):
    """One error at the start rather than one forked child per protocol."""
    config = _config(tmp_path, llm={
        "backend": "remote-claude",
        "profiles": {"remote-claude": {"api_key": "???"}}})
    suite = load_suite("main", config)          # readable: status still answers
    with pytest.raises(MissingConfigError,
                       match=r"llm\.profiles\.remote-claude\.api_key"):
        preflight(suite)


def test_the_child_command_is_two_words(tmp_path):
    """What crosses the process boundary is a batch's name, not its
    settings, so the command recorded in `_batch/` cannot be re-run by hand
    with different ones."""
    suite = _suite(tmp_path)
    protocol = Protocol("EDHOC", "rfc/EDHOC/draft-08", "draft-08", "asymmetric")
    command, state = build_orrery(suite, protocol)
    assert command[1:] == ["-m", "experiments.batch", "_child", "main",
                           "EDHOC-draft-08-asymmetric"]
    assert "--config" not in command          # the child reads it off the suite
    assert not any("timeout_s" in part for part in command)   # nor the settings
    assert state == {"run_dir": None, "run_name": None}


def test_the_child_hands_orrery_the_batch_and_the_work_root(tmp_path):
    """The work root is derived per batch and is the one thing added to a
    batch's own settings."""
    suite = _suite(tmp_path)
    # The child reads the batch config to hand the engine its settings, so the
    # file has to exist, with the runner's own key in it.
    suite.config.write_text("paths:\n  work_root: ./x\nmax_runs_concurrency: 2\n")
    protocol = Protocol("NSPK", "academic/NSPK")
    seen = {}

    def fake_launch(name, directory, config, **kw):
        seen.update(name=name, directory=directory, config=config, **kw)
        return 0

    import orrery.main
    original, orrery.main.launch = orrery.main.launch, fake_launch
    try:
        assert child_orrery(suite, protocol, None) == 0
    finally:
        orrery.main.launch = original
    # The file's engine settings, without the runner's own concurrency key,
    # which the engine's loader would refuse as a knob nothing reads.
    from experiments.batch.common import engine_layer
    assert seen["config"] == engine_layer(suite.config)
    assert "max_runs_concurrency" not in seen["config"]
    assert seen["overrides"]["inputs"] == BATCHES["main"]["inputs"]
    assert seen["overrides"]["paths"] == {"work_root": str(suite.work_root)}
    assert seen["directory"] == suite.lib_root / "academic/NSPK"


def test_baseline_allocates_a_fresh_number(tmp_path):
    suite = _suite(tmp_path)
    protocol = Protocol("NSPK", "academic/NSPK")
    (suite.work_root / "NSPK" / "NSPK01").mkdir(parents=True)
    command, seed = build_baseline(suite, protocol)
    assert seed["run_name"] == "NSPK02"
    assert command[-2:] == ["--run-name", "NSPK02"]


def test_dead_running_pid_is_not_running(tmp_path):
    """An entry a dead scheduler left behind is neither running nor pending
    while its run directory stands, so `run` walks past it and reports it
    instead of starting over on top of it."""
    run_dir = tmp_path / "NSPK01"
    run_dir.mkdir()
    state = {"status": "running", "pid": 999_999_999, "run_dir": str(run_dir)}
    assert not is_running(state)
    assert not is_pending(state)
    assert is_pending({})


def test_deleting_a_run_directory_makes_a_protocol_pending_again(tmp_path):
    """The run artifacts are the truth and `_batch` is bookkeeping, so removing
    a run directory is how a person says "start this one over"."""
    run_dir = tmp_path / "NSPK01"
    run_dir.mkdir()
    state = {"status": "failed", "run_dir": str(run_dir)}
    assert not is_pending(state)
    run_dir.rmdir()
    assert is_pending(state)
    # A failure before any run directory was written is pending for the same
    # reason: there is nothing on disk to preserve.
    assert is_pending({"status": "failed", "run_dir": None})


def test_dead_running_pid_is_reported_interrupted():
    assert report_status({"status": "running", "pid": 999_999_999},
                         artifact_status) == "interrupted"


def test_finished_artifact_wins_after_scheduler_dies(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(json.dumps({"status": "ok"}))
    assert report_status({"status": "running", "pid": 999_999_999,
                          "run_dir": str(run_dir)}, artifact_status) == "finished"


def test_artifacts_change_the_report_and_never_a_control_decision(tmp_path):
    """A run that finished after its scheduler died reads as `finished` rather
    than `interrupted`, but the two control predicates take no artifact_status
    and answer the same either way."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(json.dumps({"status": "ok"}))
    state = {"status": "running", "pid": 999_999_999, "run_dir": str(run_dir)}
    assert report_status(state, artifact_status) == "finished"
    assert report_status(state, lambda _: None) == "interrupted"
    assert not is_running(state) and not is_pending(state)


def test_report_asks_the_entry_point_what_a_run_directory_means(tmp_path):
    """The two experiments end differently — an Orrery run states a status, a
    baseline run only stamps when it finished — so the scheduler asks the
    entry point instead of reading run.json itself."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(json.dumps(
        {"experiment": "oneshot", "finished_at": "2026-01-01T00:00:00+00:00"}))
    state = {"status": "running", "pid": 999_999_999, "run_dir": str(run_dir)}
    assert report_status(state, baseline_batch.artifact_status) == "finished"
    assert report_status(state, artifact_status) == "interrupted"


def test_a_truncated_run_json_does_not_break_a_status_listing(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run.json").write_text('{"status": "o')
    for reader in (artifact_status, baseline_batch.artifact_status):
        assert reader(run_dir) is None


def test_orrery_clean_interrupt_line_is_persisted(tmp_path):
    suite = _suite(tmp_path)
    protocol = Protocol("NSPK", "academic/NSPK")
    state = {"status": "running", "pid": 123}
    write_state(suite, protocol, state)
    line_hook(suite, protocol, state,
              "Interrupted. Re-enter this run with --from-node <node>.")
    assert read_state(suite, protocol)["interrupted"] is True


def _seed(suite, protocol) -> dict:
    """The directory a runner names for its child, made so the state can
    record it: a child that exits 0 without one is a broken runner."""
    run_dir = suite.work_root / protocol.id / f"{protocol.id}01"
    run_dir.mkdir(parents=True, exist_ok=True)
    return {"run_dir": str(run_dir), "run_name": run_dir.name}


def test_process_scheduler_records_completion_and_log(tmp_path):
    suite = _suite(tmp_path)
    protocol = Protocol("NSPK", "academic/NSPK")

    def build(suite, protocol):
        return [sys.executable, "-c", "print('finished child')"], _seed(suite, protocol)

    asyncio.run(run_many(suite, [protocol], runner=_runner(build)))
    state = read_state(suite, protocol)
    assert state["status"] == "finished"
    assert state["exit_code"] == 0
    assert "finished child" in Path(state["log"]).read_text()


def test_one_batch_launch_failure_does_not_cancel_its_sibling(tmp_path):
    suite = _suite(tmp_path)
    bad = Protocol("BAD", "bad")
    good = Protocol("GOOD", "good")

    def build(suite, protocol):
        if protocol.id == "BAD":
            raise ValueError("bad command")
        return [sys.executable, "-c", "print('ok')"], _seed(suite, protocol)

    with pytest.raises(RuntimeError, match="BAD"):
        asyncio.run(run_many(suite, [bad, good], runner=_runner(build)))
    assert read_state(suite, bad)["status"] == "failed"
    assert read_state(suite, good)["status"] == "finished"


def test_concurrent_batches_claim_each_pending_protocol_once(tmp_path):
    suite = _suite(tmp_path)
    protocols = [Protocol(f"P{i}", f"p{i}") for i in range(6)]
    builds: list[str] = []

    def build(suite, protocol):
        builds.append(protocol.id)
        # Seeded with a directory, the way baseline seeds it: a finished
        # protocol with no directory reads as pending again, and the second
        # scheduler would then build it a second time.
        return [
            sys.executable, "-c",
            "import time; time.sleep(0.05); print('ok')",
        ], _seed(suite, protocol)

    async def both():
        await asyncio.gather(*[
            run_many(suite, protocols, runner=_runner(build))
            for _ in range(2)
        ])

    asyncio.run(both())
    assert sorted(builds) == sorted(p.id for p in protocols)
    assert all(read_state(suite, p)["status"] == "finished"
               for p in protocols)


def test_a_protocol_another_batch_owns_is_skipped(tmp_path):
    """Two schedulers may share one batch's queue, so a protocol already
    claimed is somebody else's work rather than an error: never built twice,
    and nothing is written for it here."""
    suite = _suite(tmp_path)
    protocol = Protocol("NSPK", "academic/NSPK")

    def build(suite, protocol):
        raise AssertionError("a busy protocol must not be built")

    with protocol_claim(suite, protocol):
        asyncio.run(run_many(suite, [protocol], runner=_runner(build)))
    assert read_state(suite, protocol) == {}


def test_protocol_claim_is_shared_between_os_processes(tmp_path):
    suite = _suite(tmp_path)
    protocol = Protocol("NSPK", "academic/NSPK")
    script = """
import sys
from pathlib import Path
from types import SimpleNamespace
from experiments.batch.common import Protocol, ProtocolBusy, protocol_claim

suite = SimpleNamespace(state_root=Path(sys.argv[1]))
protocol = Protocol("NSPK", "academic/NSPK")
try:
    with protocol_claim(suite, protocol):
        raise SystemExit(2)
except ProtocolBusy:
    raise SystemExit(0)
"""
    with protocol_claim(suite, protocol):
        result = subprocess.run(
            [sys.executable, "-c", script, str(suite.state_root)],
            cwd=Path(__file__).parents[3], check=False)
    assert result.returncode == 0


def test_a_child_that_ends_well_without_naming_its_run_is_a_broken_runner(tmp_path):
    """is_pending reads a finished protocol with no directory as one to start
    again, so a runner that let its child exit 0 without naming one would have
    that protocol built twice. The contract is enforced where it is broken."""
    suite = _suite(tmp_path)
    protocol = Protocol("NSPK", "academic/NSPK")

    def build(suite, protocol):
        return [sys.executable, "-c", "print('ok')"], {}

    # the scheduler reports it as a batch-layer failure and the state says why
    with pytest.raises(RuntimeError, match="failed in the batch layer: NSPK"):
        asyncio.run(run_many(suite, [protocol], runner=_runner(build)))
    state = read_state(suite, protocol)
    assert state["status"] == "failed"
    assert "never named its run directory" in state["error"]


def test_a_protocol_that_died_before_its_run_directory_is_started_again(tmp_path):
    """A child that fails before printing ``run:`` (a corpus path that is
    wrong) leaves a state with no directory. That is pending again by
    is_pending's rule, and the blocking gate in main() applies the same rule,
    or the batch could never be started again without editing state files."""
    from experiments.batch.common import is_pending, report_status
    state = {"status": "failed", "run_dir": None, "exit_code": 1}
    assert is_pending(state)
    # what the gate used to look at alone: a word that reads as blocking
    assert report_status(state, lambda p: None) == "failed"


def test_resume_reenters_the_recorded_run_under_the_batch_settings(tmp_path):
    """The resumed child gets the run name and the node on its command line,
    which is how the batch's own overrides reach the continued run: the
    child imports them by batch name, as a fresh child does."""
    from experiments.batch.orrery import build
    suite = _suite(tmp_path)
    protocol = Protocol("NSPK", "academic/NSPK")
    cmd, seed = build(suite, protocol, ("NSPK03", "extract_flow"))
    assert cmd[-4:] == ["--run-name", "NSPK03", "--from-node", "extract_flow"]
    assert seed == {"run_dir": str(suite.work_root / "NSPK" / "NSPK03"),
                    "run_name": "NSPK03"}
    fresh, _ = build(suite, protocol)
    assert "--from-node" not in fresh


def test_a_resumed_protocol_is_not_pending_and_still_runs(tmp_path):
    """run's gate refuses a protocol holding a finished run; resume is the one
    door past it, and it refuses a run still in flight."""
    suite = _suite(tmp_path)
    protocol = Protocol("NSPK", "academic/NSPK")
    write_state(suite, protocol, {**_seed(suite, protocol),
                                  "status": "interrupted", "pid": None})
    seen = []

    def build(suite, protocol, resume=None):
        seen.append(resume)
        return [sys.executable, "-c", "print('ok')"], _seed(suite, protocol)

    asyncio.run(run_many(suite, [protocol], runner=_runner(build),
                         resume=("NSPK01", "extract_flow")))
    assert seen == [("NSPK01", "extract_flow")]
    assert read_state(suite, protocol)["status"] == "finished"


def test_stop_interrupts_the_scheduler_before_the_children(tmp_path):
    """A stop that only reaches the children lets the scheduler start the
    next twenty; the scheduler's own note is what stop reads first."""
    from experiments.batch.common import scheduler_registered, stop_batch
    suite = _suite(tmp_path)
    protocol = Protocol("NSPK", "academic/NSPK")
    got = []
    real_kill = os.kill

    def fake_kill(pid, sig):
        if sig:                               # pid_alive probes with 0; not a signal
            got.append((pid, sig))
        return real_kill(pid, 0)              # only probe; never signal the test process

    import experiments.batch.common as common
    common.os.kill = fake_kill
    try:
        with scheduler_registered(suite):
            note = next(suite.state_root.glob("scheduler.*.json"))
            assert json.loads(note.read_text())["pid"] == os.getpid()
            schedulers, orphans = stop_batch(suite, wait_s=0)
        assert schedulers == [os.getpid()] and orphans == []
        assert got == [(os.getpid(), signal.SIGINT)]
    finally:
        common.os.kill = real_kill
    # the note goes with the scheduler, and a stale one is cleared by stop
    assert not list(suite.state_root.glob("scheduler.*.json"))
    (suite.state_root / "scheduler.999999.json").write_text('{"pid": 999999}')
    assert stop_batch(suite, wait_s=0) == ([], [])
    assert not list(suite.state_root.glob("scheduler.*.json"))
