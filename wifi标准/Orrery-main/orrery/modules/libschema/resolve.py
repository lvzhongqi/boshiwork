"""Point → assumption resolution and scenario coordinates: mapping a point onto
assumptions.json and the assumption vocabulary.

The vocabulary arrives as a parameter (a ``Vocabulary`` from
``modules.kbase.assumptions.catalog``) because it is built from the realizer
declarations one layer up and this module must not import upward. Which
assumption a point lands on is already resolved by ``id`` at the model layer, so
only two things are checked here: the subtype is in the domain that assumption
declares, and it applies to that assumption's target.
"""
from __future__ import annotations

from orrery.modules.libschema.model import Point, Scenario, _canon_target
from orrery.modules.libschema.version import LibResolveError


def required_params(vocab, axis, subtype):
    """The names of the required params of that subtype. An unknown
    (axis, subtype) raises LibResolveError instead of the vocabulary's
    KeyError."""
    try:
        return vocab.required_params(axis, subtype)
    except KeyError as e:
        raise LibResolveError(str(e)) from None


def applicable(vocab, axis, subtype, target):
    """The applicability rule: a subtype applies to a target if and only if the
    target supplies all of its required params.

    ``disclosed`` requires ``of`` and so does not apply to a targetless
    assumption; ``none`` requires nothing and applies to any target on its axis.
    """
    have = set(target) if isinstance(target, dict) else set()
    return required_params(vocab, axis, subtype) <= have


def resolve_point(point, assumptions, vocab):
    """Return the Assumption a point hits, raising LibResolveError if the point
    is illegal.

    Two gates: the subtype must be in the ``subtypes`` that assumption declares,
    and it must apply to that assumption's target. Which assumption the point
    lands on was already resolved by id in ``Point.from_ref``.
    """
    a = assumptions.by_id(point.ref_id) if point.ref_id else _by_axis_target(assumptions, point)
    if a is None:
        raise LibResolveError(
            f"point {point!r}: no matching entry in assumptions.json; declared: {assumptions.ids()}"
        )
    if point.subtype not in a.subtypes:
        raise LibResolveError(
            f"point {point!r}: subtype {point.subtype!r} is not in assumption "
            f"{a.id!r} subtypes {list(a.subtypes)}"
        )
    if not applicable(vocab, a.axis, point.subtype, a.target):
        need = sorted(required_params(vocab, a.axis, point.subtype))
        raise LibResolveError(
            f"point {point!r}: subtype {point.subtype!r} does not apply to assumption "
            f"{a.id!r} target {a.target!r}; the vocabulary requires {need} and the "
            f"target does not supply all of them"
        )
    return a


def _by_axis_target(assumptions, point):
    """Points built inside the engine carry no ref_id and are looked up by
    (axis, target)."""
    tk = _canon_target(point.target)
    for a in assumptions.entries():
        if a.axis == point.axis and _canon_target(a.target) == tk:
            return a
    return None


def scenario_coordinates(scenario, assumptions, vocab):
    """Scenario → full coordinates ``{assumption_id: subtype}``.

    The scenario must be a complete assignment: as many entries as
    ``assumptions.json`` declares, the single-subtype fixed ones included.
    Missing or duplicated entries raise LibResolveError. Fixed entries are not
    filled in automatically — the engine applies a scenario entry by entry, so
    an entry that was not written is not applied.
    """
    coords = {}
    for p in scenario.points:
        a = resolve_point(p, assumptions, vocab)
        if a.id in coords:
            raise LibResolveError(
                f"scenario assigns assumption {a.id!r} twice: already {coords[a.id]!r}, now {p.subtype!r}"
            )
        coords[a.id] = p.subtype
    missing = [a for a in assumptions.entries() if a.id not in coords]
    if missing:
        raise LibResolveError(
            "scenario is not a complete assignment; missing: " + "; ".join(
                f"{a.id!r} (one of {list(a.subtypes)})" for a in missing
            )
        )
    return coords


# ── world expansion: named scenarios → complete assignments ─────────────────
#
# Which subtype is the flow state (a noop) is a realizer property, and realizers
# live in the nodes layer above, so it arrives as a predicate
# ``is_noop(axis, subtype) -> bool`` rather than an import.

def noop_default(assumption, is_noop):
    """The flow-state (noop) value in an assumption's domain, or None when the
    domain has none. Two noop values in one domain would make "unmentioned"
    ambiguous, so that raises LibResolveError."""
    noops = [s for s in assumption.subtypes if is_noop(assumption.axis, s)]
    if len(noops) > 1:
        raise LibResolveError(
            f"assumption {assumption.id!r}: domain {list(assumption.subtypes)} holds "
            f"{len(noops)} flow-state values {noops}; an unmentioned dimension would "
            f"be ambiguous — a domain may carry at most one noop"
        )
    return noops[0] if noops else None


def world_of(named_scenario, assumptions, is_noop):
    """The world a named scenario runs in, as a complete assignment: all fixed
    entries + the conditions + flow-state defaults for every variable the
    conditions do not mention.

    A variable whose domain holds no flow-state value cannot be defaulted; the
    conditions must assign it, and not doing so raises LibResolveError.
    """
    points = [Point(axis=f.axis, subtype=f.subtype, target=f.target, ref_id=f.id)
              for f in assumptions.fixed]
    points.extend(named_scenario.conditions)
    assigned = {p.ref_id for p in named_scenario.conditions}
    for a in assumptions.variable:
        if a.id in assigned:
            continue
        default = noop_default(a, is_noop)
        if default is None:
            raise LibResolveError(
                f"scenario {named_scenario.name!r}: variable {a.id!r} is not assigned "
                f"and its domain {list(a.subtypes)} holds no flow-state value to "
                f"default to — the conditions must assign it explicitly"
            )
        points.append(Point(axis=a.axis, subtype=default, target=a.target, ref_id=a.id))
    return Scenario(tuple(points))


def expand_assignments(claims, assumptions, is_noop):
    """The distinct worlds this question runs, deduplicated by condition set:
    two names with the same conditions are one world, and the first name in
    table order is canonical and names the artifact directory.

    Returns ``([(canonical_name, Scenario)], alias)`` where ``alias`` maps every
    scenario name to its canonical name.
    """
    worlds, alias, by_key = [], {}, {}
    for ns in claims.scenarios:
        key = ns.condition_key()
        canon = by_key.get(key)
        if canon is None:
            by_key[key] = canon = ns.name
            worlds.append((ns.name, world_of(ns, assumptions, is_noop)))
        alias[ns.name] = canon
    return worlds, alias
