"""Semantic validation of the five kinds of LIB JSON, on top of the structure,
types, version and reference closure io deserialisation already established:
entries match the vocabularies, ids are unique, scenarios are complete
assignments, and the goal ids named by claims, results and cases agree.

The two vocabularies and the noop predicate are realizer/injector knowledge from
the layer above, so every entry point takes them as parameters — this module
never imports upward. The vocabulary may be larger than the question: a property
no claim names is legal, and :func:`validate_claims` returns those so the caller
can record them. Anything that does not check out raises LibValidationError.
"""
from __future__ import annotations

from orrery.modules.libschema.model import VERDICTS
from orrery.modules.libschema.resolve import (
    applicable,
    required_params,
    resolve_point,
    scenario_coordinates,
    world_of,
)
from orrery.modules.libschema.version import LibValidationError


def validate_world(doc, world_vocab):
    """Check the world section against the world vocabulary: the axis is known,
    the subtype is known on it and is not the flow state, the target supplies
    every required param and no extra ones, and each (axis, object instance) is
    answered once. Returns doc.

    An unmentioned axis already takes its flow state, so writing it would give
    two encodings of one world."""
    known = set(world_vocab.axes())
    seen: dict[tuple[str, object], str] = {}
    for w in doc.world:
        if w.axis not in known:
            raise LibValidationError(
                f"assumptions.world[{w.id}]: axis {w.axis!r} is not a world axis; "
                f"known: {sorted(known)}. An axis that states a fact about an "
                f"object in the model belongs in 'fixed' or 'variable'")
        subs = set(world_vocab.subtypes(w.axis))
        if w.subtype not in subs:
            raise LibValidationError(
                f"assumptions.world[{w.id}]: subtype {w.subtype!r} is not on axis "
                f"{w.axis}: {sorted(subs)}")
        if world_vocab.is_noop(w.axis, w.subtype):
            raise LibValidationError(
                f"assumptions.world[{w.id}]: {w.subtype!r} is the flow state of "
                f"axis {w.axis}; drop the entry — an unmentioned axis already "
                f"takes it, and writing it would let two encodings mean one world")
        need = world_vocab.required_params(w.axis, w.subtype)
        have = set((w.target or {}).keys())
        if not need <= have:
            raise LibValidationError(
                f"assumptions.world[{w.id}]: target {w.target!r} is missing "
                f"{sorted(need - have)}; axis {w.axis} requires {sorted(need)}")
        extra = have - set(world_vocab.params(w.axis, w.subtype))
        if extra:
            raise LibValidationError(
                f"assumptions.world[{w.id}]: target carries {sorted(extra)}, which "
                f"axis {w.axis} does not take; it takes "
                f"{sorted(world_vocab.params(w.axis, w.subtype))}")
        inst = world_vocab.instance_of(w.axis, w.target)
        key = (w.axis, inst)
        if key in seen:
            raise LibValidationError(
                f"assumptions.world[{w.id}]: axis {w.axis} is answered twice for "
                f"the same object ({seen[key]!r} already does); a run analyses "
                f"one world, so each (axis, object) holds exactly one value")
        seen[key] = w.id
    return doc


def validate_assumptions(doc, vocab):
    """Check both sections against the vocabulary: the axis is known, each
    subtype is known and applies to that entry's target, the target carries no
    field no declared subtype takes, and each (axis, object) is answered once.
    A fixed entry's single subtype goes through the same loop via its
    one-element domain. Returns doc."""
    known = set(vocab.axes())
    for a in doc.entries():
        if a.axis not in known:
            raise LibValidationError(
                f"assumptions[{a.id}]: axis {a.axis!r} is not in the vocabulary; "
                f"known: {sorted(known)}")
        subs = set(vocab.dimension_values(a.axis))
        for s in a.subtypes:
            if s not in subs:
                raise LibValidationError(
                    f"assumptions[{a.id}]: subtype {s!r} is not on axis {a.axis}: {sorted(subs)}")
            if not applicable(vocab, a.axis, s, a.target):
                raise LibValidationError(
                    f"assumptions[{a.id}]: subtype {s!r} does not apply to target {a.target!r}; "
                    f"the vocabulary requires {sorted(required_params(vocab, a.axis, s))} "
                    f"and the target does not supply all of them"
                )
            bad = vocab.domain_error(a.axis, s, a.target)
            if bad:
                raise LibValidationError(f"assumptions[{a.id}]: {bad}")
        # Checked against the union of the entry's own subtypes' params, since a
        # field can belong to one rung and not another (`phase` is a leak-rung
        # field) and a variable entry declares several rungs at once. A field no
        # subtype reads would ride along and look as if it meant something.
        takes = set()
        for sub in a.subtypes:
            takes |= set(vocab.params(a.axis, sub))
        extra = set(a.target or {}) - takes
        if extra:
            raise LibValidationError(
                f"assumptions[{a.id}]: target carries {sorted(extra)}, which no "
                f"subtype of axis {a.axis} takes; the subtypes declared here "
                f"({sorted(a.subtypes)}) take {sorted(takes)}")
    _one_answer_per_object(doc, vocab)
    return doc


