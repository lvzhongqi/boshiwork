"""One experiment kind: the monolithic one-shot baseline, as a `Runner`.

Supplies the command that starts a baseline run, its run naming, and how to
read a finished run directory. A baseline run has no `--from-node` to re-enter
from and announces no name of its own. `../oneshot/` is imported inside
`child`, only when a child process actually needs it.
"""
from __future__ import annotations

import sys
from pathlib import Path

from experiments.batch.common import (
    Protocol, Runner, Suite, main, read_json,
)


def _next_name(suite: Suite, protocol: Protocol) -> str:
    home = suite.work_root / protocol.id
    used = {p.name for p in home.iterdir()} if home.is_dir() else set()
    for number in range(1, 10000):
        name = f"{protocol.id}{number:02d}"
        if name not in used:
            return name
    raise RuntimeError(f"{protocol.id}: exhausted four-digit run numbering")


def build(suite: Suite, protocol: Protocol,
          resume: tuple[str, str] | None = None) -> tuple[list[str], dict]:
    """Build the child command line and the initial state for one baseline run.

    Only the suite name, protocol id and run name cross as text; the batch's
    settings do not. The run name is allocated here because the baseline never
    announces one, so the scheduler has to know it before the child starts.
    A baseline has no nodes to re-enter at, so ``resume`` is refused.
    """
    if resume is not None:
        raise ValueError(
            f"a baseline run cannot be resumed at a node ({protocol.id}: "
            f"{resume[0]}); delete its run directory to start it over")
    run_name = _next_name(suite, protocol)
    cmd = [sys.executable, "-m", "experiments.batch",
           "_child", suite.name, protocol.id, "--run-name", run_name]
    run_dir = suite.work_root / protocol.id / run_name
    return cmd, {"run_name": run_name, "run_dir": str(run_dir)}


def child(suite: Suite, protocol: Protocol, run_name: str | None,
          from_node: str | None = None) -> int:
    """Run one baseline in this process and return its exit code.

    The batch's overrides and its config are handed to the baseline entry
    point as dicts, so nothing but paths and names travels as command-line
    text, and the runner's own ``max_runs_concurrency`` never reaches the
    engine's loader.
    """
    from experiments.batch.common import engine_layer
    from experiments.oneshot.runner import main as run_oneshot

    if from_node is not None:
        raise ValueError("a baseline run has no node to resume at")
    argv = ["--dir", str(suite.lib_root / protocol.path),
            "--name", protocol.id,
            "--out", str(suite.work_root),
            "--run-name", run_name or protocol.id]
    if protocol.subprotocol:
        argv += ["--subprotocol", protocol.subprotocol]
    return run_oneshot(argv, overrides=suite.overrides,
                       config=engine_layer(suite.config))


def line_hook(suite: Suite, protocol: Protocol, state: dict, line: str) -> None:
    """No-op: nothing in a baseline child's output is worth lifting out.

    `build` already seeded the run directory, and an interrupted baseline is
    resumed from its `verdict.json` rather than from a node.
    """
    return None


def artifact_status(run_dir: Path) -> str | None:
    """Read a finished baseline run's status out of its run directory.

    `run.json` is written last and only on the way out, so a `finished_at` in
    it is the whole answer. There is no overall status field, so a run that
    died returns None and the batch state decides its fate.
    """
    return "finished" if read_json(run_dir / "run.json").get("finished_at") else None


#: The scheduler's handle on this experiment kind.
RUNNER = Runner(build, child, line_hook, artifact_status)
