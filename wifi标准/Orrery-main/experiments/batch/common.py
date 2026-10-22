"""Process scheduler shared by the batch entry points: which protocols run, and
how many at once.

Three inputs that do not overlap: ``../batches.py`` holds what an experiment
means, ``../protocols.yaml`` which protocols, ``../config.yaml`` this machine's
credential, paths and concurrency. Everything experiment-specific arrives as a
``Runner``. The run artifacts are the experimental truth; ``_batch`` records
only which process and log belong to a protocol.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import fcntl
import json
import os
import re
import signal
import subprocess
import time
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import yaml

from orrery.pipeline.config import (
    MissingConfigError, ensure_config, load_config,
)

from experiments.batches import (
    BATCHES, PAPER_MODEL, PAPER_PROVERIF, RUNNERS,
)


@dataclass(frozen=True)
class Protocol:
    protocol_name: str
    path: str
    version: str | None = None
    subprotocol: str | None = None

    @property
    def id(self) -> str:
        return "-".join(x for x in (
            self.protocol_name, self.version, self.subprotocol) if x)


#: The checkout the children are started from. ``parents[2]`` depends on where
#: this file sits, so the result is checked right here.
ROOT = Path(__file__).resolve().parents[2]
if not (ROOT / "pyproject.toml").is_file():
    raise RuntimeError(
        f"the scheduler cannot find the checkout it lives in: no pyproject.toml "
        f"at {ROOT}. Moving this file to another depth changes what parents[1] "
        f"means, and this is that move failing loudly rather than starting "
        f"children in the wrong directory.")


@dataclass(frozen=True)
class Suite:
    #: A key of ``BATCHES``, and the directory name under ``work_root``.
    name: str
    #: The one config file handed to every child. ``--config`` replaces the user
    #: level outright, so the root config.yaml is never opened by a child.
    config: Path
    #: This batch's settings, from ``batches.py``. The child imports them
    #: by batch name; they never cross the command line.
    overrides: dict
    work_root: Path
    lib_root: Path
    max_runs: int
    protocols: tuple[Protocol, ...]

    @property
    def state_root(self) -> Path:
        return self.work_root / "_batch"


#: Build the command that starts one experiment, and the state to seed its entry
#: with: ``(suite, protocol[, resume]) -> (argv, seed)``. The argv names this
#: module's hidden ``_child`` command, so only a batch's name crosses the
#: process boundary; the settings are imported from code on the other side.
#: ``resume`` is ``(run_name, from_node)`` when an interrupted run is being
#: continued in place rather than a fresh one started.
CommandBuilder = Callable[..., tuple[list[str], dict]]
#: Run one experiment in this process: ``(suite, protocol, run_name[,
#: from_node]) -> exit code``. What the child does once ``_child`` has parsed
#: its words.
ChildRunner = Callable[..., int]
#: Watch the child's stdout a line at a time, for whatever the entry point needs
#: to lift out of it (a run directory, a clean interrupt).
LineHook = Callable[[Suite, Protocol, dict, str], None]
#: What a run directory says about itself: ``"finished"``, ``"failed"``,
#: ``"interrupted"``, or ``None`` when the artifacts do not answer. Reporting
#: only; no control decision reads it.
ArtifactStatus = Callable[[Path], str | None]


@dataclass(frozen=True)
class Runner:
    """One experiment kind, as the scheduler needs to see it.

    Everything experiment-specific arrives through here: the scheduler starts
    the command it is handed, reads lines back through the hook it is handed,
    and asks ``artifact_status`` what a run directory means.
    """

    build: CommandBuilder
    child: ChildRunner
    line_hook: LineHook
    #: Read by ``print_status`` and nobody else; control decisions ask
    #: ``is_pending`` / ``is_running`` instead.
    artifact_status: ArtifactStatus


#: This runner's own config: one credential, this machine's paths, and how many
#: runs at once. Separate from the project root config, which it neither reads
#: nor extends.
CONFIG_PATH = ROOT / "experiments" / "config.yaml"
EXAMPLE_PATH = ROOT / "experiments" / "config.example.yaml"
CATALOG_PATH = ROOT / "experiments" / "protocols.yaml"

#: Everything the batch config file may hold. Unknown keys are rejected rather
#: than merged: an engine setting written here would redefine the experiment per
#: machine, which is what ``batches.py`` exists to prevent.
_CONFIG_KEYS = {"llm", "proverif", "paths", "max_runs_concurrency"}


def _mapping(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"required configuration does not exist: {path}")
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return value


def _catalog(path: Path) -> tuple[Protocol, ...]:
    """The protocols this batch runs, ordered by ``selected_protocols``.

    Raises ``ValueError`` up front on an unknown key, an id that names no entry,
    an entry whose fields do not generate its own id, or a duplicate selection.
    """
    catalog = _mapping(path)
    raw_catalog = catalog.get("protocols")
    if not isinstance(raw_catalog, dict) or not raw_catalog:
        raise ValueError(f"{path}: protocols must be a non-empty mapping")
    definitions = {}
    for protocol_id, raw in raw_catalog.items():
        if not isinstance(protocol_id, str) or not protocol_id.strip():
            raise ValueError(f"{path}: protocol ids must be non-empty strings")
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: protocols.{protocol_id} must be a mapping")
        unknown = set(raw) - {"protocol_name", "path", "version", "subprotocol"}
        if unknown:
            raise ValueError(
                f"{path}: protocols.{protocol_id} has unknown keys "
                f"{sorted(unknown)}")
        for required in ("protocol_name", "path"):
            if not isinstance(raw.get(required), str) or not raw[required].strip():
                raise ValueError(
                    f"{path}: protocols.{protocol_id}.{required} must be "
                    "a non-empty string")
        p = Protocol(raw["protocol_name"], raw["path"], raw.get("version"),
                     raw.get("subprotocol"))
        if p.id != protocol_id:
            raise ValueError(
                f"{path}: key {protocol_id!r} does not match the identity "
                f"generated by its fields ({p.id!r})")
        definitions[protocol_id] = p

    selected = catalog.get("selected_protocols")
    if not isinstance(selected, list) or not selected:
        raise ValueError(
            f"{path}: selected_protocols must be a non-empty list of ids")
    if any(not isinstance(item, str) or not item.strip() for item in selected):
        raise ValueError(f"{path}: selected protocol ids must be non-empty strings")
    if len(selected) != len(set(selected)):
        raise ValueError(f"{path}: selected_protocols contains duplicate ids")
    missing = [protocol_id for protocol_id in selected
               if protocol_id not in definitions]
    if missing:
        raise ValueError(f"{path}: unknown selected protocol ids {missing}")
    return tuple(definitions[protocol_id] for protocol_id in selected)


def load_suite(name: str, config: str | Path | None = None) -> Suite:
    """Everything one batch needs: its settings, its protocols, this machine.

    ``name`` is a key of ``BATCHES``; ``config`` defaults to ``CONFIG_PATH``.
    The config is loaded with ``require=False`` so an unfilled credential still
    lets ``status`` answer — anything about to spend money calls ``preflight``.
    """
    if name not in BATCHES:
        raise ValueError(
            f"unknown batch {name!r}; this repository defines "
            f"{', '.join(sorted(BATCHES))}. A batch is an entry in "
            f"experiments/batches.py, not a directory.")
    # Seeded from the example on first use, so a fresh checkout only has to
    # paste a key into it.
    config_path = Path(config) if config else ensure_config(CONFIG_PATH,
                                                            EXAMPLE_PATH)
    if not config_path.is_file():
        raise FileNotFoundError(f"no such config: {config_path}")

    raw = _mapping(config_path)
    unknown = sorted(set(raw) - _CONFIG_KEYS)
    if unknown:
        raise ValueError(
            f"{config_path}: {unknown} does not belong in the batch runner's "
            f"config, which holds only {sorted(_CONFIG_KEYS)}. What an "
            f"experiment *means* -- inputs, budgets, where it stops -- is "
            f"experiments/batches.py, in code, so that it is the same on "
            f"every machine.")
    limit = raw.get("max_runs_concurrency")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError(
            f"{config_path}: max_runs_concurrency must be a positive integer")

    overrides = BATCHES[name]
    # Orrery's own loader, the same one every child uses, so the scheduler's
    # view of a run and the run itself cannot drift.
    config = load_config(engine_layer(config_path), overrides=overrides,
                         require=False)
    # The loader anchors relative paths on the project, so these are already
    # absolute; checked anyway, since a non-path value would otherwise surface
    # as a batch writing somewhere surprising instead of as an error.
    paths = config["paths"]
    for key in ("work_root", "lib_root"):
        if not isinstance(paths.get(key), str) or not Path(paths[key]).is_absolute():
            raise ValueError(
                f"{config_path}: paths.{key} must resolve to an absolute path; "
                f"it came out as {paths.get(key)!r}")
    return Suite(
        name=name,
        config=config_path,
        overrides=overrides,
        # The batch contributes its own name and nothing else; the absolute
        # part comes from this machine's config.
        work_root=Path(paths["work_root"]) / name,
        lib_root=Path(paths["lib_root"]),
        max_runs=limit,
        protocols=_catalog(CATALOG_PATH),
    )


def engine_layer(config_path: Path) -> dict:
    """The batch config as the engine's loader takes it: the file's mappings
    without ``max_runs_concurrency``, which is this runner's own setting. The
    engine refuses a key nothing in it reads, and it is right to."""
    return {k: v for k, v in _mapping(config_path).items()
            if k != "max_runs_concurrency"}


def preflight(suite: Suite) -> None:
    """Load the config with ``require=True`` so a missing credential is one
    error before the first child rather than one per protocol.

    Raises ``MissingConfigError`` naming the key and the file; which slot is
    required depends on the backend that same file names.
    """
    try:
        load_config(engine_layer(suite.config), overrides=suite.overrides,
                    require=True)
    except MissingConfigError as e:
        raise MissingConfigError(f"{e}; the file is {suite.config}") from None


def state_path(suite: Suite, protocol: Protocol) -> Path:
    return suite.state_root / f"{protocol.id}.json"


def read_state(suite: Suite, protocol: Protocol) -> dict:
    path = state_path(suite, protocol)
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise RuntimeError(f"cannot read batch state {path}: {e}") from e
    if not isinstance(value, dict):
        raise RuntimeError(f"batch state is not an object: {path}")
    return value


def write_state(suite: Suite, protocol: Protocol, value: dict) -> None:
    path = state_path(suite, protocol)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class ProtocolBusy(RuntimeError):
    """Another batch process currently owns this protocol."""


@contextmanager
def protocol_claim(suite: Suite, protocol: Protocol):
    """Hold the cross-process claim for one protocol until the run finishes.

    Raises ``ProtocolBusy`` if another batch process holds it. The lock is a
    kernel ``flock`` released when the scheduler exits or crashes, so several
    batch processes share one ``_batch`` directory with no stale-lock cleanup.
    """
    lock_dir = suite.state_root / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    path = lock_dir / f"{protocol.id}.lock"
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise ProtocolBusy(
                f"{protocol.id} is already claimed by another batch") from e
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps({
            "protocol_id": protocol.id,
            "scheduler_pid": os.getpid(),
            "claimed": datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False) + "\n")
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def pid_alive(pid) -> bool:
    if not isinstance(pid, int) or pid < 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_json(path: Path) -> dict:
    """The mapping at ``path``, or ``{}`` if it is missing or unreadable.

    For the ``artifact_status`` implementations: an experiment that crashed
    mid-write leaves a truncated file behind, and a status listing has to
    survive reading it.
    """
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


# Control flow asks two questions, both answerable from ``_batch`` and a live
# pid: has this protocol been started at all, and is it running right now. How a
# finished experiment turned out needs the run's own artifacts, so only
# ``report_status`` takes an ``artifact_status``.


def is_pending(state: dict) -> bool:
    """Nothing of this protocol exists to look at, so ``run`` may start it.

    True three ways: never started; started but left nothing on disk (a failure
    in the batch layer, before any run directory); or its run directory has been
    deleted, which is how a person asks for that protocol to start over.
    """
    if is_running(state):
        return False
    if not state.get("status"):
        return True
    run_dir = state.get("run_dir")
    return not run_dir or not Path(run_dir).is_dir()


def is_running(state: dict) -> bool:
    """Started, and its process is still alive.

    A state file saying ``running`` proves only what some scheduler last saw,
    and children outlive the scheduler that started them
    (``start_new_session``), so the pid is checked against the machine.
    """
    return state.get("status") == "running" and pid_alive(state.get("pid"))


def report_status(state: dict, artifact_status: ArtifactStatus) -> str:
    """One word for a person reading the table.

    A scheduler that was killed never wrote an ending, so a run still marked
    ``running`` whose pid is gone is judged by what ``artifact_status`` reads
    off disk instead.
    """
    run_dir = state.get("run_dir")
    artifact = artifact_status(Path(run_dir)) if run_dir else None
    if state.get("status") == "running":
        return "running" if pid_alive(state.get("pid")) else (artifact or "interrupted")
    if state.get("status") == "starting":
        return artifact or "interrupted"
    if artifact:
        return artifact
    return str(state.get("status") or "pending")


def print_status(suite: Suite, artifact_status: ArtifactStatus) -> None:
    """Print one row per protocol: status and the run name it left.

    ``run`` never continues an unfinished run, so re-entering one goes through
    Orrery's ``--run-name`` / ``--from-node``, and this is where that name comes
    from.
    """
    rows = []
    for p in suite.protocols:
        state = read_state(suite, p)
        rows.append((p.id, report_status(state, artifact_status),
                     state.get("run_name") or ""))
    width = max([len("protocol"), *(len(name) for name, _, _ in rows)])
    print(f"{'protocol':<{width}}  {'status':<11}  run")
    print(f"{'-' * width}  -----------  ---")
    for name, status, run in rows:
        print(f"{name:<{width}}  {status:<11}  {run}")
    totals = {s: sum(1 for _, got, _ in rows if got == s)
              for s in ("finished", "running", "interrupted", "failed", "pending")}
    print("\n" + "  ".join(f"{k}={v}" for k, v in totals.items()))


async def _one(suite: Suite, protocol: Protocol, *, runner: Runner,
               resume: tuple[str, str] | None = None) -> None:
    with protocol_claim(suite, protocol):
        old = read_state(suite, protocol)
        if resume is None and not is_pending(old):
            # Claimed between the listing and here, by another batch process.
            print(f"[{protocol.id}] skipped: no longer pending", flush=True)
            return
        if resume is not None and is_running(old):
            raise RuntimeError(f"[{protocol.id}] is still running (pid "
                               f"{old.get('pid')}); stop it before resuming")
        command, seed = (runner.build(suite, protocol) if resume is None
                         else runner.build(suite, protocol, resume))
        attempt = int(old.get("attempt", 0)) + 1
        log_dir = suite.state_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{protocol.id}.{attempt:02d}.log"
        state = {
            **old, **seed,
            "protocol_id": protocol.id,
            "attempt": attempt,
            "status": "starting",
            "command": command,
            "log": str(log_path),
            "started": datetime.now().isoformat(timespec="seconds"),
            "finished": None,
            "exit_code": None,
            "stop_requested": False,
            "interrupted": False,
        }
        write_state(suite, protocol, state)
        with log_path.open("a", encoding="utf-8", buffering=1) as log:
            proc = await asyncio.create_subprocess_exec(
                *command, cwd=ROOT,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                start_new_session=True)
            state.update(status="running", pid=proc.pid)
            write_state(suite, protocol, state)
            try:
                assert proc.stdout is not None
                async for raw in proc.stdout:
                    line = raw.decode("utf-8", errors="replace")
                    log.write(line)
                    print(f"[{protocol.id}] {line}", end="", flush=True)
                    runner.line_hook(suite, protocol, state, line.rstrip("\n"))
                code = await proc.wait()
            except asyncio.CancelledError:
                latest = read_state(suite, protocol)
                latest.update(stop_requested=True)
                write_state(suite, protocol, latest)
                try:
                    os.killpg(proc.pid, signal.SIGINT)
                except ProcessLookupError:
                    pass
                # Keep reading until the child closes its end: it says how it
                # closed out (the interrupt line, work.md) on the way down,
                # and with nobody draining the pipe a chatty run blocks on
                # write and the wait below never returns.
                async for raw in proc.stdout:
                    line = raw.decode("utf-8", errors="replace")
                    log.write(line)
                    runner.line_hook(suite, protocol, latest, line.rstrip("\n"))
                code = await proc.wait()
                latest = read_state(suite, protocol)
                latest.update(
                    status="interrupted", exit_code=code, pid=None,
                    interrupted=True,
                    finished=datetime.now().isoformat(timespec="seconds"))
                write_state(suite, protocol, latest)
                raise
        latest = read_state(suite, protocol)
        state.update(latest)
        stopped = bool(state.get("stop_requested") or state.get("interrupted"))
        state.update(
            status="interrupted" if stopped else ("finished" if code == 0 else "failed"),
            exit_code=code,
            pid=None,
            finished=datetime.now().isoformat(timespec="seconds"),
        )
        write_state(suite, protocol, state)
        if code == 0 and not state.get("run_dir"):
            # Every runner names the directory its child writes (the seed, or
            # the ``run:`` line), and ``is_pending`` reads a finished protocol
            # with no directory as one to start again — so a run that ended
            # well without naming one would be run again by the next
            # scheduler, and twice is what the claim exists to prevent.
            raise RuntimeError(
                f"[{protocol.id}] the child exited 0 but never named its run "
                f"directory; the runner's contract is broken")


async def run_many(suite: Suite, protocols: list[Protocol], *,
                   runner: Runner,
                   resume: tuple[str, str] | None = None) -> None:
    queue = asyncio.Queue()
    errors: list[tuple[str, Exception]] = []
    for protocol in protocols:
        queue.put_nowait(protocol)

    async def worker() -> None:
        while not queue.empty():
            try:
                protocol = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                await _one(suite, protocol, runner=runner, resume=resume)
            except ProtocolBusy:
                print(f"[{protocol.id}] skipped: claimed by another batch",
                      flush=True)
            except Exception as e:
                state = read_state(suite, protocol)
                state.update(
                    status="failed", pid=None,
                    finished=datetime.now().isoformat(timespec="seconds"),
                    error=f"{type(e).__name__}: {e}")
                write_state(suite, protocol, state)
                errors.append((protocol.id, e))
                print(f"[{protocol.id}] batch launch failed: {e}", file=sys.stderr)
            finally:
                queue.task_done()

    workers = [asyncio.create_task(worker())
               for _ in range(min(suite.max_runs, len(protocols)))]
    try:
        await asyncio.gather(*workers)
    except (KeyboardInterrupt, asyncio.CancelledError):
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        raise
    if errors:
        names = ", ".join(name for name, _ in errors)
        raise RuntimeError(f"{len(errors)} experiment(s) failed in the batch layer: {names}")


def runner_for(batch: str) -> Runner:
    """The ``Runner`` that executes this batch, from ``batches.RUNNERS``.

    The import happens here rather than at module level because every entry
    module imports this one; that is also why ``RUNNERS`` maps to a module name
    instead of the object.
    """
    from importlib import import_module

    if batch not in RUNNERS:
        raise ValueError(f"unknown batch {batch!r}")
    return import_module(f"experiments.batch.{RUNNERS[batch]}").RUNNER


def solver_version(executable: str) -> str:
    """The ProVerif release that will answer, or ``""`` if it cannot be asked.

    ``-help`` is the only invocation that prints the version banner. A missing
    or unreadable solver yields ``""``; the failure surfaces per run instead.
    """
    try:
        out = subprocess.run([executable, "-help"], capture_output=True,
                             text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    head = out.splitlines()[0] if out else ""
    m = re.search(r"(\d+\.\d+)", head)
    return m.group(1) if m else ""


def _scheduler_files(suite: Suite) -> list[Path]:
    """Every scheduler that has registered on this batch, alive or not."""
    return sorted(suite.state_root.glob("scheduler.*.json"))


@contextmanager
def scheduler_registered(suite: Suite):
    """Announce this scheduler process on the batch for as long as it runs.

    ``stop`` reads the file: a SIGINT to the scheduler is the whole-batch
    interrupt (its cancel path stops every child and starts no more), while
    a SIGINT per child leaves the scheduler free to start the next twenty.
    One file per scheduler, since two may share a batch's queue.
    """
    suite.state_root.mkdir(parents=True, exist_ok=True)
    path = suite.state_root / f"scheduler.{os.getpid()}.json"
    path.write_text(json.dumps({
        "pid": os.getpid(), "batch": suite.name,
        "started": datetime.now().isoformat(timespec="seconds"),
        "command": sys.argv}), encoding="utf-8")
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def stop_batch(suite: Suite, *, wait_s: float = 15.0) -> tuple[list[int], list[str]]:
    """Interrupt the whole batch: every live scheduler first, then any child
    whose scheduler is already gone. Returns (scheduler pids signalled,
    protocol ids signalled directly).
    """
    schedulers: list[int] = []
    for path in _scheduler_files(suite):
        try:
            pid = int(json.loads(path.read_text(encoding="utf-8")).get("pid"))
        except (ValueError, TypeError, json.JSONDecodeError, OSError):
            path.unlink(missing_ok=True)
            continue
        if not pid_alive(pid):
            path.unlink(missing_ok=True)       # a scheduler that died leaves its note
            continue
        os.kill(pid, signal.SIGINT)
        schedulers.append(pid)
    # A scheduler unwinds by interrupting its children and waiting for them;
    # give it that long before looking at the children ourselves.
    deadline = time.monotonic() + wait_s
    while schedulers and time.monotonic() < deadline \
            and any(pid_alive(p) for p in schedulers):
        time.sleep(0.2)
    orphans: list[str] = []
    for protocol in suite.protocols:
        state = read_state(suite, protocol)
        if not is_running(state):
            continue
        state["stop_requested"] = True
        write_state(suite, protocol, state)
        try:
            os.killpg(state["pid"], signal.SIGINT)
        except ProcessLookupError:      # exited between the read and here
            continue
        orphans.append(protocol.id)
    return schedulers, orphans


def protocol_by_id(suite: Suite, name: str) -> Protocol:
    for p in suite.protocols:
        if p.id == name:
            return p
    raise ValueError(f"unknown protocol {name!r} in batch {suite.name}")


#: How this is invoked, for ``--help`` and for the error messages that tell a
#: reader what to type. One entry point for every batch; which runner a
#: batch needs is ``batches.RUNNERS``.
PROG = "python -m experiments.batch"


def main() -> None:
    """Four commands and one argument: ``run``, ``status``, ``stop`` or
    ``resume`` a batch.

    ``run`` starts a batch but never repairs one: it stops if any protocol
    holds a run that did not finish, and ``status`` names that run so it can be
    continued with ``resume <batch> <protocol> --from-node <node>`` (under the
    batch's own settings) or deleted.
    """
    parser = argparse.ArgumentParser(prog=PROG)
    # `_child` is in the choices and out of the usage line: it is what `run`
    # spawns per protocol, not something to type.
    parser.add_argument("command",
                        choices=("run", "status", "stop", "resume", "_child"),
                        metavar="{run,status,stop,resume}",
                        help="run | status | stop | resume")
    parser.add_argument("batch", choices=sorted(BATCHES),
                        help="which experiment; defined in experiments/batches.py")
    # These two words are the whole of what crosses the process boundary into a
    # spawned child.
    parser.add_argument("protocol", nargs="?",
                        help="one protocol of the batch, by its id in "
                             "protocols.yaml; the whole batch when omitted")
    parser.add_argument("--run-name", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--from-node", default=None,
                        help="resume only: the node to re-enter the protocol's "
                             "interrupted run at, under this batch's own "
                             "settings (the run names it when it stops)")
    args = parser.parse_args()
    runner = runner_for(args.batch)
    try:
        suite = load_suite(args.batch)
    except MissingConfigError as e:
        # An unfilled config is an answer, not a crash: a stack trace would bury
        # the sentence naming the key. Same boundary as orrery/main.py::_CLI.
        sys.exit(f"error: {e}")
    if args.protocol and args.command != "_child":
        # Named on the command line, the batch is that one protocol for every
        # command: run starts it alone, status and stop look at it alone.
        try:
            suite = dataclasses.replace(
                suite, protocols=(protocol_by_id(suite, args.protocol),))
        except ValueError as e:
            sys.exit(f"error: {e}")

    if args.command == "_child":
        sys.exit(runner.child(suite, protocol_by_id(suite, args.protocol),
                              args.run_name, args.from_node))

    # Printed on every command because both are derived rather than written
    # down: where this batch writes, and which model will answer. Anyone
    # comparing numbers with the paper needs the model before the run starts.
    live = load_config(engine_layer(suite.config), overrides=suite.overrides,
                       require=False)
    print(f"batch {suite.name}: runs -> {suite.work_root}", flush=True)
    print(f"model: {live['llm']['backend']} / {live['llm']['model']}"
          + ("" if live["llm"]["model"] == PAPER_MODEL
             else f"   (the paper's runs used {PAPER_MODEL})"), flush=True)
    got = solver_version(live["proverif"]["executable"])
    print(f"solver: ProVerif {got or 'version unknown'}"
          + ("" if got == PAPER_PROVERIF
             else f"   (the paper's runs used {PAPER_PROVERIF})"), flush=True)

    if args.command == "status":
        print_status(suite, runner.artifact_status)
        return

    if args.command == "stop":
        schedulers, orphans = stop_batch(suite)
        print(f"interrupt sent to {len(schedulers)} scheduler(s)"
              + (f" (pid {', '.join(map(str, schedulers))})" if schedulers else "")
              + f" and {len(orphans)} experiment(s) running on their own"
              + (f": {', '.join(orphans)}" if orphans else ""))
        return

    if args.command == "resume":
        # One protocol, its recorded run, re-entered under the batch's own
        # settings. `orrery run --run-name/--from-node` cannot do this: it has
        # no way to take batches.py's overrides, so the continued run would
        # finish under the defaults and rewrite the run's config.yaml.
        if not args.protocol or not args.from_node:
            sys.exit(f"usage: {PROG} resume {suite.name} <protocol> "
                     f"--from-node <node>")
        protocol = suite.protocols[0]
        state = read_state(suite, protocol)
        run_name = state.get("run_name")
        if not run_name or not state.get("run_dir") \
                or not Path(state["run_dir"]).is_dir():
            sys.exit(f"error: {protocol.id} has no run to resume in this "
                     f"batch; `{PROG} run {suite.name} {protocol.id}` starts one")
        if is_running(state):
            sys.exit(f"error: {protocol.id} is still running (pid "
                     f"{state.get('pid')}); `{PROG} stop {suite.name}` first")
        try:
            preflight(suite)
        except MissingConfigError as e:
            sys.exit(f"error: {e}")
        try:
            with scheduler_registered(suite):
                asyncio.run(run_many(suite, [protocol], runner=runner,
                                     resume=(run_name, args.from_node)))
        except KeyboardInterrupt:
            print("\ninterrupt sent to the running experiment", file=sys.stderr)
            sys.exit(130)
        except (RuntimeError, ValueError) as e:
            sys.exit(f"error: {e}")
        return

    # `run`. A protocol that already holds an unfinished run stops the whole
    # command: continuing that run and throwing it away are worth different
    # amounts of money, so neither is a default.
    try:
        preflight(suite)                    # once, before the first child
    except MissingConfigError as e:
        sys.exit(f"error: {e}")
    # The rest of what every child needs, checked once here rather than
    # discovered by twenty children in parallel: a solver that cannot be run
    # fails each run after its model sessions have been paid for, and a corpus
    # path that is wrong kills each child before it has printed a run
    # directory, which used to block the batch for good (see below).
    if not got:
        sys.exit(f"error: proverif.executable "
                 f"{live['proverif']['executable']!r} cannot be run; nothing "
                 f"started")
    if not suite.lib_root.is_dir():
        sys.exit(f"error: paths.lib_root {suite.lib_root} is not a directory; "
                 f"nothing started")
    missing = [p.id for p in suite.protocols
               if not (suite.lib_root / p.path).is_dir()]
    if missing:
        sys.exit(f"error: protocols.yaml names directories the corpus lacks: "
                 f"{missing[:8]}{', ...' if len(missing) > 8 else ''}; nothing "
                 f"started")
    states = {p.id: read_state(suite, p) for p in suite.protocols}
    # The same rule is_pending applies: a protocol whose last attempt left
    # nothing on disk (it died before printing a run directory) is pending,
    # not blocked, or the batch could never be started again without editing
    # the state file by hand.
    blocked = [(p.id, got) for p in suite.protocols
               if not is_pending(states[p.id])
               and (got := report_status(states[p.id], runner.artifact_status))
               in ("interrupted", "failed")]
    if blocked:
        listed = ", ".join(f"{name} ({got})" for name, got in blocked[:8])
        sys.exit(
            f"error: {len(blocked)} protocol(s) hold a run that did not finish, "
            f"so nothing was started: {listed}"
            + (f", and {len(blocked) - 8} more" if len(blocked) > 8 else "")
            + f"\n  `{PROG} status {suite.name}` names the run each one "
              f"left. Continue one with `{PROG} resume {suite.name} <protocol> "
              f"--from-node <node>`, or delete its run directory and this "
              f"command will start it afresh.")
    protocols = [p for p in suite.protocols if is_pending(states[p.id])]
    if not protocols:
        print("nothing to start: every protocol has finished")
        return
    try:
        with scheduler_registered(suite):
            asyncio.run(run_many(suite, protocols, runner=runner))
    except KeyboardInterrupt:
        print("\ninterrupt sent to running experiments", file=sys.stderr)