def _one_answer_per_object(doc, vocab) -> None:
    """One entry per (axis, object instance), across fixed and variable.

    An axis's subtypes are mutually exclusive answers about one object, so two
    entries on one object are two answers to one question and no scenario could
    hold both. The parse-time ``(axis, target)`` check keys on the whole target,
    so a qualifier field would make two targets on one object look like two
    objects; the instance key names the object itself. Left to ProVerif, the
    contradiction only surfaces deep in solve, after the whole pipeline has run.
    """
    seen: dict[tuple[str, object], str] = {}
    for a in doc.entries():
        inst = vocab.instance_of(a.axis, a.target)
        if inst is None and vocab.instance_key(a.axis) is not None:
            continue                          # names no instance: nothing to key on
        key = (a.axis, inst)
        if key in seen:
            what = (f"the object {' -> '.join(map(str, inst))!r}"
                    if inst is not None else "this protocol (a global axis)")
            raise LibValidationError(
                f"assumptions[{a.id}]: axis {a.axis!r} already answers for "
                f"{what} in {seen[key]!r}. One axis states one answer per "
                f"object: the subtypes are mutually exclusive, so two entries "
                f"on it cannot both hold. Merge them into one entry (a "
                f"variable dimension if the document leaves the answer open).")
        seen[key] = a.id



def validate_properties(doc, prop_vocab):
    """Check properties against the goal vocabulary: ids are unique, the type
    and subtype exist, and the parties shape matches the type. Returns doc.

    Both routes — authored claims read from LIB, and extraction from the
    document — pass through this gate, so an invented type is caught here rather
    than at injection, where it would only show as "no matching injector".
    """
    valid_types = set(prop_vocab.types())
    seen = set()
    for g in doc.properties:
        if g.id in seen:
            raise LibValidationError(f"properties: duplicate goal id {g.id!r}")
        seen.add(g.id)

        if g.type not in valid_types:
            raise LibValidationError(
                f"properties[{g.id}]: type {g.type!r} is not in the vocabulary {sorted(valid_types)}")
        if g.subtype:
            allowed = set(prop_vocab.subtypes_of(g.type))
            if g.subtype not in allowed:
                raise LibValidationError(
                    f"properties[{g.id}]: subtype {g.subtype!r} is not under {g.type}; "
                    f"allowed: {sorted(allowed)}")
        _check_parties(g, prop_vocab.parties_shape(g.type))
    return doc


def validate_claims(claims, assumptions, properties, *, is_noop, vocab, prop_vocab):
    """Check the claims: property references close, no condition writes the flow
    state, every named scenario expands to a well-defined world, and any
    required assumption axis is present in that world (a fixed entry counts).

    ``is_noop(axis, subtype) -> bool`` is the realizer knowledge injected from
    above; a stub has no realization and is never a noop.

    Returns the vocabulary goal ids no claim names — legal, since the vocabulary
    may be larger than the question, but the caller has to record which goals
    are not being run.
    """
    world_coords = {}
    for ns in claims.scenarios:
        for p in ns.conditions:
            resolve_point(p, assumptions, vocab)   # applicability on top of parse-time closure
            if is_noop(p.axis, p.subtype):
                raise LibValidationError(
                    f"claims.scenarios[{ns.name}]: condition {p.ref_id!r} = {p.subtype!r} "
                    f"writes the flow state; drop the condition — an unmentioned "
                    f"dimension already takes it, and writing it would let two encodings "
                    f"mean one world"
                )
        try:
            world = world_of(ns, assumptions, is_noop)
        except Exception as e:
            raise LibValidationError(f"claims.scenarios[{ns.name}]: {e}") from e
        world_coords[ns.name] = {p.ref_id: p.subtype for p in world.points}

    for c in claims.claims:
        g = properties.by_id(c.property)
        if g is None:
            raise LibValidationError(
                f"claims[{c.property}]: dangling reference; properties.json has no such "
                f"goal, it declares {properties.ids()}")
        need = prop_vocab.requires_assumption(g.type, g.subtype)
        if need:
            for name in c.scenarios:
                _check_required_assumption(g, name, world_coords[name], assumptions, need)
    claimed = set(claims.property_ids())
    return [g.id for g in properties.properties if g.id not in claimed]


