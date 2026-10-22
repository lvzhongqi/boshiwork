"""A run's attack reproductions as the console reads and asks for them.

``index`` is the reading: every false cell and what was decided for it, where
each reproduced cell's script and explanation are, and the newest summary, off
the files the ``reproduce_attacks`` step wrote and the ones asked for after the
run (``nodes/reproduce_attacks/manual``), resolved through the run's own layout
so a front end never spells a directory. While the step is still working it
has written ``targets.json`` but not yet ``attacks.json``, so its cells are read
back one by one from what each has finished.

``Reproductions`` is the asking: one queue per run, worked one cell at a time
on the console's own event loop, every change said on the run's ledger.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from pathlib import Path

import yaml

from orrery.api.host import Host
from orrery.api.settings import MissingConfigError, merge
from orrery.infra.proverif.runner import solver_problem
from orrery.modules.attacks.targets import AUTO, PENDING
from orrery.nodes.base import NodeError, RunEnv
from orrery.nodes.reproduce_attacks.explain import EXPLANATION, NODE
from orrery.nodes.reproduce_attacks.manual import (
    manual_outcome, manual_summary, refusal, reproduce_asked, resummarize,
    set_aside,
)
from orrery.nodes.reproduce_attacks.node import (
    ATTACKS, REPRODUCTION, TARGETS, make_runner,
)
from orrery.services.events import AttacksSummarized, AttackStatus
from orrery.services.store.layout import RunLayout

__all__ = ["index", "Reproductions", "QueueBusy"]

_log = logging.getLogger(__name__)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _layout(run_dir: Path) -> RunLayout:
    return RunLayout(run_dir.parent.parent, run_dir.parent.name, run_dir.name)


def index(run_dir: Path) -> dict:
    """What the console draws the attack panel from.

    ``step`` is ``None`` before the step has a directory; otherwise it names
    that directory and says whether the step is ``enabled`` and ``complete``.
    Each cell carries its target (``decision``, ``reason``, ``expected``,
    ``weakened``, ``round``) and, once reproduced, its outcome (``status``,
    ``script``, ``steps``, ``explanation`` …), with run-relative paths; a cell
    reproduced on request says ``manual`` and whether it is ``stale``.
    ``summary`` is the newer of the step's summary and the one rewritten on
    request, its content plus ``path`` and ``manual``, or ``None``.
    """
    layout = _layout(run_dir)
    home = layout.find_node_dir(NODE)
    if home is None:
        return {"step": None, "cells": [], "summary": None}
    step = {"dir": layout.rel(home), "enabled": True, "complete": False,
            "ground_truth": False, "limit": None}
    summary = None
    if (home / ATTACKS).is_file():
        doc = _read(home / ATTACKS)
        step.update(enabled=doc["enabled"], complete=doc["complete"],
                    ground_truth=doc.get("ground_truth", False))
        cells = doc["cells"]
        if doc.get("summary"):
            summary = {"path": doc["summary"], "manual": False,
                       **_read(layout.run_dir / doc["summary"])}
    elif (home / TARGETS).is_file():
        cells = [_so_far(layout, t) for t in _read(home / TARGETS)["targets"]]
    else:
        return {"step": step, "cells": [], "summary": None}
    if (home / TARGETS).is_file():
        targets = _read(home / TARGETS)
        step.update(limit=targets["limit"], ground_truth=targets["ground_truth"])
    out = []
    for c in cells:
        asked = (manual_outcome(layout, c["label"], c["goal"])
                 if c["decision"] == PENDING else None)
        # The target's reason says why the cell waited; once it has been
        # reproduced, the reason is the reproduction's own.
        out.append({**c, "reason": asked.get("reason", "") if asked else c["reason"],
                    **{k: v for k, v in (asked or {}).items() if k != "reason"},
                    "manual": asked is not None, "stale": bool(asked and asked["stale"])})
    later = manual_summary(layout)
    if later is not None and (summary is None or later.stat().st_mtime
                              > (layout.run_dir / summary["path"]).stat().st_mtime):
        summary = {"path": layout.rel(later), "manual": True, **_read(later)}
    return {"step": step, "cells": out, "summary": summary}


def _so_far(layout: RunLayout, target: dict) -> dict:
    """One target, with whatever its cell has finished while the step is
    still at work: the reproduction's outcome, then its explanation."""
    if target["decision"] != AUTO:
        return target
    cell = layout.attack_dir(target["label"], target["goal"], manual=False)
    out = dict(target)
    if (cell / REPRODUCTION).is_file():
        out.update(_read(cell / REPRODUCTION))
    if (cell / EXPLANATION).is_file():
        out["explanation"] = layout.rel(cell / EXPLANATION)
    return out


class QueueBusy(RuntimeError):
    """A summary was asked for while cells are still being reproduced."""


