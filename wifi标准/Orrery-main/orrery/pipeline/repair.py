"""Projection of the run ledger into repair.json: how many times each
check-gated session had to submit before it cleared. Nothing is inferred and no
model is called.

A submission is a ``check_report``, not a model round, so ``attempt`` is the
field that counts. A session is keyed by (node, scenario, unit), the same
grouping the console uses.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from orrery.services.store.atomic import write_json


def from_events(rows) -> dict:
    """Ledger rows in, repair record out. Pure.

    Reports session and submission counts, ``repairs`` (the extra submissions),
    how many sessions passed on their first try, how many passed at all, and a
    per-session breakdown sorted by key.
    """
    sessions: dict[tuple, dict] = {}
    for r in rows:
        if r.get("t") != "check_report":
            continue
        key = (r.get("node") or "", r.get("scenario") or "", r.get("unit") or "")
        d = r.get("data") or {}
        s = sessions.setdefault(key, {"attempts": 0, "passed": False,
                                      "first_pass": False})
        # ``attempt`` is what the runner stamps; a row without it falls back to
        # arrival order.
        s["attempts"] = max(s["attempts"], int(d.get("attempt") or 0)
                            or s["attempts"] + 1)
        if d.get("passed"):
            s["passed"] = True
            s["first_pass"] = s["first_pass"] or s["attempts"] == 1
    n = len(sessions)
    submissions = sum(s["attempts"] for s in sessions.values())
    return {
        "sessions": n,
        "submissions": submissions,
        # a repair is an extra submission: what is left after one per session
        "repairs": submissions - n,
        "first_pass": sum(1 for s in sessions.values() if s["first_pass"]),
        "passed": sum(1 for s in sessions.values() if s["passed"]),
        "by_session": [
            {"node": k[0], "scenario": k[1], "unit": k[2],
             "attempts": s["attempts"], "passed": s["passed"]}
            for k, s in sorted(sessions.items())],
    }


def read(run_dir: Path) -> dict:
    """Project one run directory. Raises if it has no ledger."""
    path = Path(run_dir) / "events.jsonl"
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue          # a half-written last line on a killed run
    return from_events(rows)


def write(run_dir: Path) -> None:
    """Write ``repair.json`` beside work.md. A failure here is logged and
    swallowed, since a projection must not fail an otherwise finished run."""
    try:
        write_json(Path(run_dir) / "repair.json", read(run_dir))
    except Exception:                            # noqa: BLE001
        logging.getLogger(__name__).warning(
            "repair.json projection failed", exc_info=True)
