"""The stage index: one run is an append-only sequence of executions, recorded
in ``stages.jsonl``. Every execution writes a new directory; nothing is renamed.

Two numbering kinds. ``seq`` siblings form an ordered chain and the number is
execution order, shared by every identity and never repeated. ``gen`` siblings
are a parallel fan-out and the number is which generation, so siblings of one
generation share it. This index is the authority: path resolution reads it and
never parses a directory name. Staleness is derived rather than bookkept — a
stage is live when it is the newest of its identity and ran after the input it
was computed from, where a stage's time is the latest line anywhere in its
subtree. For a ``seq`` chain the input is the point before; a ``gen`` row may
name a band as its ``input`` (an inject family reads its scenario's apply
chain), and a write there after the row makes the row stale.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

from orrery.services.store.atomic import append_line, read_jsonl_records

FILENAME = "stages.jsonl"

#: How an execution came to be: a step's first run, or one of three ways back.
CAUSES = ("initial", "gap", "fix", "rerun")

KINDS = ("seq", "gen")

_PREFIX = re.compile(r"^(\d{2})_")


@dataclass(frozen=True)
class Stage:
    """One execution of one identity, and where it wrote."""

    dir: str        #: run-relative directory, or "" for a step that writes none
    ident: str      #: node name, scenario label, apply rid, or goal family
    parent: str     #: run-relative directory holding it; "" is the run root
    kind: str       #: "seq" | "gen"
    n: int          #: the number in the name: order (seq) or generation (gen)
    cause: str
    by: str = ""            #: who caused the re-work: a node name, or "user"
    supersedes: str = ""    #: the directory this execution replaces, if any
    ts: str = ""
    #: The band whose output this execution consumed, as a parent path (an
    #: inject family's is its scenario's ``apply``), or "" when its input is
    #: the chain it sits in. A write under that band after this row makes the
    #: row stale: the model it was built on has been rewritten.
    input: str = ""

    @property
    def name(self) -> str:
        """The directory's own name, without its parent."""
        return self.dir.rsplit("/", 1)[-1] if self.dir else ""


def path(run_dir: Path) -> Path:
    """Where the index file lives inside ``run_dir``."""
    return Path(run_dir) / FILENAME


def load(run_dir: Path) -> list[Stage]:
    """Every execution this run has recorded, in the order it recorded them.
    An absent file gives an empty list.

    A line that does not parse raises RuntimeError rather than being skipped:
    this file decides which directory holds each step's current artifact, so a
    dropped line changes the answer instead of degrading it.
    """
    p = path(run_dir)
    out: list[Stage] = []
    for i, d in read_jsonl_records(p, what="the stage index"):
        try:
            out.append(Stage(**d))
        except TypeError as e:
            raise RuntimeError(
                f"{p}:{i}: unreadable stage record. This file is what says "
                f"which directory holds each step's current artifact, so a "
                f"line that cannot be read is an error, not a skip.") from e
    return out


def _check(run_dir: Path, s: Stage) -> None:
    """Refuse a record that does not describe a stage this store can hold."""
    if s.kind not in KINDS:
        raise ValueError(f"stage kind must be one of {KINDS}, got {s.kind!r}")
    if s.cause not in CAUSES:
        raise ValueError(f"stage cause must be one of {CAUSES}, got {s.cause!r}")
    if not s.ident:
        raise ValueError("a stage must name the identity it is an execution of")
    if s.dir and not (Path(run_dir) / s.dir).is_dir():
        raise ValueError(
            f"stage {s.dir!r} is recorded but no such directory exists; the "
            f"index and the run directory must be written together")


def record(run_dir: Path, s: Stage) -> Stage:
    """Append one execution to the index, stamping ``ts`` when unset, and give
    back the stored record. Callers normally go through ``allocate``, which
    creates the directory in the same call. Raises ValueError on a record this
    store cannot hold, including one naming a directory that is not there."""
    s = Stage(**{**asdict(s),
                 "ts": s.ts or datetime.now().isoformat(timespec="seconds")})
    _check(run_dir, s)
    append_line(path(run_dir), json.dumps(asdict(s), ensure_ascii=False))
    return s


