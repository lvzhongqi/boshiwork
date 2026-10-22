"""The engine entry point: one Run is one run of one protocol.

Headless callers use ``run()``, pure domain arguments. A host constructs
``Run``, subscribes to events on ``run.bus`` and interrupts or releases through
``run.control``, then awaits ``run.start()``.

Re-entry at from_node needs the earlier nodes' artifacts to be present; that
node and everything after it write new stage directories, so nothing is
overwritten. Run directories are immutable — a named run that already exists is
a FileExistsError (services/store/runs.py).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from orrery.modules.scoring import (
    PRODUCTS, score_assumptions_aligned, score_claims_aligned,
    score_principals_aligned, score_properties_aligned,
    score_results_aligned,
)
from orrery.modules.scoring.summary import public_alignment, score_row
from orrery.modules.scoring.symbols import (
    assumption_symbols, latest_alignment, property_symbols)
from orrery.pipeline.evaluation.principals import align_principals, alignment_paths
from orrery.pipeline.evaluation.symbols import align_references
from orrery.modules.document import resolve_subprotocol_name
from orrery.nodes.apply.realizers import VOCAB, subtype_is_noop
from orrery.nodes.base import CheckFailed, GapRaised, Node, NodeError, RunEnv
from orrery.pipeline.control import gaps
from orrery.infra.proverif.runner import solver_problem
from orrery.pipeline.config import MissingConfigError, load_config
from orrery.pipeline.control.interrupts import RunControl
from orrery.pipeline.table import build_table, index_of
from orrery.services.store.atomic import write_json
from orrery.services.events import (
    AwaitingApproval, EventBus, Interrupted, Invalidated, NodeFinished,
    NodeProgress, NodeScored, NodeStarted, RunFailed, RunFinished, RunStarted,
    SessionUsage,
)
from orrery.services import concurrency
from orrery.services.logs import to_file
from orrery.services.store import stages as stage_index
from orrery.services.store.layout import RunLayout
from orrery.services.store.runs import (
    LATEST, next_run_name, point_latest, protocol_id,
)
from orrery.services.transcript.writer import TranscriptWriter
from orrery.services.transcript.reader import TranscriptReader


def _leaves(e: BaseException) -> list[BaseException]:
    """The real exceptions inside a (possibly nested) group, in order.

    A node that fans out (scenarios, cells) fails inside a TaskGroup, and
    services/concurrency unwraps the group only while it holds a single
    exception, so several siblings failing at once arrive here as a group.
    """
    out: list[BaseException] = []
    def walk(x: BaseException) -> None:
        if isinstance(x, BaseExceptionGroup):
            for sub in x.exceptions:
                walk(sub)
        else:
            out.append(x)
    walk(e)
    return out


def _describe(e: BaseException) -> str:
    """One line naming what actually went wrong, groups flattened.

    ``str`` on a group names neither the error nor where it came from, so the
    distinct leaf messages are joined here in order, with a count when several
    siblings failed the same way. The location rides on ``RunFailed.where``
    instead, and is spelled into this line only when siblings failed in
    different places and one field cannot hold it.
    """
    leaves = _leaves(e)
    if len(leaves) == 1:
        return f"{type(leaves[0]).__name__}: {leaves[0]}"
    split = _origin(e) == ""
    def one(x: BaseException) -> str:
        w = concurrency.where(x)
        return (f"{type(x).__name__} at {w}: {x}" if w and split
                else f"{type(x).__name__}: {x}")
    seen: dict[str, int] = {}
    for leaf in leaves:
        seen[one(leaf)] = seen.get(one(leaf), 0) + 1
    parts = [m if n == 1 else f"{m}  [x{n}]" for m, n in seen.items()]
    return f"{len(leaves)} concurrent failures — " + " || ".join(parts)


def _origin(e: BaseException) -> str:
    """The step the failure came from, as an identity path, or "" when there is
    no single one: nothing claimed it (a failure on the run's serial spine,
    where the node name is the answer), or siblings failed in different
    places."""
    steps = {concurrency.where(x) for x in _leaves(e)}
    return steps.pop() if len(steps) == 1 else ""


def _documents_given(documents: dict) -> dict:
    """The caller's ``documents=`` argument, checked and normalised to
    ``{"main": Path, "refs": [Path]}``.

    Raises ValueError on a malformed dict and FileNotFoundError on a path that
    does not exist. Checked at construction rather than at load_document: the
    run directory, run.json and the ledger are all written before node 1 runs.
    """
    if not isinstance(documents, dict) or "main" not in documents:
        raise ValueError(
            'documents must be a dict with a "main" key: '
            '{"main": <path>, "refs": [<path>, ...]}, where main is the '
            'document being analysed and refs are the ones it cites')
    main = Path(documents["main"]).expanduser().resolve()
    if not main.is_file():
        raise FileNotFoundError(f"main document does not exist: {main}")
    refs = [Path(r).expanduser().resolve() for r in (documents.get("refs") or ())]
    for r in refs:
        if not r.is_file():
            raise FileNotFoundError(f"reference document does not exist: {r}")
    return {"main": main, "refs": refs}


@dataclass
class RunResult:
    """What one run produced: its verdict, its directory and its numbers."""

    # ok | check_failed | failed. check_failed = every node ran and one of them
    # answered "no" (cross_check against ground truth); failed = a node broke.
    status: str
    run_dir: Path
    metrics: dict = field(default_factory=dict)   # acc is present when cross_check ran
    node_statuses: dict[str, str] = field(default_factory=dict)
    failed_node: str | None = None
    failure: str = ""


class Run:
    """One run of one protocol. Construction is synchronous and free of side
    effects: parse the config, compute the paths, create the bus and the control
    handle. Every disk action is deferred to start()."""

    def __init__(
        self,
        protocol_name: str,              # protocol name (NSSK, EDHOC)
        protocol_dir: str | Path,        # protocol directory (corpus layout)
        config: dict | str | Path,       # user config, a path or a dict; required
        *,
        version: str | None = None,      # protocol version (draft-08, 8446), if any
        subprotocol: str | None = None,  # target; omitted needs a one-target bundle
        run_name: str | None = None,     # run directory; omitted allocates one
        documents: dict | None = None,   # {"main": path, "refs": [path]}
        assumptions: object = None,      # assumptions vocabulary: a path or a dict
        properties: object = None,       # properties vocabulary: as above
        claims: object = None,           # claims (goal × scenario): as above
        flow: object = None,             # mother model .pv, a path or the text
        principals: object = None,       # principals.json the flow is written on
        ground_truth: object = None,     # cross_check only runs when this is given
        from_node: str | None = None,    # resume here, reusing the earlier artifacts
        from_step: str | None = None,    # aim at a step path below the node
        to_node: str | None = None,      # stop once this node completes
        fork_from: str | None = None,    # seed upstream artifacts from another run
        table: list[Node] | None = None, # node-table injection point, for tests only
    ) -> None:
        self.protocol_dir = Path(protocol_dir).resolve()
        if not self.protocol_dir.is_dir():
            raise FileNotFoundError(f"protocol directory does not exist: {self.protocol_dir}")
        if not protocol_name:
            raise ValueError(
                "protocol_name is required: the run directory and run.json are "
                "named after it, and the protocol directory cannot supply it — "
                "its last segment is the protocol for academic/NSSK and the "
                "version for rfc/EDHOC/draft-08")
        self.protocol_name = protocol_name
        self.version = version
        self.subprotocol = resolve_subprotocol_name(self.protocol_dir, subprotocol)
        self.protocol_id = protocol_id(protocol_name, version, self.subprotocol)
        if config is None:
            raise ValueError(
                "config is required: pass a path or a dict; the built-in defaults are only placeholders")
        self.cfg = load_config(config)
        # The documents, when the caller names them rather than leaving them to
        # be found.
        self.documents = _documents_given(documents) if documents else None
        self.assumptions = assumptions
        self.properties = properties
        self.claims = claims
        # The dependency is one-way. A mother model needs the principals.json it
        # was written on: flow checks its stable value names and dependency
        # edges against that semantic inventory. Principals on its own is
        # allowed, and measures the flow extraction alone.
        if flow is not None and principals is None:
            raise ValueError(
                "flow supplied without principals: a mother model needs the "
                "principals.json carrying its stable values and dependency "
                "edges. Supply principals too "
                "(principals on its own is allowed, and leaves the flow model "
                "to be extracted)")
        self.flow = flow
        self.principals = principals
        self.ground_truth = ground_truth
        self.from_node = from_node
        # The aim, as a step path. A plain re-entry aims at the node itself, so
        # every level below asks one question instead of each having its own
        # reading of "nothing was aimed at".
        self.from_step = from_step or from_node
        self.fork_from = fork_from
        if from_step is not None and from_node is None:
            raise ValueError(
                f"from_step={from_step!r} needs from_node: the step says which "
                f"work is being re-done, and the node says where the pipeline "
                f"picks up in order to reach it")
        if fork_from is not None and from_node is None:
            raise ValueError(
                f"fork_from={fork_from!r} needs from_node: without a re-entry "
                f"point every node re-runs, so the copied artifacts would be "
                f"superseded before they were read")
        if from_node is not None and run_name is None and fork_from is None:
            raise ValueError(
                "from_node needs run_name: with no name a fresh run is allocated, "
                "and re-entering a run that has just been created finds no "
                "artifacts. Name the run to re-enter, or pass fork_from to seed "
                "a new one from it")
        self.table = table if table is not None else build_table()
        self.to_node = to_node
        if from_node is not None:
            # Rejected here, before start() has written config.yaml, moved the
            # latest pointer and bound the ledger of the run being re-entered.
            index_of(self.table, from_node)
        if to_node is not None:
            # index_of rejects an unknown name loudly; the ordering check keeps
            # an empty run from ever counting as ok.
            if from_node is not None and \
                    index_of(self.table, from_node) > index_of(self.table, to_node):
                raise ValueError(
                    f"to_node {to_node!r} precedes from_node {from_node!r}: "
                    f"no node would run")
            index_of(self.table, to_node)
        # The solver, checked before anything is written or paid for, whenever
        # a step up to the stop point runs it: up to it, not from the entry
        # point, because a gap can send the run back upstream to a step that
        # does. Left to the first call, a missing solver surfaces after the
        # flow model was bought, as the OS's "No such file or directory".
        stop = index_of(self.table, to_node) + 1 if to_node else len(self.table)
        if any(n.needs_solver for n in self.table[:stop]):
            exe = self.cfg["proverif"]["executable"]
            if (problem := solver_problem(exe)) is not None:
                raise MissingConfigError(
                    f"proverif.executable cannot run ProVerif: {problem}. Set "
                    f"it to the ProVerif binary, the file named proverif in "
                    f"the ProVerif distribution, as an absolute path or a name "
                    f"on PATH. Nothing was started, so nothing was spent")
        root = Path(self.cfg["paths"]["work_root"])
        # No name means a fresh one: a run directory is immutable, so repeated
        # runs stack up rather than overwrite (services/store/runs.py).
        if run_name == LATEST:
            raise ValueError(f"{LATEST!r} is the reserved name of the pointer to "
                             f"the newest run; pick another run name")
        self.layout = RunLayout(
            root, self.protocol_id,
            run_name or next_run_name(root, self.protocol_id, self.protocol_id))
        # Output channel and control surface: both exist from construction, so
        # the host can subscribe to or hold them before start().
        self.bus = EventBus()            # start() binds it to a path
        self.control = RunControl()

    @property
    def run_dir(self) -> Path:
        """This run's directory on disk."""
        return self.layout.run_dir

    def _seed_from_fork(self) -> None:
        """Copy the node directories strictly before ``from_node`` out of
        another run of this protocol, so this run starts where that one left off
        without touching it.

        The two runs then share no mutable state, and run.json's ``forked_from``
        is the only link between them. Raises FileNotFoundError for a missing
        source run and FileExistsError when this run's directory already exists.
        """
        src = RunLayout(self.layout.root, self.layout.protocol, self.fork_from)
        if not src.run_dir.is_dir():
            raise FileNotFoundError(
                f"fork source run {self.fork_from!r} does not exist: {src.run_dir}")
        if self.layout.run_dir.exists():
            raise FileExistsError(
                f"run {self.layout.run_name!r} already exists: {self.layout.run_dir}. "
                f"Forking writes a fresh run; pick an unused name, or re-enter "
                f"that run in place by dropping fork_from")
        upstream = [n.name for n in self.table[:index_of(self.table, self.from_node)]]
        live = stage_index.live(src.stages, "")
        self.layout.run_dir.mkdir(parents=True, exist_ok=True)
        for name in upstream:
            st = live.get(name)
            if st is None or not st.dir:
                continue
            # The directory keeps its name and its number, so the fork's own
            # numbering carries on from where the source left off and the two
            # runs' listings line up. Only what is current comes across: a fork
            # takes the state, not the source's dead ends.
            shutil.copytree(src.run_dir / st.dir, self.layout.run_dir / st.dir)
            # The whole subtree's index rows come with the directory, in the
            # source's order (parents precede children there): a scenario
            # stage carries its scenarios, apply points and goal families
            # under it, and a fork that re-enters after it finds them only
            # through the index.
            for sub in src.stages:
                if sub.dir == st.dir or sub.dir.startswith(st.dir + "/"):
                    self.layout.adopt(sub)

    async def start(self) -> RunResult:
        """Commit the run directory, bind the ledger, then walk the node table.

        Raises ValueError when manual mode has no subscriber to release its
        approvals, and FileExistsError when a named run already exists and is
        neither being re-entered nor forked from.
        """
        layout, cfg, bus = self.layout, self.cfg, self.bus
        if cfg["pipeline"]["mode"] == "manual" and not bus.has_subscribers:
            raise ValueError(
                "manual mode needs at least one event subscriber (a host): with nobody to "
                "see AwaitingApproval, nobody releases it and the run stops forever")
        if self.from_node is None and self.fork_from is None and layout.run_dir.exists():
            # Reached only when the caller chose the name; an allocated one is
            # free by construction.
            raise FileExistsError(
                f"run {layout.run_name!r} already exists: {layout.run_dir}. "
                f"Runs are never overwritten: omit the name to start a fresh "
                f"one, pass from_node to re-enter this one in place, or "
                f"fork_from to seed a new run from it")
        if self.fork_from is not None:
            self._seed_from_fork()
        # Keep the effective configuration beside the artifacts it produced.
        # RunLayout redacts credentials before the atomic write; ``cfg`` itself
        # stays untouched because the live clients still need the real key.
        layout.write_config(cfg)
        point_latest(layout.root, layout.protocol, layout.run_name)
        bus.bind(layout.events_path)
        # From here the run directory is committed, so this run's log can sit
        # beside its other traces. Opening the log creates the directory, which
        # is why the existence check above has to come first.
        with to_file(layout.run_log):
            return await self._execute()

    async def _execute(self) -> RunResult:
        """Walk the node table. Split out of start() so that everything it
        writes — including the way it fails or is interrupted — lands inside the
        run's own log file."""
        layout, cfg, bus = self.layout, self.cfg, self.bus
        self.control.bind(asyncio.get_running_loop(), asyncio.current_task())

        env = RunEnv(protocol_dir=self.protocol_dir, layout=layout, config=cfg,
                     protocol_id=self.protocol_id,
                     subprotocol=self.subprotocol,
                     documents_input=self.documents,
                     assumptions_input=self.assumptions,
                     properties_input=self.properties,
                     claims_input=self.claims,
                     flow_input=self.flow,
                     principals_input=self.principals,
                     ground_truth=self.ground_truth,
                     aim=self.from_step,
                     node_names=tuple(n.name for n in self.table),
                     model_driven_names=tuple(n.name for n in self.table
                                              if n.model_driven),
                     always_run_names=tuple(n.name for n in self.table
                                            if n.always_run))
        env.bus = bus
        rn = layout.run_name
        table = self.table
        from_node = self.from_node
        start = index_of(table, from_node) if from_node else 0

        result = RunResult(status="ok", run_dir=layout.run_dir)
        eval_tasks: set[asyncio.Task] = set()
        eval_jobs: dict[str, asyncio.Task] = {}

        def _schedule_score(node_name: str) -> None:
            """Score one finished node, off the node boundary when it needs a
            model call.

            Ordinary scores are millisecond pure functions and stay inline. The
            five listed here first need an alpha-renaming call, so they run
            beside the later nodes and are joined when the run itself closes.
            """
            if node_name not in {
                    "extract_principals", "extract_assumptions",
                    "extract_properties", "extract_claims", "aggregate"}:
                _score_node(node_name, env, bus)
                return
            here = layout.find_node_dir(node_name)
            if node_name == "extract_principals":
                work = _score_principals_node(env, bus, here)
            elif node_name in {"extract_assumptions", "extract_properties"}:
                work = _score_reference_node(node_name, env, bus, here)
            else:
                work = _score_dependent_node(node_name, env, bus, here,
                                             _alignment_jobs())
            task = asyncio.create_task(work,
                name=f"{layout.run_name}:{node_name}-evaluation")
            eval_tasks.add(task)
            eval_jobs[node_name] = task
            task.add_done_callback(eval_tasks.discard)

        def _alignment_jobs() -> list[asyncio.Task]:
            """The symbol alignments of assumptions and properties still in
            the air: scoring and cross_check both rename through them."""
            return [eval_jobs[n] for n in (
                "extract_assumptions", "extract_properties") if n in eval_jobs]

        async def _drain_scores() -> None:
            pending = list(eval_tasks)
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        meta = {"protocol_id": self.protocol_id,
                "protocol": self.protocol_name,
                "version": self.version,
                "protocol_dir": str(self.protocol_dir),
                "subprotocol": self.subprotocol,
                # Named documents are recorded as the paths they were, so a
                # finished run says what it read. Absent for a corpus entry,
                # whose documents the layout answers for.
                "documents": ({"main": str(self.documents["main"]),
                               "refs": [str(r) for r in self.documents["refs"]]}
                              if self.documents is not None else None),
                "ground_truth": (str(self.ground_truth)
                                 if self.ground_truth is not None else None),
                "assumptions": (str(self.assumptions)
                                if self.assumptions is not None else None),
                "properties": (str(self.properties)
                               if self.properties is not None else None),
                "claims": (str(self.claims)
                           if self.claims is not None else None),
                "flow": (str(self.flow)
                         if self.flow is not None else None),
                "principals": (str(self.principals)
                               if self.principals is not None else None),
                "run_name": layout.run_name,
                "started": datetime.now().isoformat(timespec="seconds"),
                # Both ends of what this run was asked to do: a reader opening
                # the run later cannot otherwise tell a run that was cut short
                # on purpose from one that stopped.
                "from_node": from_node, "to_node": self.to_node,
                "forked_from": self.fork_from,
                "nodes": result.node_statuses}

        def _flush(status: str) -> None:
            write_json(layout.run_json, {**meta, "status": status})

        async def _fail(node_name: str, reason: str, *, kind: str = "crash",
                        artifacts: list[str] | None = None,
                        where: str = "",
                        node_closed: bool = False) -> RunResult:
            """Close the run out. Shared by a node's own NodeError and by an
            exhausted gap-rejection limit, so both leave the same trail.

            kind="check" is the other case: the node ran to the end and its
            check says no. That node was closed out on the ledger when the
            check failed (``node_closed``), so only the run is left to close.
            A crash after a failed check names that check too: the run's one
            reason field would otherwise lose it."""
            status = "check_failed" if kind == "check" else "failed"
            reason = _with_check_failure(reason, kind)
            result.status = status
            result.failed_node = node_name
            result.failure = reason
            if not node_closed:
                result.node_statuses[node_name] = status
                bus.emit(NodeFinished(run=rn, node=node_name, status=status,
                                      artifacts=artifacts or []))
            bus.emit(RunFailed(run=rn, reason=reason, kind=kind, where=where))
            _flush(status)
            await _drain_scores()
            _read_metrics(layout, result)
            _write_journey(layout)
            return result

        # The first check that said no, as (node, reason). The run goes on to
        # the steps that exist to explain such a failure and closes as
        # check_failed once they are done.
        check_failure: tuple[str, str] | None = None

        def _with_check_failure(reason: str, kind: str) -> str:
            if check_failure is None or kind == "check":
                return reason
            return (f"{reason} (earlier, {check_failure[0]} did not pass: "
                    f"{check_failure[1]})")

        _flush("running")
        bus.emit(RunStarted(run=rn, from_node=from_node))
        names = [n.name for n in table]
        # to_node truncates the table's tail, so re-entry, archiving and the
        # ledger all behave identically on a partial run.
        end = index_of(table, self.to_node) + 1 if self.to_node else len(table)
        i = 0
        # Why each step is about to execute, recorded on its stage so a reader
        # of the run directory can see what sent the pipeline back and who
        # asked. Overwritten by the gap path when the pipeline sends itself back.
        cause = "rerun" if from_node else "initial"
        by = "user" if from_node else ""
        resume_at: str | None = None      # the one node a gap lets carry on its session

        async def _prepare(node: Node) -> None:
            """Allocate one node's stage and announce its start.

            Stage allocation stays serial even when the two independent
            extractors run together: the stage index has one writer, while the
            model sessions have no shared output and may overlap. In manual
            mode this also waits on the node's approval gate.
            """
            nonlocal resume_at
            if not node.always_run:
                prev = layout.find_node_dir(node.name)
                finished = prev is not None and node.is_done(env)
                if env.plan(node.name, prev, finished) == "carry":
                    bus.emit(NodeProgress(
                        run=rn, node=node.name,
                        text=f"carrying on in {prev.name}"))
                else:
                    where = layout.open_node(
                        node.name, cause=cause, by=by,
                        resume=node.name == resume_at)
                    if prev is not None:
                        bus.emit(Invalidated(run=rn, node=node.name,
                                             targets=[prev.name]))
                    bus.emit(NodeProgress(
                        run=rn, node=node.name,
                        text=f"writing to {where.name}"))
            # Consumed by whichever node opens next, always_run ones included:
            # left standing, the resume would reach the node after the one the
            # gap named.
            resume_at = None
            if cfg["pipeline"]["mode"] == "manual":
                bus.emit(AwaitingApproval(run=rn, node=node.name))
                await self.control.wait_approval(
                    cfg["pipeline"].get("approval_timeout_s"))
            here = layout.find_node_dir(node.name)
            bus.emit(NodeStarted(run=rn, node=node.name,
                                 dir=here.name if here else ""))

        async def _captured(node: Node) -> Exception | None:
            """Run a sibling to completion without cancelling the other one."""
            try:
                await node.run(env)
            except Exception as exc:                  # noqa: BLE001
                return exc
            return None

        try:
            while i < end:
                node = table[i]
                if check_failure is not None and not node.runs_after_check_failure:
                    # A step built on the failed one has nothing to build.
                    i += 1
                    continue
                if i < start and not node.always_run:
                    if not node.is_done(env):
                        raise RuntimeError(
                            f"node {node.name!r}, which precedes the re-entry point {from_node!r}, has "
                            f"no artifact: either the re-entry point is wrong, or the "
                            f"artifact was superseded and never re-run"
                        )
                    result.node_statuses[node.name] = "skipped"
                    i += 1
                    continue

                # These two readers depend on the same upstream artifacts
                # (flow, principals) and neither on the other, and they write
                # disjoint artifacts, so automatic mode opens both stages first
                # and overlaps the two model sessions. Manual mode stays serial
                # because each node has its own approval gate.
                #
                # So does a step that can report a gap. A gap rolls the whole
                # run back to an upstream node, which is a decision about the
                # serial spine; inside the TaskGroup below GapRaised is just
                # another exception and _captured would turn it into a plain
                # node failure. Neither of these two mounts the tool today, so
                # this only keeps the pairing from breaking the day one does.
                pair = (
                    cfg["pipeline"]["mode"] != "manual"
                    and node.name == "extract_assumptions"
                    and i + 1 < end
                    and table[i + 1].name == "extract_properties"
                    and not node.gap_targets
                    and not table[i + 1].gap_targets
                )
                if pair:
                    sibling = table[i + 1]
                    await _prepare(node)
                    await _prepare(sibling)
                    async with asyncio.TaskGroup() as tg:
                        first = tg.create_task(
                            _captured(node), name=f"{rn}:{node.name}")
                        second = tg.create_task(
                            _captured(sibling), name=f"{rn}:{sibling.name}")
                    outcomes = ((node, first.result()),
                                (sibling, second.result()))
                    for done, error in outcomes:
                        if error is not None:
                            continue
                        result.node_statuses[done.name] = "ok"
                        bus.emit(NodeFinished(
                            run=rn, node=done.name, status="ok",
                            artifacts=done.artifacts(env)))
                        _schedule_score(done.name)
                    _flush("running")
                    failed = [(done, error) for done, error in outcomes
                              if error is not None]
                    if failed:
                        failed_node, error = failed[0]
                        if len(failed) > 1:
                            # Both siblings ran to completion, so both failures
                            # are real and only one field holds the reason.
                            # Grouped rather than dropped: _describe and
                            # _origin already flatten a group, and the second
                            # exception would otherwise leave no trace at all.
                            error = BaseExceptionGroup(
                                "both document readers failed",
                                [e for _, e in failed])
                            for other, _ in failed[1:]:
                                # _fail and the crash path below close out
                                # one node; the ledger (and the console
                                # reading it) has to hear about the other.
                                result.node_statuses[other.name] = "failed"
                                bus.emit(NodeFinished(
                                    run=rn, node=other.name, status="failed",
                                    artifacts=[]))
                        if all(isinstance(e, NodeError) for _, e in failed):
                            return await _fail(
                                failed_node.name,
                                str(error) if len(failed) == 1
                                else _describe(error),
                                where=_origin(error))
                        result.status = "failed"
                        result.failed_node = failed_node.name
                        result.failure = _describe(error)
                        result.node_statuses[failed_node.name] = "failed"
                        logging.getLogger(__name__).error(
                            "%s crashed", failed_node.name,
                            exc_info=(type(error), error, error.__traceback__))
                        bus.emit(NodeFinished(
                            run=rn, node=failed_node.name, status="failed"))
                        bus.emit(RunFailed(
                            run=rn, reason=result.failure,
                            where=_origin(error)))
                        _flush("failed")
                        await _drain_scores()
                        _write_journey(layout)
                        raise error
                    i += 2
                    continue

                await _prepare(node)
                if node.name == "cross_check":
                    # It pairs cells after renaming through the symbol
                    # alignments, which run beside the nodes; a failed one is
                    # the node's to report, not this loop's.
                    await asyncio.gather(*_alignment_jobs(),
                                         return_exceptions=True)
                try:
                    await node.run(env)
                    # The aim is not cleared by hand: a node after the aimed-at
                    # one finds its own earlier work already stale, because its
                    # input was written again.
                    result.node_statuses[node.name] = "ok"
                    bus.emit(NodeFinished(run=rn, node=node.name, status="ok",
                                          artifacts=node.artifacts(env)))
                    _schedule_score(node.name)
                    _flush("running")
                    i += 1
                except GapRaised as raised:
                    upstream = names[:i]
                    verdict, reason = gaps.process(env, raised, upstream)
                    if verdict == "exhausted":
                        return await _fail(node.name, reason)
                    if verdict == "rejected":
                        # The diagnosis is already back in the reporter's
                        # transcript, so re-running this node resumes from there.
                        continue
                    # Accepted: go back to the target and run forward again.
                    # Nothing is superseded here — the steps in between keep
                    # their directories and stop being current the moment the
                    # target writes a newer one (services/store/stages.live).
                    # The target carries on its own session.
                    t_idx = names.index(raised.gap.target)
                    for n in names[t_idx:]:
                        result.node_statuses.pop(n, None)
                    if (check_failure is not None
                            and names.index(check_failure[0]) >= t_idx):
                        check_failure = None
                    cause, by = "gap", node.name
                    env.aim = raised.gap.target
                    resume_at = raised.gap.target
                    start = min(start, t_idx)
                    i = t_idx
                    _flush("running")
                except CheckFailed as e:
                    # The node ran to the end and its check said no. It is
                    # closed out now, reason on the ledger, and the loop goes
                    # on to the steps that exist to explain such a failure
                    # (runs_after_check_failure). They run the way every step
                    # does — own stage, approval gate, events, score — and one
                    # that breaks fails the run like any other step. The run
                    # closes as check_failed after the loop.
                    if check_failure is None:
                        check_failure = (node.name, str(e))
                    result.node_statuses[node.name] = "check_failed"
                    bus.emit(NodeProgress(run=rn, node=node.name,
                                          text=f"did not pass: {e}"))
                    bus.emit(NodeFinished(run=rn, node=node.name,
                                          status="check_failed",
                                          artifacts=_artifacts_of(node, env)))
                    _flush("running")
                    i += 1
                except NodeError as e:
                    # A node that fans out raises this from inside a branch too
                    # (repair rounds exhausted on one goal family), so the
                    # location has to be recovered the same way as for a crash.
                    return await _fail(node.name, str(e), where=_origin(e))
                except Exception as e:      # noqa: BLE001
                    # Exceptions other than NodeError (a 5xx from the model
                    # service, a programming error) are closed out too, or
                    # run.json would sit at "running" forever and leave no way
                    # to tell alive from dead.
                    result.status = "failed"
                    result.failed_node = node.name
                    result.failure = _with_check_failure(_describe(e), "crash")
                    result.node_statuses[node.name] = "failed"
                    # The traceback, into the run's own log while its handler is
                    # still attached. The re-raise below leaves this scope, so
                    # without this line run.log holds the one-line reason and
                    # nothing to debug from.
                    logging.getLogger(__name__).error(
                        "%s crashed", node.name, exc_info=True)
                    bus.emit(NodeFinished(run=rn, node=node.name, status="failed"))
                    bus.emit(RunFailed(run=rn, reason=result.failure,
                                       where=_origin(e)))
                    _flush("failed")
                    await _drain_scores()
                    _write_journey(layout)
                    raise
            if check_failure is not None:
                return await _fail(*check_failure, kind="check",
                                   node_closed=True)
        except asyncio.CancelledError:
            for task in eval_tasks:
                task.cancel()
            bus.emit(Interrupted(run=rn))
            _flush("interrupted")
            # work.md is regenerated on every other way out; leaving it stale
            # here would have it claim the state before the interrupt.
            _write_journey(layout)
            raise
        await _drain_scores()
        bus.emit(RunFinished(run=rn))
        _read_metrics(layout, result)
        _flush("ok")
        _write_journey(layout)
        return result


