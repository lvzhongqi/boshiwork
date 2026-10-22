"""The host base class, which a front end (the CLI, the web console) subclasses
by implementing the two abstract methods.

This is where expert and pipeline are joined, since neither knows about the
other: a plan comes out of an expert session, estimate prices it, the user
confirms, fixes executes it, and the host re-runs.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path

from orrery.agent.tools.expert_tools import FixPlan
from orrery.api.truth import stow_ground_truth
from orrery.expert.session import (
    ExpertReply, ExpertSession, executed_notice,
)
from orrery.infra.llm.factory import build_chat_client
from orrery.pipeline.control import fixes
from orrery.pipeline.config import load_config
from orrery.pipeline.control.fixes import FixCost
from orrery.pipeline.main import Run
from orrery.services.events import AwaitingConfirm, Event, EventBus


#: The supplied artifacts whose recorded path must still resolve. A path that
#: no longer does is an error and not a None: silently dropping one flips the
#: re-run from "was handed this" to "extracts its own", which is a different
#: measurement wearing the same run name.
_RECORDED_PATHS = ("assumptions", "properties", "claims", "flow", "principals")


def asked_of(run_meta: dict) -> dict:
    """What a run was asked, as the kwargs that ask it again — everything a
    re-entry must restate, in one list.

    One list because dropping any one of them is silent and each fails
    differently: a lost `documents` sends load_document off to look for a
    corpus layout under a reader's own folder, a lost `subprotocol` reads a
    different sub-protocol, a lost `ground_truth` turns the cross-check off,
    a lost `to_node` buys every node the run was told to stop before. Written
    once here, so the next kind of supplied input is added in one place rather
    than in however many callers happen to rebuild a run.

    `documents` and `ground_truth` go over as recorded: Run and
    stow_ground_truth are the ones that open them, and both raise on their own.
    """
    out = {"version": run_meta.get("version") or None,
           "subprotocol": run_meta.get("subprotocol") or None,
           "documents": run_meta.get("documents") or None,
           # Where the run was told to stop is half of what it was asked (the
           # console shows it as the run's range); a re-entry that forgot it
           # would run past the end and bill for nodes nobody asked for.
           "to_node": run_meta.get("to_node") or None}
    gt = run_meta.get("ground_truth")
    out["ground_truth"] = Path(gt) if gt else None
    for which in _RECORDED_PATHS:
        recorded = run_meta.get(which)
        if recorded is None:
            out[which] = None
            continue
        if not Path(recorded).exists():
            raise FileNotFoundError(
                f"run.json records {which}={recorded!r} but the path does not "
                f"resolve; the corpus moved, so re-point it before re-running")
        out[which] = Path(recorded)
    return out


class Host(ABC):
    """One host serves one interactive session: it owns the run, the expert
    session and the event bus. A subclass supplies only the human interface."""

    def __init__(self, config=None, overrides=None) -> None:
        self.cfg = load_config(config, overrides)
        self._run: Run | None = None
        self._session: ExpertSession | None = None
        self._bus: EventBus | None = None
        # One chat message at a time: pricing, halting, archiving and
        # restarting are what a second concurrent caller would corrupt.
        self._chat_turn = asyncio.Lock()

    @property
    def current(self) -> Run | None:
        """The run this host built last, executing or not: the one a fix
        re-runs under, which the registry never saw start. Whoever asks
        "is anything running under this host" asks here, not the registry's
        own copy of the first run."""
        return self._run

    # The front-end adaptation surface, implemented by subclasses.
    @abstractmethod
    def on_event(self, event: Event) -> None: ...

    @abstractmethod
    async def confirm(self, plan: FixPlan, cost: FixCost) -> bool: ...

    # The machinery, used directly by subclasses.
    def make_run(self, protocol_name, protocol_dir, **kw) -> Run:
        """Construct a run and wire it up, subscribing this host to its bus.
        Starting is left to the caller, which wants run.control in hand first.

        A run re-entering a ledger this host already has bound takes over that
        bus: one ledger, one bus, since two of them keep separate ``_seq``
        counters whose numbers collide. This is the one place a run is built,
        so the corpus answers get stowed beside it here, before start().
        """
        kw.setdefault("config", self.cfg)
        run = Run(protocol_name, protocol_dir, **kw)
        stow_ground_truth(run.layout.root, run.layout.protocol,
                          kw.get("ground_truth"))
        if self._bus is not None and self._bus.path == run.layout.events_path:
            run.bus = self._bus          # already carries on_event, from attach()
        else:
            run.bus.subscribe(self.on_event)
            self._bus = run.bus
        self._run = run
        return run

    async def start_run(self, protocol_name, protocol_dir, **kw):
        """make_run plus start(), for a caller that does not need the control
        handle first."""
        return await self.make_run(protocol_name, protocol_dir, **kw).start()

    @property
    def control(self):
        """The current run's control handle: interrupt, and manual release."""
        return self._run.control if self._run is not None else None

    def attach(self, run_dir: str | Path) -> ExpertSession:
        """Open an expert session on a run, wired to the same event stream the
        pipeline writes, and return it.

        A run this host is already executing keeps its own bus, since a second
        bus on the same events.jsonl hands out colliding ``seq`` numbers.
        Otherwise the ledger is bound here, without which a durable emit raises
        and the expert cannot speak while no pipeline is running.
        """
        run_dir = Path(run_dir)
        bus = self._run.bus if self._run is not None else EventBus()
        if self._run is None:
            bus.bind(run_dir / "events.jsonl")
            bus.subscribe(self.on_event)
        self._session = ExpertSession(run_dir, self.cfg,
                                      build_chat_client(self.cfg["llm"]),
                                      bus=bus)
        self._bus = bus
        return self._session

    async def chat(self, user_text: str) -> str:
        """The full loop for one user message: a question is answered directly,
        a plan goes through price, confirm, execute and re-run. Raises when no
        run is attached.

        Serialised end to end, the re-run included, so a queued caller waits
        out a fix instead of reading artifacts while this turn archives them.
        The lock is taken before ExpertSession._turn, never the other way round.
        """
        if self._session is None:
            raise RuntimeError("attach a run first")
        async with self._chat_turn:
            return await self._chat(self._session, user_text)

    async def _chat(self, s: ExpertSession, user_text: str) -> str:
        reply: ExpertReply = await s.handle(user_text)
        if reply.kind != "plan":
            return reply.display
        plan = reply.plan
        # The proposing turn cost tokens too, so every way out of this branch
        # carries the same cost tail as a plain reply.
        tail = f"\n\n{reply.cost}" if reply.cost else ""
        # The index this session caches was read at attach time; a fix from an
        # earlier turn, or a run this host executed since, has grown it.
        s.layout.reload()
        try:
            cost = fixes.estimate(s.layout, plan)
        except Exception as e:
            # The plan leaves an unanswered tool_use hanging; unbalanced, the
            # next message resuming the session is rejected by the API.
            s.resolve_plan(f"plan could not be priced ({e}); not executed.")
            return f"plan could not be priced: {e}{tail}"
        try:
            if cost.heavy:
                # Through the bus rather than straight to on_event: an out-of-
                # process front end reads the stream and nothing else.
                self.emit(AwaitingConfirm(
                    run=s.layout.run_name, node="expert",
                    plan_digest=f"{plan.step}/{plan.mode}: {plan.message[:80]}",
                    cost_digest=f"supersedes {len(cost.superseded)} step(s), "
                                f"re-runs {len(cost.reruns)} step(s)"))
                if not await self.confirm(plan, cost):
                    s.resolve_plan("the user cancelled the plan; not executed.")
                    return f"cancelled; artifacts untouched.{tail}"
            # Stop, supersede, restart, in that order, and only after the user
            # has said yes: a cancelled plan stops nothing.
            halted = await self._halt_run()
            # The run that was just stopped wrote to the index while it unwound.
            s.layout.reload()
            # Read before execute, which archives the artifacts: losing the
            # sub-protocol, version or ground truth here makes the re-run load
            # the wrong document and silently turns the cross-check off.
            run_meta = self._run_meta()
            asked = asked_of(run_meta)
            try:
                from_node = fixes.execute(s.layout, plan)
            except Exception as e:
                s.resolve_plan(f"plan execution failed ({e}).")
                raise
            # The priced list is the only thing that tells the model which of
            # the artifacts it has already read are now stale.
            s.resolve_plan(executed_notice(from_node, cost.superseded))
        except asyncio.CancelledError:
            # Stopped while the plan waited for a decision or the run was
            # unwinding: the proposal's tool_use still has to be answered, or
            # every later message is refused with "a fix is still waiting"
            # and nothing on the page can clear it. Idempotent after execute.
            s.resolve_plan("the question was stopped before the plan was "
                           "decided; not executed.")
            raise
        rerun_cfg = load_config(self.cfg,
                                {"paths": {"work_root": str(s.layout.root)}})
        r = await self.make_run(
            run_meta["protocol"], s.protocol_dir, config=rerun_cfg, **asked,
            run_name=s.layout.run_name, from_node=from_node).start()
        # A check that says no is a result, not a breakage, so the two
        # outcomes are worded apart.
        outcome = ("succeeded" if r.status == "ok"
                   else ("differs from the corpus: " if r.status == "check_failed"
                         else "failed: ") + r.failure)
        return (f"fix executed ({plan.rationale or plan.step})"
                f"{'; the run in flight was interrupted first' if halted else ''}"
                f"; re-run {outcome}.{tail}")

    @property
    def bus(self) -> EventBus | None:
        """The run's event stream as this host holds it: the one bound when a
        run was attached or started here, or None before either."""
        return self._bus or getattr(self._run, "bus", None)

    def emit(self, event: Event) -> None:
        """Put a host-side event on the run's stream, falling back to
        delivering it straight to this host when there is no bus to write
        to."""
        bus = self.bus
        if bus is None:
            self.on_event(event)
            return
        bus.emit(event)

    async def _halt_run(self) -> bool:
        """Stop a run in flight and wait until it has really stopped. Returns
        whether there was one.

        A fix supersedes directories by moving them, so it must not run under a
        live run: interrupt, await the task unwinding (the ProVerif kill and
        the interrupt marker happen there), and only then move anything.
        """
        run = self._run
        if run is None or not run.control.running:
            return False
        run.control.interrupt()
        await run.control.stopped()
        return True

    def _run_meta(self) -> dict:
        """Metadata from the attached run (protocol, version, ground_truth and
        so on); empty when there is no run.json."""
        import json
        p = self._session.layout.run_json
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
