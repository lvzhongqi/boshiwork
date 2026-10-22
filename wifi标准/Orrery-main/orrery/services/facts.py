"""Facts: what a step was told after it first ran — a user fix, or an accepted
upstream-gap report — kept in a ``facts.jsonl`` in the step's own directory.

The file's location is the address: a fact in ``08_scenarios/`` reaches every
scenario, one in ``08_scenarios/lowe/`` reaches that scenario alone. A fresh
session reads its step's and its ancestors' facts at prompt build
(``RunEnv.facts``); a resumed session already has the same text in its
transcript, so it does not read them again.

Superseding a step seals its canonical files but never its ``facts.jsonl``, so
facts outlive attempts. They live inside the run directory, so a later run of
the same protocol starts clean.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from orrery.services.store.atomic import append_line, read_jsonl_records

FILENAME = "facts.jsonl"


@dataclass(frozen=True)
class Fact:
    """One filed message: when it was filed, who filed it, and its text."""

    ts: str
    source: str         # "user" | "gap:<reporter>"
    text: str


def append(step_dir: Path, *, source: str, text: str) -> None:
    """File one fact for the step at ``step_dir``, timestamped now. ``source``
    is ``"user"`` or ``"gap:<reporter>"``."""
    append_line(Path(step_dir) / FILENAME, json.dumps(
        {"ts": datetime.now().isoformat(timespec="seconds"),
         "source": source, "text": text.strip()},
        ensure_ascii=False))


def read(step_dir: Path) -> list[Fact]:
    """This one step's facts, in file order; no file means an empty list. A
    line that does not parse raises RuntimeError rather than being skipped,
    because the message on it would then reach no step."""
    path = Path(step_dir) / FILENAME
    out: list[Fact] = []
    for i, d in read_jsonl_records(path, what="a step's filed messages"):
        try:
            out.append(Fact(ts=d["ts"], source=d["source"], text=d["text"]))
        except (KeyError, TypeError) as e:
            raise RuntimeError(
                f"{path}:{i}: unreadable fact line; the message on it would "
                f"reach no step, so this is an error rather than a skip") from e
    return out


def collect(run_dir: Path, step_rel: str) -> list[Fact]:
    """The facts a step reads: its ancestors' first, then its own, each file
    in order. ``step_rel`` is the step's run-relative directory path."""
    run_dir = Path(run_dir)
    parts = [p for p in step_rel.split("/") if p]
    out: list[Fact] = []
    for i in range(1, len(parts) + 1):
        out.extend(read(run_dir.joinpath(*parts[:i])))
    return out
