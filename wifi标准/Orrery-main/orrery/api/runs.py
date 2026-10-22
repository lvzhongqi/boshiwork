"""Reading a run directory: what is in it, what is current, and what a person
has said about it.

A run directory is written once, so everything here is a reading except the
review state a person adds afterwards. What is current is resolved with the
engine's own rules — the stage index, the node table, ``pinned_nodes`` — so a
front end holds no second copy. Refusals are ValueError; rendering them belongs
to the front end.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterator
from dataclasses import asdict
from pathlib import Path

from orrery.api.corpus_inputs import supplied_of
from orrery.api.reading_order import headline_rank
from orrery.api.truth import corpus_rel
from orrery.nodes.base import pinned_nodes
from orrery.pipeline import steps
from orrery.pipeline.table import build_table
from orrery.services.review import REVIEW_JSON, review_state
from orrery.services.store import stages as stage_index
from orrery.services.store.atomic import read_jsonl_tolerant, write_json
from orrery.services.store.layout import RunLayout
from orrery.services.store.runs import RESERVED, delete_run, list_runs

__all__ = ["RESERVED", "run_list", "run_meta", "run_tree", "rerun_target",
           "remove", "ledger", "findings", "review", "close_review"]


def run_list(runs_root: Path, live: Collection[str] | None = None) -> list[dict]:
    """Every run under this work root, plus ``review``, ``dir`` (the protocol's
    corpus path, which groups eighty ISO mechanisms under nine standards; empty
    without ground truth) and ``rank`` (that path's place in the shared reading
    order).

    ``live`` names the runs actually executing: a killed run leaves ``running``
    in its run.json for ever, so a run outside ``live`` reads as
    ``interrupted``. It is only correct from a caller that knows every writer of
    this tree; ``None``, the default, leaves the status alone.
    """
    out = []
    for r in list_runs(runs_root):
        home = runs_root / r.protocol / r.name
        rel = corpus_rel(run_meta(home).get("ground_truth") or "")
        status = ("interrupted"
                  if live is not None and r.status == "running"
                  and r.name not in live else r.status)
        out.append({"name": r.name, "protocol": r.protocol, "status": status,
                    "problem": r.problem,
                    "started": r.started, "verdicts": r.verdicts, "acc": r.acc,
                    "dir": rel, "rank": headline_rank(rel),
                    "review": review_state(home).get("state", "open")})
    return out


def run_meta(root: Path) -> dict:
    """A run's run.json, or empty when it has none yet. Reading a run must not
    fail because the file that names it has not landed."""
    p = root / "run.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def run_tree(root: Path) -> dict:
    """The run's files, and the index that says which of them are current.

    A run that went back holds more than one directory per step, and which one a
    reader should look at is not readable off the names; it is resolved here off
    ``stages.jsonl``, the same way the engine does it.
    """
    st = stage_index.load(root)
    meta = run_meta(root)
    return {
        # The index is the authority, the directory names its projection; a
        # reader opening a run is where a disagreement matters, and checking
        # tens of entries is cheap. Reported, never repaired.
        "problems": stage_index.verify(root, st),
        "files": sorted(str(p.relative_to(root)) for p in root.rglob("*")
                        if p.is_file()),
        # Every execution, in order — the run's real shape, including the steps
        # it went back to.
        "stages": [asdict(x) for x in st],
        # The resolution itself, keyed by the parent directory each group lives
        # under, so nobody re-implements the rule.
        "live": {parent: {ident: x.dir
                          for ident, x in stage_index.live(st, parent).items()}
                 for parent in sorted({x.parent for x in st})},
        # The steps this run cannot be re-entered at, because their artifact was
        # handed in rather than produced: re-running one writes the same bytes
        # back. Decided by the engine off the inputs run.json recorded, so the
        # rule has one copy the day a further supplied input appears.
        "pinned": sorted(pinned_nodes(meta)),
        # What this run was actually handed, and where it was told to stop.
        "range": supplied_of(meta),
    }


def rerun_target(run_dir: Path, meta: dict, step: str):
    """Which node a re-entry at ``step`` starts from, resolved with
    ``steps.resolve`` so a front end holds no copy of that rule.

    Raises ValueError when run.json is missing or incomplete, when ``step``
    names nothing current, or when the step's artifact was supplied rather than
    extracted.
    """
    if not run_dir.joinpath("run.json").is_file():
        raise ValueError(
            f"run {run_dir.name!r} has no run.json: it never got far enough to "
            f"record what it was asked, so there is nothing to re-enter")
    for field in ("protocol", "protocol_dir"):
        if not meta.get(field):
            raise ValueError(f"run.json for {run_dir.name!r} records no "
                             f"{field}; cannot re-enter it")
    layout = RunLayout(run_dir.parent.parent, run_dir.parent.name, run_dir.name)
    ref = steps.resolve(layout, build_table(), step)
    # A step holding a file somebody handed it has nothing to redo. A console
    # greys these out, so reaching here means the page and the run disagree
    # about what was supplied, which is worth an answer rather than a no-op run.
    if ref.node in pinned_nodes(meta):
        raise ValueError(
            f"{ref.node} cannot be re-entered: this run was handed its artifact "
            f"rather than extracting it, so re-running it would write the same "
            f"file back. Start a run without that input to have it extracted")
    return ref


def remove(runs_root: Path, protocol: str, name: str) -> list[str]:
    """Delete a run directory, returning what went. The caller must ensure the
    run is not in flight: a directory pulled out from under a running pipeline
    is the one state the store's immutability argument assumes cannot happen."""
    return delete_run(runs_root, protocol, name)


def ledger(run_dir: Path, since: int = 0) -> Iterator[dict]:
    """This run's durable events, oldest first, from ``since`` on (that
    sequence number included; the stream route adds one to a Last-Event-ID).
    Tolerant of a truncated last line, which a ledger being written while it
    is read will have."""
    for row in read_jsonl_tolerant(run_dir / "events.jsonl"):
        if row.get("seq", -1) >= since:
            yield row


def findings(run_dir: Path) -> list[dict]:
    """Every reading a person has filed on this run, newest first.

    Read off the ledger rather than a file, since findings are added after the
    run and a run directory is written once. Newest first because a second look
    at a cell overrules the first.
    """
    out = [{**(row.get("data") or {}), "seq": row.get("seq"), "at": row.get("ts")}
           for row in read_jsonl_tolerant(run_dir / "events.jsonl")
           if row.get("t") == "finding_recorded"]
    out.reverse()
    return out


def review(run_dir: Path) -> dict:
    """Whether this run is still open for review."""
    return review_state(run_dir)


def close_review(run_dir: Path, state: str, note: str = "") -> dict:
    """Mark this run reviewed (``archived``) or open it again (``open``),
    raising ValueError on any other state.

    Kept apart from the run's ``status``: what the pipeline concluded and what a
    person concluded about it are two different facts, so a reader closing a run
    does not overwrite the record of how it ended.
    """
    if state not in ("open", "archived"):
        raise ValueError("state is open or archived")
    payload = {"state": state, "note": note.strip()}
    write_json(run_dir / REVIEW_JSON, payload)
    return payload