def siblings(stages: list[Stage], parent: str) -> list[Stage]:
    """Every stage recorded directly under ``parent`` ("" is the run root)."""
    return [s for s in stages if s.parent == parent]


def newest(stages: list[Stage], parent: str, ident: str) -> Stage | None:
    """The last execution of one identity under ``parent``, live or not, and
    None when there is none. This is what a new execution supersedes and what
    it carries facts forward from."""
    got = [s for s in siblings(stages, parent) if s.ident == ident]
    return max(got, key=lambda s: s.n) if got else None


def next_n(stages: list[Stage], parent: str, kind: str, ident: str) -> int:
    """The number the next execution under ``parent`` takes.

    ``seq`` gives one past the highest under this parent — execution order,
    shared by every identity. ``gen`` gives one past the highest of this
    identity, so a first execution is always generation 0 whatever order the
    siblings finished in, and a parallel fan-out gets the same directory names
    on every run.
    """
    if kind == "gen":
        last = newest(stages, parent, ident)
        return 0 if last is None else last.n + 1
    used = [s.n for s in siblings(stages, parent)]
    return max(used) + 1 if used else 1


def chain(stages: list[Stage], parent: str) -> list[str]:
    """The declared order of a ``seq`` parent's identities, derived from the
    index alone.

    The first pass through a chain is the declared order, so ordering each
    identity by the number of its earliest execution reproduces it. Nothing has
    to hand the order in, which matters because the node table lives in
    ``pipeline`` and ``services`` may not import it.
    """
    first: dict[str, int] = {}
    for s in sorted(siblings(stages, parent), key=lambda s: s.n):
        first.setdefault(s.ident, s.n)
    return [ident for ident, _ in sorted(first.items(), key=lambda kv: kv[1])]


def kind_of(stages: list[Stage], parent: str) -> str | None:
    """Whether ``parent`` holds an ordered chain ("seq") or a concurrent
    fan-out ("gen"), read off its children; None when it has none. A parent
    whose children disagree raises RuntimeError — a directory is one or the
    other and a mixture is a bug, not a case to interpret."""
    kinds = {s.kind for s in siblings(stages, parent)}
    if not kinds:
        return None
    if len(kinds) > 1:
        raise RuntimeError(
            f"{parent or '<run root>'} holds both {' and '.join(sorted(kinds))} "
            f"stages; a directory is either an ordered chain or a concurrent "
            f"fan-out and cannot be read as both")
    return kinds.pop()


def _times(stages: list[Stage]) -> dict[str, int]:
    """When each stage last had work done anywhere in its tree, as a position
    in this index — its own line, or the latest line under it.

    Re-working one apply point rewrites the enclosing scenario's verdict without
    the scenario or the step above it taking a new number, so a step's time has
    to come from its subtree for the staleness cascade to reach through levels.
    """
    at = {s.dir: i for i, s in enumerate(stages) if s.dir}
    out = dict(at)
    for i, s in enumerate(stages):
        for d in at:
            if s.parent == d or s.parent.startswith(d + "/"):
                out[d] = max(out[d], i)
    return out


def last_write(stages: list[Stage], parent: str) -> int:
    """The latest line anywhere under ``parent``, as a position in this index;
    -1 when nothing was ever written there."""
    return max((i for i, s in enumerate(stages)
                if s.parent == parent or s.parent.startswith(parent + "/")),
               default=-1)