async def run(
    protocol_name: str,              # protocol name (NSSK, EDHOC)
    protocol_dir: str | Path,        # protocol directory (corpus layout)
    config: dict | str | Path,       # user config, a path or a dict; required
    *,
    version: str | None = None,      # protocol version (draft-08, 8446), if any
    subprotocol: str | None = None,  # target; omitted needs a one-target bundle
    run_name: str | None = None,     # run directory; omitted allocates one
    documents: dict | None = None,   # {"main": path, "refs": [path]}
    assumptions: object = None,      # assumptions vocabulary: a path or a dict
    properties: object = None,       # properties vocabulary: as above
    claims: object = None,           # claims (goal × scenario): as above
    flow: object = None,             # mother model .pv, a path or the text
    principals: object = None,       # principals.json the flow is written on
    ground_truth: object = None,     # cross_check only runs when this is given
    from_node: str | None = None,    # resume here, reusing the earlier artifacts
    from_step: str | None = None,    # aim at a step path below the node
    to_node: str | None = None,      # stop once this node completes
    fork_from: str | None = None,    # seed upstream artifacts from another run
) -> RunResult:
    """The headless entry point: pure domain arguments. To subscribe to events or
    to interrupt and release, use the Run object."""
    return await Run(
        protocol_name, protocol_dir, config,
        version=version, subprotocol=subprotocol, run_name=run_name,
        documents=documents,
        assumptions=assumptions, properties=properties, claims=claims,
        flow=flow, principals=principals,
        ground_truth=ground_truth, from_node=from_node, from_step=from_step,
        to_node=to_node,
        fork_from=fork_from,
    ).start()


