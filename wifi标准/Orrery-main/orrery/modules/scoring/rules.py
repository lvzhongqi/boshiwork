"""The comparison judgements: two documents in, one score out.

Pure functions: nothing here opens a file, knows a path, or knows what a run is
— the caller reads both sides and hands them over as parsed JSON.

Every judgement has the same shape: ``num`` is what matched, ``den`` is what the
corpus declares, and anything the candidate produced beyond that lands in
``extra`` rather than being deducted, so a score is a recall plus an
over-generation count. Ids are model-generated and never comparable across
sides, so entries are matched on what they say, one to one. The vocabularies
(assumptions, properties) match fuzzily (``greedy_match`` lets each corpus
entry be claimed once, so near-duplicate candidates cannot push the count above
the truth); claims and verdicts are cells and pair exactly, by the one rule
cross_check uses (``modules/verdicts/cells``).
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from orrery.modules.verdicts.cells import claim_cells, pair_cells, pair_goals


def item(num: int, den: int, *, extra: int = 0, detail: list | None = None,
         **more) -> dict:
    """One score. ``score`` is None rather than 0 when the corpus declares
    nothing: a protocol with no entries of a kind has no accuracy on it, and
    averaging a 0 in would measure the corpus."""
    return {"num": num, "den": den,
            "score": (num / den) if den else None,
            "extra": extra, **more, "detail": detail or []}


def greedy_match(cands: list, golds: list, hit: Callable[[Any, Any], bool]):
    """(pairs, missed_golds, extra_cands), matching each corpus entry at most
    once. Deterministic: the corpus's order decides, not the candidate's."""
    taken: set[int] = set()
    pairs, missed = [], []
    for g in golds:
        for i, c in enumerate(cands):
            if i not in taken and hit(c, g):
                taken.add(i)
                pairs.append((c, g))
                break
        else:
            missed.append(g)
    return pairs, missed, [c for i, c in enumerate(cands) if i not in taken]


def _flat(v) -> set[str]:
    """Every scalar inside a value, as strings. dicts contribute their values,
    not their keys, so ``{"asserter": "A"}`` and ``{"holders": ["A"]}`` are both
    about A."""
    if isinstance(v, dict):
        return set().union(*(_flat(x) for x in v.values())) if v else set()
    if isinstance(v, (list, tuple)):
        return set().union(*(_flat(x) for x in v)) if v else set()
    return {str(v)}


# ── principals ───────────────────────────────────────────────────────────────
def _value_facts(doc: dict) -> set[tuple[str, tuple[str, ...]]]:
    """The machine-comparable part of the semantic value inventory: each value's
    name paired with its sorted dependency edges.

    ``derived_from`` is compared as a set, since which values a term depends on
    is the fact and the order they are listed in is not. Descriptions carry
    evidence for a reader and are not comparable across two valid extractions.
    """
    return {
        (value.get("name"), tuple(sorted(value.get("derived_from") or [])))
        for value in doc.get("values", [])
    }


def score_principals(cand: dict, gold: dict) -> dict:
    """Two numbers: actor names and semantic value/dependency facts."""
    cnames = [p.get("name") for p in cand.get("principals", [])]
    gnames = [p.get("name") for p in gold.get("principals", [])]
    matched = [n for n in gnames if n in cnames]

    candidate_values = _value_facts(cand)
    gold_values = _value_facts(gold)
    hits = candidate_values & gold_values
    misses = gold_values - candidate_values
    extras = candidate_values - gold_values
    detail = [
        {"hit": sorted(map(str, hits))},
        {"miss": sorted(map(str, misses))},
        {"extra": sorted(map(str, extras))},
    ]
    return item(len(hits), len(gold_values), extra=len(extras), detail=detail,
                principals={"num": len(matched), "den": len(gnames)})


def score_principals_aligned(cand: dict, gold: dict, maps: dict) -> dict:
    """Exact semantic-inventory score after a validated alpha-rename.

    The LLM only supplies ``maps``; applying them and intersecting the fact sets
    is the same deterministic judgement as :func:`score_principals`.
    """
    from orrery.modules.scoring.alignment import apply_alignment
    return score_principals(apply_alignment(cand, maps), gold)


# ── assumptions ──────────────────────────────────────────────────────────────
_SECTIONS = ("world", "fixed", "variable")


def _assumption_entries(doc: dict) -> list[dict]:
    return [{"section": s, **e} for s in _SECTIONS for e in doc.get(s, [])]


def _assumption_answers(e: dict) -> set[str]:
    """The vocabulary rungs an assumption entry explicitly contains."""
    if "subtype" in e:
        return {e["subtype"]}
    return set(e.get("subtypes", []))


def _assumption_section_covers(candidate: str, gold: str) -> bool:
    """Whether the candidate's section can contain the corpus entry's section.

    A variable dimension contains each of its rungs, so it covers a corpus entry
    that fixed the same object at one of them; one fixed value does not cover a
    variable scenario space. World declarations are section-exact.
    """
    if gold == "world":
        return candidate == "world"
    if gold == "fixed":
        return candidate in {"fixed", "variable"}
    return candidate == "variable"


def hit_assumption(c: dict, g: dict) -> bool:
    """A hit means the candidate entry contains the corpus one: a covering
    section, the same axis, a superset of its rungs, and an overlapping target.

    An extraction may open a wider scenario domain than the sparse corpus query;
    missing a corpus rung is still a miss, adding rungs is not.
    """
    return (_assumption_section_covers(c["section"], g["section"])
            and c.get("axis") == g.get("axis")
            and _assumption_answers(c) >= _assumption_answers(g)
            and bool(_flat(c.get("target")) & _flat(g.get("target"))))


def score_assumptions(cand: dict, gold: dict) -> dict:
    """Recall over the corpus's assumption entries, hit ids in ``detail``."""
    cs, gs = _assumption_entries(cand), _assumption_entries(gold)
    pairs, missed, extra = greedy_match(cs, gs, hit_assumption)
    return item(len(pairs), len(gs), extra=len(extra),
                detail=[{"hit": [g.get("id") for _, g in pairs]},
                        {"miss": [g.get("id") for g in missed]},
                        {"extra": [c.get("id") for c in extra]}])


