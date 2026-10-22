"""The Orrery node pipeline as one kind of batch experiment.

`RUNNER` at the bottom bundles the four things the scheduler needs: the command
that starts one experiment, how to run one in this process, what to read out of
a child's output, and what a finished run directory means. The entry point is
`__main__.py` beside this; `batches.py::RUNNERS` names this module.
"""
from __future__ import annotations

import sys
from pathlib import Path

from experiments.batch.common import (
    Protocol, Runner, Suite, main, read_json, write_state,
)


def build(suite: Suite, protocol: Protocol,
          resume: tuple[str, str] | None = None) -> tuple[list[str], dict]:
    """Build the child-process command for one experiment, plus its initial state.

    Only two words cross the boundary, the batch name and the protocol id;
    the child imports the settings from `batches.py`, so the recorded command
    is one a person can retype. `sys.executable` makes the child inherit the
    scheduler's interpreter, which by definition has Orrery importable.

    ``resume`` is ``(run_name, from_node)``: the child re-enters that run in
    place under the batch's own settings, which is the one way to continue an
    interrupted run without silently changing what it was configured to do.
    """
    cmd = [sys.executable, "-m", "experiments.batch",
           "_child", suite.name, protocol.id]
    if resume is None:
        return cmd, {"run_dir": None, "run_name": None}
    run_name, from_node = resume
    cmd += ["--run-name", run_name, "--from-node", from_node]
    return cmd, {"run_dir": str(suite.work_root / protocol.id / run_name),
                 "run_name": run_name}


def child(suite: Suite, protocol: Protocol, run_name: str | None,
          from_node: str | None = None) -> int:
    """Run one experiment in this process; `build`'s command lands here.

    `launch` is Orrery's entry point for a host that does not go through argv,
    the same one `orrery run` calls, taking the batch as a dict. It prints
    the run directory before starting and turns one Ctrl-C into a clean stop,
    which `line_hook` reads and `stop` relies on. Returns the exit code.
    """
    from orrery.main import launch

    from experiments.batch.common import engine_layer

    # The work root is the only thing added to the batch's own settings, so
    # no batch has to write a path down. A batch may not carry `paths`,
    # so this cannot collide.
    overrides = {**suite.overrides, "paths": {"work_root": str(suite.work_root)}}
    return launch(protocol.protocol_name, suite.lib_root / protocol.path,
                  engine_layer(suite.config), overrides=overrides,
                  version=protocol.version, subprotocol=protocol.subprotocol,
                  run_name=run_name, from_node=from_node)


def line_hook(suite: Suite, protocol: Protocol, state: dict, line: str) -> None:
    if line.startswith("Interrupted."):
        state["interrupted"] = True
        write_state(suite, protocol, state)
        return
    for prefix in ("run: ", "artifacts: "):
        if line.startswith(prefix):
            run_dir = line[len(prefix):].strip()
            state["run_dir"] = run_dir
            state["run_name"] = Path(run_dir).name
            write_state(suite, protocol, state)
            return


def artifact_status(run_dir: Path) -> str | None:
    """Turn an Orrery run's own `run.json` status into a batch status.

    `ok` and `check_failed` both count as finished: a failed check is a verdict
    about the protocol, not about the batch. Returns None for anything else,
    including a run.json not written yet, leaving the answer to the batch state.
    """
    status = read_json(run_dir / "run.json").get("status")
    if status in ("ok", "check_failed"):
        return "finished"
    if status in ("failed", "interrupted"):
        return status
    return None


#: This kind of experiment, as the scheduler sees it. `common.runner_for` reads
#: it after `batches.RUNNERS` names this module.
RUNNER = Runner(build, child, line_hook, artifact_status)