def _artifacts_of(node: Node, env: RunEnv) -> list[str]:
    """A node's artifacts, best effort: naming them is a courtesy to the reader
    and must never turn one failure into a different one."""
    try:
        return node.artifacts(env)
    except Exception:                            # noqa: BLE001
        return []


def _score_node(node_name: str, env: RunEnv, bus) -> None:
    """Score this step's product against the corpus, write it under the run's
    ``eval/`` directory and say the numbers on the bus.

    Here rather than in a node so that a node cannot reach the answers: the
    ground-truth handle is the orchestrator's and this runs after ``node.run``
    has returned. Nothing reads the score back — it is not in RunEnv, no repair
    round sees it, and it gates nothing.

    Silent when the step has no product the corpus answers, the run has no
    corpus, or the product was supplied to the step. A failure in here is
    logged and dropped rather than turning a finished run into a failed one.
    """
    spec = PRODUCTS.get(node_name)
    if spec is None or env.ground_truth is None or node_name in env.pinned():
        return
    try:
        here = env.layout.find_node_dir(node_name)
        product = (here / spec.product) if here else None
        if product is None or not product.is_file():
            return                            # no such file on this path
        gold_path = Path(env.ground_truth) / spec.gold if spec.gold else None
        if gold_path is not None and not gold_path.is_file():
            return                            # the corpus does not answer this one
        args = [_read_json(product),
                _read_json(gold_path) if gold_path else None]
        for extra_product, extra_gold in spec.also:
            args += [_read_json(here / extra_product),
                     _read_json(Path(env.ground_truth) / extra_gold)]
        for other in spec.needs:
            o_spec, o_dir = PRODUCTS[other], env.layout.find_node_dir(other)
            args += [_read_json(o_dir / o_spec.product),
                     _read_json(Path(env.ground_truth) / o_spec.gold)]
        score = spec.fn(*args)
        write_json(env.layout.run_dir / "eval" / f"{here.name[:2]}_{spec.slug}.json",
                   score)
        _write_eval_summary(env)
        if bus is not None:
            bus.emit(NodeScored(run=env.layout.run_name, node=node_name,
                                slug=spec.slug, num=score["num"],
                                den=score["den"], extra=score["extra"]))
    except Exception:                            # noqa: BLE001
        logging.getLogger(__name__).warning(
            "scoring %s against the corpus failed", node_name, exc_info=True)