def score_assumptions_aligned(cand: dict, gold: dict,
                              symbols: dict[str, str]) -> dict:
    """:func:`score_assumptions` after renaming the candidate's symbols."""
    from orrery.modules.scoring.symbols import rename_assumptions
    return score_assumptions(rename_assumptions(cand, symbols), gold)


# ── properties ───────────────────────────────────────────────────────────────
def hit_property(c: dict, g: dict) -> bool:
    """Same goal type and subtype, plus at least one shared value or party."""
    return (c.get("type") == g.get("type")
            and c.get("subtype") == g.get("subtype")
            and bool((_flat(c.get("values")) | _flat(c.get("parties")))
                     & (_flat(g.get("values")) | _flat(g.get("parties")))))


def score_properties(cand: dict, gold: dict) -> dict:
    """Recall over the corpus's security goals, hit ids in ``detail``."""
    cs, gs = cand.get("properties", []), gold.get("properties", [])
    pairs, missed, extra = greedy_match(cs, gs, hit_property)
    return item(len(pairs), len(gs), extra=len(extra),
                detail=[{"hit": [g.get("id") for _, g in pairs]},
                        {"miss": [g.get("id") for g in missed]},
                        {"extra": [c.get("id") for c in extra]}])


def score_properties_aligned(cand: dict, gold: dict,
                             symbols: dict[str, str]) -> dict:
    """:func:`score_properties` after renaming the candidate's symbols."""
    from orrery.modules.scoring.symbols import rename_properties
    return score_properties(rename_properties(cand, symbols), gold)


# ── claims ───────────────────────────────────────────────────────────────────
def score_claims(cand: dict, gold: dict, cand_assum: dict, gold_assum: dict,
                 cand_props: dict, gold_props: dict, *,
                 instance_of: Callable[[str, object], object],
                 is_noop: Callable[[str, str], bool]) -> dict:
    """Over every cell the corpus claims: a claim counts when the corpus claims
    the same goal under the same world, paired by the rule the verdicts are
    (``modules/verdicts/cells``). Each scenario is spelled out as the complete
    assignment it runs, so a run that asserts a goal under the wrong world
    scores nothing for it even when both vocabularies match perfectly. A cell
    the run claims with no counterpart is ``extra``; ``detail`` lists the
    corpus's cells no claim of the run's reached.
    """
    ours = claim_cells(cand, cand_assum, is_noop)
    theirs = claim_cells(gold, gold_assum, is_noop)
    pairs = pair_cells(ours, theirs, (cand_assum, cand_props),
                       (gold_assum, gold_props), instance_of)
    reached = {(goal, id(entry)) for _, _, goal, entry in pairs}
    missed = [f"{c['id']}@{sorted((p['id'], p['subtype']) for p in e['scenario'])}"
              for c in theirs["cases"] for e in c["by_scenario"]
              if (c["id"], id(e)) not in reached]
    produced = sum(len(c["by_scenario"]) for c in ours["cases"])
    total = sum(len(c["by_scenario"]) for c in theirs["cases"])
    return item(len(pairs), total, extra=produced - len(pairs),
                detail=[{"miss": missed}])


def score_claims_aligned(cand: dict, gold: dict, cand_assum: dict,
                         gold_assum: dict, cand_props: dict, gold_props: dict,
                         assumption_symbols: dict[str, str],
                         property_symbols: dict[str, str], *,
                         instance_of: Callable[[str, object], object],
                         is_noop: Callable[[str, str], bool]) -> dict:
    """:func:`score_claims` after renaming the two candidate vocabularies."""
    from orrery.modules.scoring.symbols import rename_assumptions, rename_properties
    return score_claims(
        cand, gold,
        rename_assumptions(cand_assum, assumption_symbols), gold_assum,
        rename_properties(cand_props, property_symbols), gold_props,
        instance_of=instance_of, is_noop=is_noop)


