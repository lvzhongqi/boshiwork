"""The vocabulary this build is written in: what every assumption subtype,
every goal subtype and every pipeline step means, one sentence apiece.

Not per-run and not on any ledger — the same for every run this build serves,
read straight off the realizer/injector registries and the node table that own
it. Both front ends ask here, so no page carries a copy of its own to drift.
"""

from __future__ import annotations

import yaml

from orrery.api.corpus_usage import scan_usage
from orrery.api.reading_order import name_rank
from orrery.nodes.apply.realizers import REALIZERS, VOCAB
from orrery.nodes.inject.injectors import INJECTORS, PROP_VOCAB
from orrery.nodes.world.builders import WORLD_VOCAB
from orrery.pipeline.table import build_table
from orrery.version import VOCAB_VERSION


def _by_kind(registry: dict) -> dict:
    """``{(kind, subtype): class}`` -> ``{kind: {subtype: description}}``."""
    out: dict = {}
    for (kind, subtype), cls in registry.items():
        out.setdefault(kind, {})[subtype] = cls.description
    return out


def vocabulary() -> dict:
    """Every closed vocabulary a front end has to name things with."""
    table = build_table()
    return {
        "assumptions": _by_kind(REALIZERS),
        "goals": _by_kind(INJECTORS),
        # One sentence per pipeline step, identical in every run.
        "steps": {n.name: n.task for n in table},
        # The one word each step is drawn with, declared by the node itself
        # (nodes/base.py), so a strip needs no alias table of its own.
        "step_short": {n.name: n.short for n in table},
        # What each step waits on. The table is a list, the real shape is a DAG
        # — assumptions and properties run side by side and extract_claims
        # joins them. Empty means the plain linear default.
        "depends_on": {n.name: list(n.depends_on) for n in table},
        # The steps that still run after a comparison said no, so a console
        # can offer one as the next step of a run that ended check_failed.
        "after_check_failure": [n.name for n in table
                                if n.runs_after_check_failure],
        # No axis is world-level: world assumptions live in the world section
        # of assumptions.json and never appear in an assignment. The key stays
        # so a reader's world/root split keeps meaning "nothing in the world
        # tier".
        "world_axes": [],
    }


def as_text() -> str:
    """The two vocabularies as humans read them, straight from the registries.
    Generated on demand, so there is no stored vocabulary file to go stale."""
    lines: list[str] = []
    w = lines.append
    from orrery.nodes.inject.injectors import PROP_VOCAB

    # A corpus file loads only under a build whose vocabulary carries this same
    # number (orrery/version.py).
    w(f"vocabulary {VOCAB_VERSION}\n")
    w("── assumptions (axis.subtype, weakest first per axis) ──")
    last_cat = None
    for axis in VOCAB.axes():
        cat = VOCAB.obj_of(axis)
        if cat != last_cat:
            w(f"\n[{cat}]")
            last_cat = cat
        w(f"  {axis}")
        for sub in VOCAB.dimension_values(axis):
            marks = []
            if VOCAB.is_structural(axis, sub):
                marks.append("structural")
            if VOCAB.is_stub(axis, sub):
                marks.append("stub")
            stronger = VOCAB.stronger_than(axis, sub)
            if stronger:
                marks.append(f"stronger than {', '.join(sorted(stronger))}")
            tag = f" ({'; '.join(marks)})" if marks else ""
            w(f"    {sub}{tag}")
            w(f"      {VOCAB.description(axis, sub)}")
            params = VOCAB.params(axis, sub)
            if params:
                fields = ", ".join(
                    f"{f}:{s['kind']}" + ("" if s.get("required", True) else "?")
                    for f, s in params.items())
                w(f"      target: {fields}")

    w("\n── properties (type.subtype) ──")
    for gtype in PROP_VOCAB.types():
        w(f"\n{gtype}  (parties: {PROP_VOCAB.parties_shape(gtype)}, "
              f"realization: {PROP_VOCAB.realization(gtype)})")
        for sub in PROP_VOCAB.subtypes_of(gtype):
            tag = " (stub)" if PROP_VOCAB.is_stub(gtype, sub) else ""
            w(f"  {sub}{tag}")
            w(f"    {PROP_VOCAB.description(gtype, sub)}")
            req = PROP_VOCAB.requires_assumption(gtype, sub)
            if req:
                w(f"    requires assumption: {req['axis']} in {list(req['subtypes'])}")
    w("")
    return "\n".join(lines) + "\n"


