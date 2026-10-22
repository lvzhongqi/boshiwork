"""Run directory lifecycle: allocating run names, keeping the ``latest``
pointer, listing runs, and deleting one on request.

A run directory is immutable once written; a new execution takes the next free
name rather than overwriting. ``<protocol>/latest`` is a symlink to the newest
run, so ``latest`` is a reserved name. ``delete_run`` is the only thing here
that removes data, and nothing calls it on its own.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from itertools import count
from pathlib import Path

from orrery.services.store import stages

LATEST = "latest"

#: The corpus's expected answers, stowed beside the runs they are compared
#: against. Written by the host (``orrery/api/truth.py``); the engine side
#: never reads it.
GROUND_TRUTH = "_ground_truth"

#: What a protocol directory holds that is not a run. Every walk of such a
#: directory has to agree on this list; one that forgets an entry allocates a
#: run name over it, lists it as a result, or points ``latest`` at it.
RESERVED = (LATEST, GROUND_TRUTH)


def run_dirs(home: Path) -> list[Path]:
    """The run directories under one protocol, sorted by name.

    The single answer to what counts as a run here. Symlinks are excluded along
    with the reserved names, so ``latest`` and any run linked in from elsewhere
    are both left out.
    """
    home = Path(home)
    if not home.is_dir():
        return []
    return sorted((p for p in home.iterdir()
                   if p.is_dir() and not p.is_symlink()
                   and p.name not in RESERVED),
                  key=lambda p: p.name)


def protocol_id(name: str, version: str | None = None,
                subprotocol: str | None = None) -> str:
    """The protocol identity ``<name>[-<version>][-<subprotocol>]``.

    Names the results tree and goes into run.json, and matches the corpus's own
    protocol_id so a run and its ground truth carry the same name. Built from
    what the caller declares, not from the corpus directory name: its last
    segment is the protocol for ``academic/NSSK`` but the version for
    ``rfc/EDHOC/draft-08``.
    """
    parts = [name]
    if version:
        parts.append(version)
    if subprotocol:
        parts.append(subprotocol)
    return "-".join(parts)


def next_run_name(root: Path, protocol: str, base: str) -> str:
    """The first unused ``<base><NN>`` under ``root/protocol``.

    The sequence is read off the directory itself, so an interrupted run or a
    tree copied from elsewhere continues from what is actually on disk. Runs of
    one protocol are serial (the batch host's constraint), so scan-then-claim
    cannot race.
    """
    d = Path(root) / protocol
    used = {p.name for p in d.iterdir()} if d.is_dir() else set()
    return next(n for i in count(1) if (n := f"{base}{i:02d}") not in used)


@dataclass(frozen=True)
class RunSummary:
    """One row of the run list: what a reader can tell about a run without
    opening anything else."""

    protocol: str                       # the directory name, i.e. the protocol id
    name: str
    status: str                         # run.json's status; "unknown" when it has none, "unreadable" when its index cannot be read
    started: str = ""
    problem: str = ""                   # what stopped this run from being read, when status is "unreadable"
    verdicts: dict[str, int] = field(default_factory=dict)   # verdict → property count
    acc: float | None = None            # cross-check accuracy, when it ran

    @property
    def run_dir_name(self) -> str:
        return f"{self.protocol}/{self.name}"


def _summarize(run_dir: Path) -> RunSummary | None:
    """One run directory → its summary, or None when it holds no run.json.

    Every read is defensive: this walks whatever is on disk, including runs
    written by older versions and runs killed mid-write.
    """
    meta = _read_json(run_dir / "run.json")
    if meta is None:
        return None
    verdicts: dict[str, int] = {}
    # Through the index: the answers live in the aggregate step's own directory,
    # and a run that went back has more than one of those. An index this store
    # refuses to read (a line edited from outside) is that run's problem and is
    # listed as such, rather than one bad run taking the whole list down.
    try:
        loaded = stages.load(run_dir)
    except RuntimeError as e:
        return RunSummary(protocol=run_dir.parent.name,
                          name=meta.get("run_name", run_dir.name),
                          status="unreadable", problem=str(e),
                          started=str(meta.get("started", "")))
    agg = stages.live_dir(run_dir, loaded, "", "aggregate")
    results = (_read_json(agg / "results.json") if agg else None) or {}
    for row in results.get("results", []):
        v = str(row.get("verdict", "unknown"))
        verdicts[v] = verdicts.get(v, 0) + 1
    # The report is cross_check's own artifact, found through the index the
    # same way.
    cc = stages.live_dir(run_dir, loaded, "", "cross_check")
    report = (_read_json(cc / "cross_check.json") if cc else None) or {}
    acc = report.get("acc")
    return RunSummary(
        protocol=run_dir.parent.name,
        name=meta.get("run_name", run_dir.name),
        status=str(meta.get("status", "unknown")),
        started=str(meta.get("started", "")),
        verdicts=verdicts,
        acc=float(acc) if isinstance(acc, (int, float)) else None,
    )


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def list_runs(root: Path) -> list[RunSummary]:
    """Every run under the work root, newest first.

    The tree is the index: there is no registry file that can fall out of step
    with it. What counts as a run under a protocol is ``run_dirs``' to say.
    """
    root = Path(root)
    if not root.is_dir():
        return []
    out = [s for proto in sorted(root.iterdir()) if proto.is_dir()
           for d in run_dirs(proto)
           if (s := _summarize(d)) is not None]
    # A run with no start time sorts last.
    return sorted(out, key=lambda s: s.started or "", reverse=True)


def delete_run(root: Path, protocol: str, name: str) -> list[str]:
    """Remove one run and leave the tree consistent behind it.

    Irreversible and unconditional here: whether the run is safe to remove —
    nothing executing it, nobody reading it — is the caller's to establish. The
    path is resolved and must land inside ``root``, so a ``..`` in the name
    cannot reach the corpus; ``latest`` is re-pointed at the newest remaining
    run or removed; a protocol directory left with neither runs nor a stowed
    ground truth is removed too. Returns what it removed, relative to ``root``.
    """
    root = Path(root).resolve()
    if name == LATEST:
        raise ValueError(
            f"{LATEST!r} is the pointer to the newest run, not a run; delete "
            f"the run it names")
    d = (root / protocol / name).resolve()
    # Resolved and then checked against the two-level shape, not only against
    # the root: ``.`` as the name resolves to the protocol directory itself,
    # and removing that takes every run and the stowed ground truth with it.
    if (not d.is_relative_to(root) or d == root
            or d.relative_to(root).parts != (protocol, name)):
        raise ValueError(f"{protocol}/{name} is not a run inside {root}")
    if not d.is_dir():
        raise FileNotFoundError(f"no run at {protocol}/{name}")
    if not (d / "run.json").is_file():
        # The same test _summarize applies to decide what is a run. A work
        # root pointed somewhere that holds other things would otherwise let
        # this remove any directory two levels down.
        raise ValueError(
            f"{protocol}/{name} holds no run.json, so it is not a run; "
            f"nothing was removed")

    removed = [str(d.relative_to(root))]
    shutil.rmtree(d)

    home = root / protocol
    link = home / LATEST
    rest = run_dirs(home)
    if link.is_symlink() and not link.exists():         # dangling: it pointed here
        link.unlink()
        if rest:
            point_latest(root, protocol, rest[-1].name)
        else:
            removed.append(f"{protocol}/{LATEST}")
    if not rest:
        link.unlink(missing_ok=True)
        # Empty of runs is not the same as empty: a stowed ground truth keeps
        # the directory alive.
        if next(home.iterdir(), None) is None:
            home.rmdir()
            removed.append(protocol)
    return removed


def point_latest(root: Path, protocol: str, run_name: str) -> None:
    """Point ``<protocol>/latest`` at ``run_name``.

    The target is relative, so the tree can be moved or copied without breaking
    the link. Written as a temporary symlink and renamed over the old one:
    ``symlink`` cannot replace an existing entry, and unlinking first would
    leave the pointer missing for a moment.
    """
    d = Path(root) / protocol
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / ".latest.tmp"
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(run_name)
    os.replace(tmp, d / LATEST)