class Reproductions:
    """The cells somebody asked for on one finished run, reproduced and
    explained one at a time, and the summary rewritten on request.

    A request answers at once; the work carries on as a task on the caller's
    loop and says each change on the run's ledger (``AttackStatus``,
    ``AttacksSummarized``), so every tab watching the run sees it. The solver
    and the model go through the same gates a run does.
    """

    def __init__(self, run_dir: Path, host: Host) -> None:
        self.run_dir = run_dir
        self.host = host
        self.waiting: deque[tuple[str, str]] = deque()
        self.current: tuple[str, str] | None = None
        self.summarizing = False
        #: Why the last summary could not be written, until the next one is.
        self.error = ""
        self.task: asyncio.Task | None = None

    @property
    def busy(self) -> bool:
        return self.task is not None and not self.task.done()

    def state(self) -> dict:
        """What the index adds about this queue: the cells in it, in order,
        as ``scenario|goal``, and whether a summary is being written."""
        cells = ([self.current] if self.current else []) + list(self.waiting)
        return {"queue": [f"{label}|{goal}" for label, goal in cells],
                "summarizing": self.summarizing, "queue_error": self.error}

    def _env(self) -> RunEnv:
        """The run's environment: the console's configuration, pinned to the
        run's own work root and written in the run's own language. Raises
        MissingConfigError when the solver cannot run."""
        meta = _read(self.run_dir / "run.json")
        # Every run records the configuration it ran under (RunLayout.
        # write_config), so a run without one is not one this can add to.
        recorded = yaml.safe_load(
            (self.run_dir / "config.yaml").read_text(encoding="utf-8"))
        cfg = merge(self.host.cfg, {
            "paths": {"work_root": str(self.run_dir.parent.parent)},
            "prompt_lang": recorded["prompt_lang"]})
        exe = cfg["proverif"]["executable"]
        if (problem := solver_problem(exe)) is not None:
            raise MissingConfigError(
                f"proverif.executable cannot run ProVerif: {problem}")
        env = RunEnv(protocol_dir=Path(meta["protocol_dir"]),
                     layout=_layout(self.run_dir), config=cfg,
                     protocol_id=meta["protocol_id"],
                     subprotocol=meta.get("subprotocol"))
        env.bus = self.host.bus
        return env

    def _say(self, label: str, goal: str, status: str, reason: str = "") -> None:
        self.host.emit(AttackStatus(run=self.run_dir.name, node=NODE, goal=goal,
                                    label=label, status=status, reason=reason,
                                    manual=True))

    def enqueue(self, cells: list[tuple[str, str]]) -> dict:
        """Put cells in the queue and start working if idle. Returns the cells
        ``queued`` (a cell already in the queue counts, and is not added
        twice) and the ones ``refused``, each with why."""
        env = self._env()
        queued, refused = [], []
        for label, goal in cells:
            cell = {"scenario": label, "goal": goal}
            if (label, goal) == self.current or (label, goal) in self.waiting:
                queued.append(cell)
                continue
            why = refusal(env.layout, label, goal)
            if why is not None:
                refused.append({**cell, "why": why})
                continue
            self.waiting.append((label, goal))
            queued.append(cell)
            self._say(label, goal, "queued")
        if self.waiting and not self.busy:
            self.task = asyncio.get_running_loop().create_task(self._work(env))
        return {"queued": queued, "refused": refused}

    async def _work(self, env: RunEnv) -> None:
        runner = make_runner(env.config)
        emit = env.emitter(NODE)
        while self.waiting:
            label, goal = self.current = self.waiting.popleft()
            try:
                await reproduce_asked(env, runner, label=label, goal=goal,
                                      emit=emit)
            except NodeError:
                pass                    # said on the ledger where it was raised
            except Exception as e:      # noqa: BLE001
                _log.exception("reproducing %s/%s failed", label, goal)
                self._say(label, goal, "failed", f"{type(e).__name__}: {e}")
            finally:
                self.current = None

    def summarize(self) -> None:
        """Start rewriting the summary. Raises QueueBusy while cells are still
        in the queue: the summary would miss them."""
        if self.busy:
            raise QueueBusy(
                "cells are still being reproduced; ask for the summary once "
                "the queue is empty")
        env = self._env()
        self.summarizing, self.error = True, ""
        self.task = asyncio.get_running_loop().create_task(self._summary(env))

    async def _summary(self, env: RunEnv) -> None:
        try:
            doc = await resummarize(env)
        except asyncio.CancelledError:
            raise
        except Exception as e:          # noqa: BLE001
            _log.exception("rewriting the attack summary failed")
            self.error = f"{type(e).__name__}: {e}"
            return
        finally:
            self.summarizing = False
        self.host.emit(AttacksSummarized(run=self.run_dir.name, node=NODE,
                                         covered=len(doc["covered"])))

    async def stop(self, timeout: float = 30.0) -> int:
        """Empty the queue and stop the cell in hand; every cell dropped goes
        back to waiting. Returns how many were dropped."""
        in_hand = self.current
        dropped = ([in_hand] if in_hand else []) + list(self.waiting)
        self.waiting.clear()
        if self.busy:
            self.task.cancel()
            await asyncio.wait([self.task], timeout=timeout)
        self.current = None
        if in_hand is not None:
            set_aside(_layout(self.run_dir), *in_hand)
        for label, goal in dropped:
            self._say(label, goal, "cancelled")
        return len(dropped)