async def _score_principals_node(env: RunEnv, bus, here: Path | None) -> None:
    """Align and score principals in the evaluation domain, never in the node.

    ``here`` is captured when the node finishes. A later gap may create another
    principals directory while this call is in flight, so only the score whose
    directory is still current emits a live badge on the bus.
    """
    node_name = "extract_principals"
    spec = PRODUCTS[node_name]
    if (here is None or env.ground_truth is None
            or node_name in env.pinned()):
        return
    product = here / spec.product
    gold_path = Path(env.ground_truth) / spec.gold
    if not product.is_file() or not gold_path.is_file():
        return

    prefix = here.name[:2]
    eval_dir = env.layout.run_dir / "eval"
    alignment_path, transcript_path = alignment_paths(eval_dir, prefix)
    try:
        candidate, gold = _read_json(product), _read_json(gold_path)
        alignment, maps = await align_principals(
            env.llm(), candidate=candidate, gold=gold,
            writer=TranscriptWriter(transcript_path),
            model=env.config["llm"].get("model", "?"),
            lang=env.config.get("prompt_lang", "en"))
        if bus is not None:
            reader = TranscriptReader(transcript_path)
            tokens_in, tokens_out = reader.usage_total()
            rounds = sum(1 for row in reader.entries()
                         if row.get("t") in ("assistant", "rejected"))
            bus.emit(SessionUsage(
                run=env.layout.run_name, node=node_name, rounds=rounds,
                input_tokens=tokens_in, output_tokens=tokens_out))
        score = score_principals_aligned(candidate, gold, maps)
        write_json(alignment_path, {
            "status": "ok",
            **alignment,
        })
        write_json(eval_dir / f"{prefix}_{spec.slug}.json", score)
        _write_eval_summary(env)
        if bus is not None and env.layout.find_node_dir(node_name) == here:
            bus.emit(NodeScored(run=env.layout.run_name, node=node_name,
                                slug=spec.slug, num=score["num"],
                                den=score["den"], extra=score["extra"],
                                alignment_status="ok",
                                alignment=[
                                    {"candidate": row["candidate"],
                                     "gold": row["gold"]}
                                    for row in (
                                        alignment["principal_mappings"]
                                        + alignment["symbol_mappings"])
                                ]))
    except Exception as exc:                       # noqa: BLE001
        # Evaluation is non-gating, but its own failure is durable and loud.
        write_json(alignment_path, {
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "principal_mappings": [],
            "symbol_mappings": [],
        })
        _write_eval_summary(env)
        if bus is not None and env.layout.find_node_dir(node_name) == here:
            bus.emit(NodeProgress(
                run=env.layout.run_name, node=node_name,
                text=f"principals symbol alignment failed: "
                     f"{type(exc).__name__}: {exc}"))
        logging.getLogger(__name__).warning(
            "scoring extract_principals against the corpus failed", exc_info=True)