def live(stages: list[Stage], parent: str) -> dict[str, Stage]:
    """Which execution of each identity under ``parent`` is the current one,
    keyed by identity; a stale identity is simply absent.

    A ``gen`` parent answers with each identity's highest generation, since
    parallel siblings do not invalidate one another; a generation that names
    an ``input`` band is stale once that band was written after it, the way a
    goal family is stale once its scenario's apply chain was re-worked. A
    ``seq`` parent walks its chain carrying a floor: an identity whose newest
    execution ran before something upstream was last written is stale, and a
    stale entry does not raise the floor, so everything after it is stale too.
    """
    here = siblings(stages, parent)
    when = _times(stages)
    if kind_of(stages, parent) != "seq":
        out: dict[str, Stage] = {}
        for s in here:
            if s.ident not in out or s.n > out[s.ident].n:
                out[s.ident] = s
        return {ident: s for ident, s in out.items()
                if not s.input or last_write(stages, s.input) < when.get(s.dir, -1)}
    out = {}
    floor = -1
    for ident in chain(stages, parent):
        s = newest(here, parent, ident)
        if s is None or when.get(s.dir, -1) <= floor:
            continue        # never ran, or ran before its input was rewritten
        out[ident] = s
        floor = when[s.dir]
    return out


def live_dir(run_dir: Path, stages: list[Stage], parent: str, ident: str
             ) -> Path | None:
    """The absolute directory holding ``ident``'s current artifacts, or None
    when it has none — never ran, or what it left is stale."""
    s = live(stages, parent).get(ident)
    return Path(run_dir) / s.dir if s is not None and s.dir else None


def allocate(run_dir: Path, stages: list[Stage], *, parent: str, ident: str,
             kind: str, cause: str, by: str = "", carry_facts: bool = True,
             input: str = "") -> Stage:
    """Create the next execution's directory and record it, in that order, and
    give back the recorded stage.

    One call does both, so an index entry never exists for a directory that
    does not. ``carry_facts`` copies the previous execution's ``facts.jsonl``
    across: a fact is a message about the work, not about one attempt at it, so
    every later attempt has to read it. Raises FileExistsError when the
    directory is already there, which means something outside the pipeline
    wrote into the run.
    """
    n = next_n(stages, parent, kind, ident)
    name = f"{n:02d}_{ident}"
    rel = f"{parent}/{name}" if parent else name
    d = Path(run_dir) / rel
    if d.exists():
        raise FileExistsError(
            f"{rel} already exists but is not in {FILENAME}; the run directory "
            f"and its index disagree, which means something outside the "
            f"pipeline wrote here")
    d.mkdir(parents=True)
    prev = newest(stages, parent, ident)
    if carry_facts and prev is not None and prev.dir:
        src = Path(run_dir) / prev.dir / "facts.jsonl"
        if src.is_file():
            (d / "facts.jsonl").write_text(src.read_text(encoding="utf-8"),
                                           encoding="utf-8")
    return record(run_dir, Stage(
        dir=rel, ident=ident, parent=parent, kind=kind, n=n, cause=cause,
        by=by, supersedes=prev.dir if prev is not None else "", input=input))


def verify(run_dir: Path, stages: list[Stage]) -> list[str]:
    """Where the index and the directory tree disagree, as sentences; empty
    when they agree.

    Every recorded directory must exist, and every numbered directory under a
    recorded parent must be recorded — a directory nobody wrote down is one
    whose place in time nothing knows.
    """
    run_dir = Path(run_dir)
    problems = []
    known = {s.dir for s in stages}
    for s in stages:
        if s.dir and not (run_dir / s.dir).is_dir():
            problems.append(f"{s.dir}: recorded in {FILENAME}, not on disk")
    for parent in {s.parent for s in stages}:
        p = run_dir / parent if parent else run_dir
        if not p.is_dir():
            continue
        for child in p.iterdir():
            rel = f"{parent}/{child.name}" if parent else child.name
            if child.is_dir() and _PREFIX.match(child.name) and rel not in known:
                problems.append(f"{rel}: on disk, not recorded in {FILENAME}")
    return problems
