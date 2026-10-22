"""Which cell of a run is which cell of the corpus.

A cell is a goal under a scenario. Each side names its goals and assumptions in
its own words — a run that extracted its vocabulary shares no id with the
corpus — so a cell is identified by what it is about, never by a name:

- a goal by its type, subtype, values and parties (``goal_key``);
- a scenario by the answer it gives on each object, an object being an axis
  and the instance its target names (``answers``; the instance comes from the
  vocabulary's own ``instance_of``, which this layer is handed).

Two scenarios are the same when they give the same answer on every object both
of them speak about. A side may speak about objects the other leaves unsaid —
an extraction that also declares the attacker's own private key disclosed,
which the corpus folds into ``admission = open`` — and those are left out of
the comparison rather than counted against it. Pairing is one to one: a goal
or a scenario that matches more than one on the other side is paired with
none, since there is no saying which one it is.

One rule for every comparison against the corpus: cross_check's and the
scoring's (``modules/scoring``) both pair through ``pair_goals`` and
``pair_cells``. A claims document is asked the same question by first spelling
it out as the cells it asserts (``claim_cells``): each scenario becomes the
complete assignment it runs, exactly as aggregate writes cases_results.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable

from orrery.modules.libschema.io import parse_assumptions, parse_claims
from orrery.modules.libschema.resolve import expand_assignments


def _canon(v) -> Hashable:
    """A hashable form of a value or a party list; lists are unordered here."""
    if isinstance(v, (list, tuple)):
        return tuple(sorted(map(str, v)))
    return v


def goal_key(prop: dict) -> tuple:
    """What a goal is about: its type, subtype, values and parties."""
    parties = prop.get("parties") or {}
    return (prop["type"], prop.get("subtype"),
            _canon(prop.get("values") or []),
            tuple(sorted((k, _canon(v)) for k, v in parties.items())))


def answers(scenario: list[dict], assumptions: dict,
            instance_of: Callable[[str, object], object]) -> dict[tuple, str]:
    """A scenario, ``[{id, subtype}]``, as ``{(axis, instance): subtype}``,
    the ids resolved through the side's own ``assumptions.json``. Raises
    KeyError for an id the declarations do not have."""
    decl = {a["id"]: a for sec in ("fixed", "variable")
            for a in assumptions.get(sec, [])}
    out: dict[tuple, str] = {}
    for p in scenario:
        if p["id"] not in decl:
            raise KeyError(f"scenario names {p['id']!r}, which the assumptions "
                           f"do not declare")
        a = decl[p["id"]]
        out[(a["axis"], instance_of(a["axis"], a.get("target")))] = p["subtype"]
    return out


def same_scenario(a: dict[tuple, str], b: dict[tuple, str]) -> bool:
    """The same answer on every object both speak about."""
    return all(a[k] == b[k] for k in a.keys() & b.keys())


def pair(ours: list, theirs: list, same: Callable[[object, object], bool]
         ) -> list[tuple[int, int]]:
    """The one-to-one pairs ``(i, j)`` with ``same(ours[i], theirs[j])``: an
    entry matching more than one on the other side is left unpaired."""
    hits = [[j for j, t in enumerate(theirs) if same(o, t)] for o in ours]
    back: dict[int, int] = {}
    for js in hits:
        for j in js:
            back[j] = back.get(j, 0) + 1
    return [(i, js[0]) for i, js in enumerate(hits)
            if len(js) == 1 and back[js[0]] == 1]


def pair_goals(ours: dict, theirs: dict) -> dict[str, str]:
    """Our goal id → the corpus's, over two ``properties.json``."""
    a, b = ours.get("properties", []), theirs.get("properties", [])
    ka, kb = [goal_key(p) for p in a], [goal_key(p) for p in b]
    return {a[i]["id"]: b[j]["id"]
            for i, j in pair(ka, kb, lambda x, y: x == y)}


def pair_cells(ours_cases: dict, theirs_cases: dict,
               ours_vocab: tuple[dict, dict], theirs_vocab: tuple[dict, dict],
               instance_of: Callable[[str, object], object]) -> list[tuple]:
    """Every paired cell of two ``cases_results.json``, as ``(our goal id,
    our by_scenario entry, their goal id, their entry)``. Each vocabulary is
    that side's ``(assumptions.json, properties.json)``."""
    (ours_assum, ours_props), (theirs_assum, theirs_props) = ours_vocab, theirs_vocab
    goals = pair_goals(ours_props, theirs_props)
    theirs = {c["id"]: c["by_scenario"] for c in theirs_cases.get("cases", [])}
    out = []
    for case in ours_cases.get("cases", []):
        gid = case["id"]
        if goals.get(gid) not in theirs:
            continue
        mine, corpus = case["by_scenario"], theirs[goals[gid]]
        a = [answers(b["scenario"], ours_assum, instance_of) for b in mine]
        b = [answers(t["scenario"], theirs_assum, instance_of) for t in corpus]
        out += [(gid, mine[i], goals[gid], corpus[j])
                for i, j in pair(a, b, same_scenario)]
    return out


def claim_cells(claims: dict, assumptions: dict,
                is_noop: Callable[[str, str], bool]) -> dict:
    """A ``claims.json`` as the cells it asserts, in ``cases_results`` form
    without verdicts: each goal with the complete assignment of every scenario
    it is claimed under, two scenario names with one condition set being one
    world. ``is_noop`` is the realizers' flow-state predicate, handed in
    because this layer does not import them."""
    assum = parse_assumptions(assumptions)
    doc = parse_claims(claims, assum)
    worlds, alias = expand_assignments(doc, assum, is_noop)
    world = dict(worlds)
    cases = []
    for c in doc.claims:
        names = list(dict.fromkeys(alias[ref] for ref in c.scenarios))
        cases.append({"id": c.property, "by_scenario": [
            {"scenario": [{"id": p.ref_id, "subtype": p.subtype}
                          for p in world[n].points]} for n in names]})
    return {"cases": cases}