async def _score_reference_node(node_name: str, env: RunEnv, bus,
                                here: Path | None) -> None:
    """Align the free model references in an assumptions or properties product
    against the corpus, then score it. Failures are recorded in the alignment
    file and logged, never raised.

    The alignment is the one evaluation product the run reads back:
    cross_check renames through it before pairing cells, and waits for it."""
    spec = PRODUCTS[node_name]
    if (here is None or env.ground_truth is None
            or node_name in env.pinned()):
        return
    product, gold_path = here / spec.product, Path(env.ground_truth) / spec.gold
    if not product.is_file() or not gold_path.is_file():
        return
    prefix, eval_dir = here.name[:2], env.layout.run_dir / "eval"
    stem = eval_dir / f"{prefix}_{spec.slug}_alignment"
    alignment_path, transcript_path = stem.with_suffix(".json"), stem / "transcript.jsonl"
    collector = (assumption_symbols if node_name == "extract_assumptions"
                 else property_symbols)
    try:
        candidate, gold = _read_json(product), _read_json(gold_path)
        alignment, mapping = await align_references(
            env.llm(), kind=spec.slug, candidate=candidate, gold=gold,
            candidate_symbols=collector(candidate), gold_symbols=collector(gold),
            writer=TranscriptWriter(transcript_path),
            model=env.config["llm"].get("model", "?"),
            lang=env.config.get("prompt_lang", "en"))
        score = (score_assumptions_aligned(candidate, gold, mapping)
                 if node_name == "extract_assumptions"
                 else score_properties_aligned(candidate, gold, mapping))
        write_json(alignment_path, {"status": "ok", **alignment})
        write_json(eval_dir / f"{prefix}_{spec.slug}.json", score)
        _write_eval_summary(env)
        if bus is not None:
            reader = TranscriptReader(transcript_path)
            tokens_in, tokens_out = reader.usage_total()
            rounds = sum(1 for row in reader.entries()
                         if row.get("t") in ("assistant", "rejected"))
            bus.emit(SessionUsage(run=env.layout.run_name, node=node_name,
                                  rounds=rounds, input_tokens=tokens_in,
                                  output_tokens=tokens_out))
        if bus is not None and env.layout.find_node_dir(node_name) == here:
            bus.emit(NodeScored(
                run=env.layout.run_name, node=node_name, slug=spec.slug,
                num=score["num"], den=score["den"], extra=score["extra"],
                alignment_status="ok",
                alignment=[{"candidate": r["candidate"], "gold": r["gold"]}
                           for r in alignment["mappings"]]))
    except Exception as exc:                       # noqa: BLE001
        write_json(alignment_path, {
            "status": "failed", "error": f"{type(exc).__name__}: {exc}",
            "mappings": [],
        })
        _write_eval_summary(env)
        if bus is not None and env.layout.find_node_dir(node_name) == here:
            bus.emit(NodeProgress(
                run=env.layout.run_name, node=node_name,
                text=f"{spec.slug} symbol alignment failed: "
                     f"{type(exc).__name__}: {exc}"))
        logging.getLogger(__name__).warning(
            "scoring %s against the corpus failed", node_name, exc_info=True)