def _check_required_assumption(goal, name, coords, assumptions, need):
    """Check that this scenario's full world holds the assumption the goal's
    subtype must be paired with (the vocabulary's ``requires_assumption``): some
    assumption on the required axis takes one of the allowed subtypes, a fixed
    entry counting exactly like a condition. One is enough — how many keys
    leaked cannot be decided mechanically.

    Without this, a ``Secrecy.forward_secrecy`` claim configuring no reveal
    assumption runs through and comes back ``true`` (with no phase in the model
    the query degenerates into plain secrecy), matching LIB for the wrong
    reason.
    """
    hit = [
        aid for aid, sub in coords.items()
        if assumptions.by_id(aid).axis == need["axis"] and sub in set(need["subtypes"])
    ]
    if hit:
        return
    same_axis = [a.id for a in assumptions.entries() if a.axis == need["axis"]]
    raise LibValidationError(
        f"claims[{goal.id}].scenarios[{name}]: {goal.type}.{goal.subtype} must be paired "
        f"with an assumption on axis {need['axis']} taking one of "
        f"{need['subtypes']}, and this scenario's world has none"
        + (f" (the axis has {same_axis}, but none is assigned one of those values)" if same_axis
           else f" (assumptions.json has no entry on axis {need['axis']} at all)")
        + "\nreason: " + str(need["why"]).strip()
    )


def _check_parties(goal, shape):
    """Check that ``parties`` carries the field names the goal's type requires.

    A wrong shape goes wrong silently: with ``holders`` on an Authentication
    goal the injector cannot find asserter/subject and has to guess who
    authenticates to whom, and a backwards guess still produces a verdict.
    """
    p = goal.parties or {}
    if shape == "holders":
        if not isinstance(p.get("holders"), (list, tuple)) or not p["holders"]:
            raise LibValidationError(
                f"properties[{goal.id}]: type={goal.type} requires parties.holders to be a "
                f"non-empty list, got {p!r}")
    elif shape == "asserter_subject":
        miss = [k for k in ("asserter", "subject") if not str(p.get(k, "")).strip()]
        if miss:
            raise LibValidationError(
                f"properties[{goal.id}]: type={goal.type} requires parties to have {miss}, "
                f"got {p!r}")
    elif not p:
        raise LibValidationError(f"properties[{goal.id}]: parties must not be empty")


def validate_results(doc, assumptions):
    """Check results: ids are unique and every verdict is in VERDICTS.
    Returns doc."""
    seen = set()
    for r in doc.results:
        if r.id in seen:
            raise LibValidationError(f"results: duplicate goal id {r.id!r}")
        seen.add(r.id)
        if r.verdict not in VERDICTS:
            raise LibValidationError(f"results[{r.id}].verdict {r.verdict!r} ∉ {VERDICTS}")
    return doc


def validate_cases_results(matrix, assumptions, vocab):
    """Check cases_results: ids/scenarios are unique, every scenario is a
    complete assignment, and verdicts are valid. Returns matrix."""
    seen = set()
    for gc in matrix.cases:
        if gc.id in seen:
            raise LibValidationError(f"cases_results: duplicate goal id {gc.id!r}")
        seen.add(gc.id)
        seen_scen = set()
        for sv in gc.by_scenario:
            if sv.verdict not in VERDICTS:
                raise LibValidationError(
                    f"cases_results[{gc.id}].verdict {sv.verdict!r} ∉ {VERDICTS}")
            if sv.scenario in seen_scen:
                raise LibValidationError(
                    f"cases_results[{gc.id}]: duplicate scenario {sv.scenario.to_json()}")
            seen_scen.add(sv.scenario)
            scenario_coordinates(sv.scenario, assumptions, vocab)
    return matrix