def as_yaml(corpus_roots=()) -> str:
    """The vocabularies as YAML, generated from the realizer and injector
    declarations. A snapshot for reading, not a source of truth.

    Two top-level keys: ``kb`` is the vocabularies themselves, carrying the
    partial order (direct stronger_than edges, subtypes weakest-first), and
    ``corpus_usage`` is the corpus read backwards — protocol directory to the
    subtypes its targets declare, measured on the spot.
    """
    lines: list[str] = []
    w = lines.append

    assumptions: dict = {}
    for axis in VOCAB.axes():
        cat = VOCAB.obj_of(axis)
        axis_node = assumptions.setdefault(cat, {}).setdefault(
            axis, {"subtypes": {}})
        node = axis_node["subtypes"]
        for sub in VOCAB.dimension_values(axis):
            cls = REALIZERS[(axis, sub)]
            entry: dict = {"description": VOCAB.description(axis, sub)}
            entry["structural"] = VOCAB.is_structural(axis, sub)
            if VOCAB.is_stub(axis, sub):
                entry["status"] = "stub"
            if cls.stronger_than:
                entry["stronger_than"] = list(cls.stronger_than)
            if VOCAB.params(axis, sub):
                entry["target"] = {
                    f: s["kind"] + ("" if s.get("required", True) else " (optional)")
                    for f, s in VOCAB.params(axis, sub).items()}
            if cls.writings:
                entry["writings"] = list(cls.writings)
            node[sub] = entry

    properties: dict = {}
    for gt in PROP_VOCAB.types():
        node = properties.setdefault(gt, {
            "parties": PROP_VOCAB.parties_shape(gt),
            "realization": PROP_VOCAB.realization(gt)})
        for sub in PROP_VOCAB.subtypes_of(gt):
            entry = {"description": PROP_VOCAB.description(gt, sub)}
            if PROP_VOCAB.is_stub(gt, sub):
                entry["status"] = "stub"
            req = PROP_VOCAB.requires_assumption(gt, sub)
            if req:
                entry["requires_assumption"] = {
                    "axis": req["axis"], "subtypes": list(req["subtypes"])}
            node[sub] = entry

    # Empty when no corpus is configured or present; the vocabulary half above
    # stands on its own.
    usage = scan_usage(corpus_roots)
    grouped = usage.by_protocol()
    corpus_usage = {rel: {"files": len(grouped[rel]),
                          "subtypes": usage.coords_of(rel)}
                    for rel in sorted(grouped, key=name_rank)}

    w("# Generated from the realizer/injector class declarations "
      "(orrery kb).")
    w("# A reading snapshot, not a source of truth — regenerate from code.")
    # A corpus file loads only under a build carrying this same number.
    w(f"# vocabulary version: {VOCAB_VERSION}")
    w("# kb: every assumption axis is commutative (set semantics, any "
      "order equivalent).")
    w("# world: world-level assumptions declared per protocol in the")
    w("# 'world' section of assumptions.json and applied once, before any "
      "object-level assumption point.")
    w("# Subtypes are listed weakest-first; stronger_than gives the direct "
          "partial-order edges.")
    w("# corpus_usage: the corpus read backwards, protocol directory -> "
      "the assumption")
    w("# subtypes declared under it, and how many assumptions.json files "
          "that was. Keyed by the")
    w("# corpus's own path; empty when no corpus was scanned.")
    w(f"# scanned: {', '.join(usage.roots) or '(none)'}\n")
    w(yaml.safe_dump({"kb": {"world": {a: WORLD_VOCAB.subtypes(a)
                                       for a in WORLD_VOCAB.axes()},
                             "assumptions": assumptions,
                             "properties": properties},
                      "corpus_usage": corpus_usage},
                     sort_keys=False, allow_unicode=True, width=100).rstrip("\n"))
    return "\n".join(lines) + "\n"
