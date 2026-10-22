"""Instrumentation for the one-shot baseline: the reachability probe and the
vacuity queries. The baseline writes the whole ProVerif file, so probe placement
is checked here and a role is whatever ``let <name>(...) =`` defines.

An authentication query is proved true when its ``end_`` event never happens, so
a separate ``query event(end_g(x)).`` tells a dead model from a safe one. Probe,
goal and vacuity verdicts take three ProVerif runs per scenario.
"""

from __future__ import annotations

import re

from orrery.modules.pvtext.parse import (
    declared_events,
    main_keyword_start,
    process_blocks,
    strip_queries,
)
from orrery.modules.pvtext.probe import (
    PROBE_SETTING,
    any_call_spans,
    event_call,
    event_name,
    is_followed_by_semicolon,
    is_reached,
    main_process_calls,
    query_line,
    remove_probe,
)

#: Prefix of the event an authentication goal ends with. The prompt states the
#: same naming contract to the model.
END_PREFIX = "end_"

_RE_RECONSTRUCT = re.compile(
    r"(?m)^[ \t]*set\s+reconstructTrace\s*=\s*\w+\s*\.[ \t]*\r?\n?")


def instrument(pv: str) -> str:
    """Return the submitted one-shot model with the probe solver setting on top.

    The setting belongs only to the probe form of the file; ``remove_probe``
    takes it out again before goal solving.
    """
    body = _RE_RECONSTRUCT.sub("", pv).lstrip()
    return f"{PROBE_SETTING}\n{body}"


def placement(pv: str) -> dict:
    """Where the probe sits, judged by the pipeline's rules minus the
    role-to-event naming, since the baseline picks its own names: a body marks
    its end with exactly one event, no other body uses that event, the call ends
    a branch, and the main process marks nothing. Returns ``{roles, marked,
    probe_of, problems}``, ``probe_of`` mapping a marked role to its event.
    """
    blocks = process_blocks(pv)
    calls = {role: any_call_spans(pv, blk) for role, blk in blocks.items()}
    callers: dict[str, list[str]] = {}
    for role, spans in calls.items():
        for _s, _e, event in spans:
            callers.setdefault(event, []).append(role)

    roles, marked, probe_of, problems = sorted(blocks), [], {}, []
    for role in roles:
        spans = calls[role]
        events = sorted({sp[2] for sp in spans})
        if not events:
            problems.append(f"role {role}'s body never marks its honest end")
            continue
        if len(events) > 1:
            problems.append(
                f"role {role}'s body marks its end with more than one event "
                f"({', '.join(event_call(e) for e in events)}): one role, one probe")
            continue
        event = events[0]
        shared = sorted(set(callers[event]) - {role})
        if shared:
            problems.append(
                f"`{event_call(event)}` is called from role {role}'s body and from "
                f"{', '.join(shared)}: a probe that more than one role can reach says "
                f"nothing about either")
            continue
        if any(is_followed_by_semicolon(pv, sp[1]) for sp in spans):
            problems.append(
                f"role {role}'s `{event_call(event)}` is followed by `;`, so it is a "
                f"waypoint, not the end of a branch")
            continue
        marked.append(role)
        probe_of[role] = event

    for event in main_process_calls(pv):
        problems.append(
            f"the main process calls `{event_call(event)}`, which is reachable "
            f"without the role ever finishing")
        for role in [r for r, e in probe_of.items() if e == event]:
            marked.remove(role)
            del probe_of[role]

    return {"roles": roles, "marked": marked, "probe_of": probe_of,
            "problems": problems}


def read_reach(verdicts, place: dict) -> dict:
    """``{per_role, all, no_verdict}`` -- whether each role's probe is reached.

    A role that was never marked, or was marked wrongly, is ``False`` without
    asking ProVerif. ``no_verdict`` lists marked roles ProVerif said nothing
    about.
    """
    out, silent = {}, []
    for role in place["roles"]:
        if role not in place["marked"]:
            out[role] = False
            continue
        mine = [v for v in verdicts if event_name(place["probe_of"][role]) in v.query]
        if not mine:
            out[role] = False
            silent.append(role)
            continue
        out[role] = any(is_reached(v.verdict) for v in mine)
    return {"per_role": out, "all": bool(out) and all(out.values()),
            "no_verdict": silent}


def end_events(pv: str, goal_ids: list[str]) -> dict[str, tuple[str, ...]]:
    """``{goal_id: (argument types…)}`` for the goals that declared an
    ``end_<gid>`` event. A secrecy goal declares none and gets no vacuity
    query: its witness is only observable from inside a body."""
    declared = declared_events(pv)
    return {g: declared[f"{END_PREFIX}{g}"]
            for g in goal_ids if f"{END_PREFIX}{g}" in declared}


def vacuity_query(goal_id: str, types: tuple[str, ...]) -> str:
    """``query x0: T0, …; event(end_g(x0, …)).``, with the argument types copied
    from the model's own event declaration."""
    args = [f"x{i}" for i in range(len(types))]
    call = f"event({END_PREFIX}{goal_id}({', '.join(args)}))"
    if not args:
        return f"query {call}."
    binder = ", ".join(f"{a}: {t}" for a, t in zip(args, types))
    return f"query {binder}; {call}."


def vacuity_form(pv: str, ends: dict[str, tuple[str, ...]]) -> str:
    """The model with the probe and its own queries removed and one vacuity
    query per goal inserted in front of the main process, which is where
    ProVerif accepts declarations."""
    text = strip_queries(remove_probe(pv))
    at = main_keyword_start(text)
    block = "\n".join(vacuity_query(g, t) for g, t in sorted(ends.items()))
    return f"{text[:at].rstrip()}\n\n{block}\n\n{text[at:]}"


def read_vacuity(verdicts, ends: dict[str, tuple[str, ...]]) -> dict:
    """``{goal_id: True}`` when the goal's ``end_`` event can never happen, so
    its correspondence query was proved on an empty set of traces. A goal
    ProVerif returned nothing for is left out rather than guessed at.
    """
    out = {}
    for g in sorted(ends):
        mine = [v for v in verdicts if f"{END_PREFIX}{g}" in v.query]
        if mine:
            out[g] = not any(is_reached(v.verdict) for v in mine)
    return out


__all__ = ["END_PREFIX", "end_events", "instrument", "placement", "query_line", "read_reach",
           "read_vacuity", "vacuity_form", "vacuity_query"]
