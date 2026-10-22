"""Detects goals ProVerif proved only because their observation point is
unreachable: with no trace to search there is no counterexample, and the goal
comes back true on an empty set, worded exactly like a real proof.

The test re-asks the same model with one reachability query per observation
point. Only two shapes have a placement to probe -- ``event end_<goal>`` and
the ``[private]`` witness envelope ``wenc_<goal>(witness_<goal>_<h>, v)``.
Whole-trace secrecy queries cannot be vacuous and carry no point.
"""

from __future__ import annotations

import re

from orrery.modules.pvtext.edits import replace_queries
from orrery.modules.pvtext.parse import query_owners
from orrery.modules.pvtext.probe import PROBE_SETTING, is_reached

_END = re.compile(r"^[ \t]*event\s+(?P<name>end_\w+)\s*\((?P<args>[^)]*)\)\s*\.", re.M)
_WENC_FUN = re.compile(
    r"^[ \t]*fun\s+(?P<fun>wenc_\w+)\s*\(\s*bitstring\s*,\s*(?P<type>\w+)\s*\)", re.M)
_WENC_OUT = re.compile(r"\b(?P<fun>wenc_\w+)\s*\(\s*(?P<witness>witness_\w+)\s*,")


def observation_points(pv: str) -> list[tuple[str, str]]:
    """One reachability query per observation point, as ``[(label, query)]``.

    The label (``end_<goal>`` or ``witness_<goal>_<holder>``) appears inside its
    own query, so verdicts split back by naming anchor rather than by order.
    Argument types are read off the model's own declarations.
    """
    out: list[tuple[str, str]] = []
    for m in _END.finditer(pv):
        name = m.group("name")
        types = [t.strip() for t in m.group("args").split(",") if t.strip()]
        if not types:
            out.append((name, f"query event({name}())."))
            continue
        xs = [f"x{i}" for i in range(len(types))]
        binder = ", ".join(f"{a}: {t}" for a, t in zip(xs, types))
        out.append((name, f"query {binder}; event({name}({', '.join(xs)}))."))
    valtype = {m.group("fun"): m.group("type") for m in _WENC_FUN.finditer(pv)}
    seen: set[tuple[str, str]] = set()
    for m in _WENC_OUT.finditer(pv):
        fun, witness = m.group("fun"), m.group("witness")
        if fun not in valtype or (fun, witness) in seen:
            continue
        seen.add((fun, witness))
        out.append((witness,
                    f"query x: {valtype[fun]}; attacker({fun}({witness}, x))."))
    return out


def vacuity_form(pv: str, points: list[tuple[str, str]]) -> str:
    """The same model with its own queries replaced by the reachability ones.

    The goal queries have to go: a goal verdict and a vacuity verdict for the
    same goal both carry that goal's id, and the splitter attributes by id.
    """
    return PROBE_SETTING + "\n" + replace_queries(pv, [q for _label, q in points])


def unreachable(verdicts, points: list[tuple[str, str]]) -> list[str]:
    """The labels ProVerif proved unreachable.

    A point it returned no verdict for is left out: silence means the solver
    ran out of room, which is not evidence of vacuity.
    """
    dead = []
    for label, _q in points:
        # A whole word: ``auth_b_to_a`` is a prefix of ``auth_b_to_a_noninj``
        # (the rule vacuous_goals already applies through query_owners), and
        # a substring match would let the long label's verdict answer for the
        # short one.
        mine = [v for v in verdicts
                if re.search(rf"\b{re.escape(label)}\b", v.query)]
        if mine and not any(is_reached(v.verdict) for v in mine):
            dead.append(label)
    return dead


def vacuous_goals(dead: list[str], points: list[tuple[str, str]],
                  goal_ids: list[str]) -> list[str]:
    """The goals all of whose observation points are unreachable.

    Secrecy carries one witness per holder, so a single dead vantage point is a
    fact about that holder alone. Ownership goes through ``query_owners`` for
    its longest-match rule: ``auth_b_to_a`` is a substring of
    ``auth_b_to_a_noninj``, so a plain ``in`` test would misattribute.
    """
    owned: dict[str, list[str]] = {gid: [] for gid in goal_ids}
    for label, _q in points:
        who = query_owners(label, goal_ids)
        if len(who) == 1:
            owned[who[0]].append(label)
    return [gid for gid in goal_ids
            if owned[gid] and all(label in dead for label in owned[gid])]
