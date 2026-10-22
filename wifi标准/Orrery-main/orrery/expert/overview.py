"""The run overview: the state of the run read off disk, prepended to every
user message.

It also names the readable sessions, which list_artifacts hides. Rebuilt every
turn, so a fix that rewrites artifacts mid-session leaves no stale snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path

from orrery.agent.compose import localized, render_prompt
from orrery.services import facts
from orrery.services.store.atomic import read_jsonl_tolerant
from orrery.services.store import stages
from orrery.services.store.layout import RunLayout


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _steps(meta: dict) -> str:
    nodes = meta.get("nodes") or {}
    if not nodes:
        return "no step has reported yet"
    return ", ".join(f"{name}={status}" for name, status in nodes.items())


def _scenarios(layout: RunLayout) -> list[str]:
    """One line per scenario with its verdicts. A scenario directory with no
    verdict.json is still listed, as unfinished."""
    root = layout.find_node_dir("scenarios")
    if root is None:
        return []
    # A re-worked scenario leaves more than one directory behind, so the keys
    # here are the live identities from the stage index.
    out = []
    for label in sorted(stages.live(layout.stages, layout.rel(root))):
        d = layout.find_scenario_dir(label)
        data = _load(d / "verdict.json") if d is not None else None
        if data is None:
            out.append(f"{label}: no verdict yet")
            continue
        verdicts = data.get("verdicts") or {}
        body = ", ".join(f"{g}={v}" for g, v in verdicts.items()) or "no goal"
        out.append(f"{label}: {body}")
    return out


def _sessions(names: list[str]) -> list[str]:
    """Group readable session names for display: the steps on one line, then
    one line per scenario. A big run has one session per assumption and per
    goal family in every scenario."""
    steps = [n for n in names if "/" not in n]
    by_scenario: dict[str, list[str]] = {}
    other = []
    for n in names:
        parts = n.split("/")
        if len(parts) >= 3 and parts[0] == "scenarios":
            by_scenario.setdefault(parts[1], []).append("/".join(parts[2:]))
        elif "/" in n:
            other.append(n)
    out = [", ".join(steps)] if steps else []
    out += [f"scenarios/{sc}/ → {', '.join(rest)}"
            for sc, rest in sorted(by_scenario.items())]
    return out + other


def _answers(layout: RunLayout) -> list[str]:
    agg = layout.find_node_dir("aggregate")
    data = _load(agg / "results.json") if agg is not None else None
    if not data:
        return []
    return [f"{r['id']}={r['verdict']}" for r in data.get("results", [])]


def _gaps(layout: RunLayout) -> str:
    rows = read_jsonl_tolerant(layout.gaps_jsonl)
    if not rows:
        return ""
    accepted = sum(1 for r in rows if r.get("verdict") == "accepted")
    return (f"{len(rows)} upstream-gap report(s), {accepted} accepted "
            f"(gaps.jsonl has the detail)")


def _facts(layout: RunLayout) -> list[str]:
    """One line per filed message: the step directory it lives in (its
    address), who filed it, and the first hundred characters."""
    out = []
    for f in sorted(layout.run_dir.rglob(facts.FILENAME)):
        rel = f.parent.relative_to(layout.run_dir)
        for fact in facts.read(f.parent):
            out.append(f"{rel} ({fact.source}): "
                       f"{' '.join(fact.text.split())[:100]}")
    return out


def build(layout: RunLayout, run_dir: Path, sessions: list[str], *,
          lang: str = "en") -> str:
    """Render the overview. ``sessions`` are the readable session names, which
    the caller already computes for the tool context."""
    meta = _load(layout.run_json) or {}
    return render_prompt(
        __file__, localized("overview.md", lang),
        run_name=meta.get("run_name", run_dir.name),
        protocol=meta.get("protocol", "?"),
        subprotocol=meta.get("subprotocol"),
        status=meta.get("status", "unknown"),
        from_node=meta.get("from_node"),
        steps=_steps(meta),
        scenarios=_scenarios(layout),
        answers=_answers(layout),
        gaps=_gaps(layout),
        facts=_facts(layout),
        sessions=_sessions(sessions),
    )