async def _score_dependent_node(node_name: str, env: RunEnv, bus,
                                here: Path | None,
                                dependencies: list[asyncio.Task]) -> None:
    """Score claims or verdicts once the assumptions and properties symbol
    alignments they reuse have finished. ``dependencies`` are those alignment
    tasks; their failures are tolerated and surface as a missing mapping."""
    if dependencies:
        await asyncio.gather(*dependencies, return_exceptions=True)
    spec = PRODUCTS[node_name]
    if (here is None or env.ground_truth is None
            or node_name in env.pinned()):
        return
    try:
        product, gold_path = here / spec.product, Path(env.ground_truth) / spec.gold
        if not product.is_file() or not gold_path.is_file():
            return
        args = [_read_json(product), _read_json(gold_path)]
        for extra_product, extra_gold in spec.also:
            args += [_read_json(here / extra_product),
                     _read_json(Path(env.ground_truth) / extra_gold)]
        for other in spec.needs:
            o_spec, o_dir = PRODUCTS[other], env.layout.find_node_dir(other)
            args += [_read_json(o_dir / o_spec.product),
                     _read_json(Path(env.ground_truth) / o_spec.gold)]
        eval_dir = env.layout.run_dir / "eval"
        pinned = env.pinned()
        amap = ({} if "extract_assumptions" in pinned
                else latest_alignment(eval_dir, "assumptions")[0])
        pmap = ({} if "extract_properties" in pinned
                else latest_alignment(eval_dir, "properties")[0])
        score = (score_claims_aligned(*args, amap, pmap,
                                      instance_of=VOCAB.instance_of,
                                      is_noop=subtype_is_noop)
                 if node_name == "extract_claims"
                 else score_results_aligned(*args, amap, pmap,
                                            instance_of=VOCAB.instance_of))
        write_json(eval_dir / f"{here.name[:2]}_{spec.slug}.json", score)
        _write_eval_summary(env)
        if bus is not None and env.layout.find_node_dir(node_name) == here:
            bus.emit(NodeScored(run=env.layout.run_name, node=node_name,
                                slug=spec.slug, num=score["num"],
                                den=score["den"], extra=score["extra"]))
    except Exception as exc:                       # noqa: BLE001
        if bus is not None and env.layout.find_node_dir(node_name) == here:
            bus.emit(NodeProgress(
                run=env.layout.run_name, node=node_name,
                text=f"{spec.slug} scoring could not use the shared symbol "
                     f"alignment: {type(exc).__name__}: {exc}"))
        logging.getLogger(__name__).warning(
            "scoring %s against the corpus failed", node_name, exc_info=True)