# ── verdicts ─────────────────────────────────────────────────────────────────
# Which cell is which is cross_check's question too, and both answer it with
# one rule (modules/verdicts/cells): a goal by what it is about, a scenario by
# its answer on each object both sides speak about. ``instance_of`` is the
# assumption vocabulary's, handed in because this layer does not build it.

def score_verdicts(cand: dict, gold: dict, cand_assum: dict, gold_assum: dict,
                   cand_props: dict, gold_props: dict, *,
                   instance_of: Callable[[str, object], object]) -> dict:
    """Cell by cell over every cell the corpus has: a cell the run never executed
    counts as wrong, not absent, so dropping a scenario cannot shrink the
    denominator. A cell of the run's with no counterpart is ``extra``.
    ``detail`` lists the cells whose verdict disagrees.
    """
    pairs = pair_cells(cand, gold, (cand_assum, cand_props),
                       (gold_assum, gold_props), instance_of)
    hit, wrong = 0, []
    for _, mine, goal, theirs in pairs:
        if mine["verdict"] == theirs["verdict"]:
            hit += 1
        else:
            wrong.append({"goal": goal, "ours": mine["verdict"],
                          "expected": theirs["verdict"]})
    produced = sum(len(c.get("by_scenario", [])) for c in cand.get("cases", []))
    gold_total = sum(len(c.get("by_scenario", [])) for c in gold.get("cases", []))
    return item(hit, gold_total, extra=produced - len(pairs), detail=wrong)


def score_verdicts_aligned(cand: dict, gold: dict, cand_assum: dict,
                           gold_assum: dict, cand_props: dict, gold_props: dict,
                           assumption_symbols: dict[str, str],
                           property_symbols: dict[str, str], *,
                           instance_of: Callable[[str, object], object]) -> dict:
    """:func:`score_verdicts` after renaming the two candidate vocabularies."""
    from orrery.modules.scoring.symbols import rename_assumptions, rename_properties
    return score_verdicts(
        cand, gold,
        rename_assumptions(cand_assum, assumption_symbols), gold_assum,
        rename_properties(cand_props, property_symbols), gold_props,
        instance_of=instance_of)


# ── results (the property's own answer) ──────────────────────────────────────
def _results(doc: dict) -> dict[str, str]:
    return {r["id"]: r["verdict"] for r in doc.get("results", [])}


def score_results(cand: dict, gold: dict, cand_cases: dict, gold_cases: dict,
                  cand_assum: dict, gold_assum: dict,
                  cand_props: dict, gold_props: dict, *,
                  instance_of: Callable[[str, object], object]) -> dict:
    """One answer per property, over every property the corpus answers. A
    property the run never answered counts as wrong, not absent.

    The step writes both levels of the answer and both are scored here so they
    cannot disagree: the headline is the property's three-valued conjunction over
    the threat models claiming it, and ``cells`` carries the per-scenario verdicts,
    where a run that reached the right answer in the wrong world shows up.
    """
    pmap = pair_goals(cand_props, gold_props)
    gres = _results(gold)
    hit, extra, wrong = 0, 0, []
    for pid, verdict in _results(cand).items():
        key = pmap.get(pid)
        if key is None or key not in gres:
            extra += 1
            continue
        if gres[key] == verdict:
            hit += 1
        else:
            wrong.append({"property": key, "ours": verdict,
                          "expected": gres[key]})
    cells = score_verdicts(cand_cases, gold_cases, cand_assum, gold_assum,
                           cand_props, gold_props, instance_of=instance_of)
    return item(hit, len(gres), extra=extra, detail=wrong,
                cells={k: cells[k] for k in ("num", "den", "score", "extra")})


def score_results_aligned(cand: dict, gold: dict, cand_cases: dict,
                          gold_cases: dict, cand_assum: dict, gold_assum: dict,
                          cand_props: dict, gold_props: dict,
                          assumption_symbols: dict[str, str],
                          property_symbols: dict[str, str], *,
                          instance_of: Callable[[str, object], object]) -> dict:
    """:func:`score_results` after renaming the two candidate vocabularies."""
    from orrery.modules.scoring.symbols import rename_assumptions, rename_properties
    return score_results(
        cand, gold, cand_cases, gold_cases,
        rename_assumptions(cand_assum, assumption_symbols), gold_assum,
        rename_properties(cand_props, property_symbols), gold_props,
        instance_of=instance_of)


# ── flow ─────────────────────────────────────────────────────────────────────
_FLOW_GATES = ("flow_typecheck", "flow_reachability")


def score_flow(checks: dict, gold=None) -> dict:
    """The two gates, typecheck and reachability, and nothing else: a model that
    parses and whose roles reach their honest end is not thereby correct, and the
    semantic measurement is the verdict score of a run given every declaration
    but the flow.

    ``gold`` is accepted and ignored, so every judgement has one call shape."""
    g = {k: bool(checks.get(k)) for k in _FLOW_GATES}
    return item(sum(g.values()), len(_FLOW_GATES), **g)