def _read_json(path: Path):
    import json as _json
    return _json.loads(Path(path).read_text(encoding="utf-8"))


def _write_eval_summary(env: RunEnv) -> None:
    """The one file an experiment table reads: every product's numbers, no
    detail. Rewritten after each score, so an interrupted run has one too."""
    eval_dir = env.layout.run_dir / "eval"
    rows = {}
    for name, spec in PRODUCTS.items():
        # Keyed by step, not by product name: every reader of this file has a
        # step in hand and would otherwise need a second table to get back from
        # a product to the step that wrote it. The slug rides along.
        if name in env.pinned():
            rows[name] = {"slug": spec.slug, "supplied": True}
            continue
        hit = sorted(eval_dir.glob(f"*_{spec.slug}.json"))
        rows[name] = (score_row(spec.slug, _read_json(hit[-1]))
                      if hit else None)
        if name in {"extract_principals", "extract_assumptions",
                    "extract_properties"}:
            alignments = sorted(eval_dir.glob(f"*_{spec.slug}_alignment.json"))
            if alignments:
                public = public_alignment(_read_json(alignments[-1]))
                if rows[name] is None:
                    rows[name] = {"slug": spec.slug, "alignment": public}
                else:
                    rows[name]["alignment"] = public
    write_json(eval_dir / "summary.json",
               {"protocol_id": env.protocol_id,
                "run": env.layout.run_name, "products": rows})


def _write_journey(layout: RunLayout) -> None:
    """Write the ledger's projections as a run finishes: work.md, what happened
    in words, and repair.json, how many times each session had to submit again.

    Both are functions of events.jsonl alone and can be regenerated for any run
    on disk. An error in a projector never affects the run result."""
    try:
        from orrery.pipeline.journey import generate
        generate(layout.run_dir)
    except Exception:                            # noqa: BLE001
        logging.getLogger(__name__).warning("work.md generation failed", exc_info=True)
    from orrery.pipeline.repair import write as write_repair
    write_repair(layout.run_dir)


def _read_metrics(layout: RunLayout, result: RunResult) -> None:
    """Carry the cross_check report's metrics into ``result``, including the
    case where a mismatch was written out before the error was raised.

    ``has`` comes first because cross_check.json is that node's own artifact: a
    run that never reached the step has no current cross_check directory, and
    asking layout for the path would raise instead of saying there are no
    metrics yet."""
    if not layout.has("cross_check", "cross_check.json"):
        return
    import json as _json
    rep = _json.loads(layout.cross_check_json.read_text())
    result.metrics = {"acc": rep["acc"],
                      "match_count": rep["cases_matched"],
                      "total_count": rep["cases_compared"]}
