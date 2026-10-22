"""Node 10, cross_check (optional): compare one run against ground truth.
Pure code. Runs only when run(ground_truth=…) was given; without it the node
emits a note and finishes ok.

Artifact: cross_check.json — one row per compared result, one per compared
cell, the two mismatch lists, how many cells the run produced, and cell
accuracy.

Cells are paired by what they are about, not by name
(``modules/verdicts/cells``): a goal by its type, subtype, values and parties,
a scenario by its answer on each object (axis and target instance), over the
objects both sides speak about. A run that extracted its own vocabulary names
everything differently from the corpus and still compares cell by cell. Rows
keep the run's own ids, so a cell joins back onto the scenario that produced
it, and name the corpus cell they were compared with.

Symbols are the one thing still compared as written: a target's object and a
goal's values and parties. A run that extracted its vocabulary may call the
corpus's ``skU`` ``sk_U``, so before pairing its assumptions and properties are
renamed through the symbol alignments the scoring files under ``eval/`` (the
orchestrator waits for them before this node starts). A symbol the alignment
leaves out keeps its name. A supplied vocabulary is the corpus's own and is not
renamed. An alignment that is missing or failed is not this run's fault: the
node compares by the names as written, says so as a warning, and records it in
``symbol_alignment`` beside where each map came from.

Only the intersection is compared: the corpus keeps every scenario while a run
executes only the ones the claims list. A cell mismatch raises CheckFailed —
the node ran fine and its report is on disk; what failed is the comparison.
The ground-truth handle is scoped to this node alone, and layout does not
expose the path.
"""

from __future__ import annotations

import json
from pathlib import Path

from orrery.modules.libschema.version import require_vocab_version
from orrery.modules.scoring.symbols import (
    latest_alignment, rename_assumptions, rename_properties)
from orrery.modules.verdicts.cells import pair_cells, pair_goals
from orrery.nodes.apply.realizers import VOCAB
from orrery.nodes.base import CheckFailed, Node, NodeError, RunEnv
from orrery.services.events import CrossChecked, NodeProgress
from orrery.services.store.atomic import write_json


def _scenario(points: list[dict]) -> list[dict]:
    """A scenario in cases_results' encoding, sorted by id."""
    return [{"id": i, "subtype": s}
            for i, s in sorted((p["id"], p["subtype"]) for p in points)]


def compare(ours_results: dict, ours_cases: dict,
            gt_results: dict, gt_cases: dict, *,
            ours_vocab: tuple[dict, dict], gt_vocab: tuple[dict, dict]) -> dict:
    """Compare results entry by entry and cases cell by cell, over the
    intersection only. Each ``*_vocab`` is that side's ``(assumptions.json,
    properties.json)``, which is what a goal and a scenario are resolved
    through. Returns the comparison report as a dict."""
    goals = pair_goals(ours_vocab[1], gt_vocab[1])
    ov = {x["id"]: x["verdict"] for x in ours_results["results"]}
    gv = {x["id"]: x["verdict"] for x in gt_results["results"]}
    # Every compared answer, not only the ones that differ: readers need the
    # agreements too, and subtracting mismatches from answers is a join.
    res_rows = [{"id": k, "corpus_id": goals[k], "ours": v,
                 "expected": gv[goals[k]], "match": v == gv[goals[k]]}
                for k, v in ov.items() if goals.get(k) in gv]
    res_mism = [{k: r[k] for k in ("id", "ours", "expected")}
                for r in res_rows if not r["match"]]

    # Only the intersection: a cell with no counterpart takes no part. The
    # scenario keeps the run's own encoding, so a cell joins back onto the
    # scenario that produced it.
    cells = [{"id": gid, "scenario": _scenario(mine["scenario"]),
              "corpus_id": corpus_id,
              "corpus_scenario": _scenario(corpus["scenario"]),
              "ours": mine["verdict"], "expected": corpus["verdict"],
              "match": mine["verdict"] == corpus["verdict"]}
             for gid, mine, corpus_id, corpus in pair_cells(
                 ours_cases, gt_cases, ours_vocab, gt_vocab, VOCAB.instance_of)]
    matched = sum(1 for c in cells if c["match"])
    return {
        "results_total": len(res_rows),
        "results": res_rows,
        "results_mismatches": res_mism,
        # Both halves of the denominator. cases_compared alone cannot say
        # whether a small number means a small question or an intersection
        # that mostly missed: a cell takes part only when the corpus has the
        # same goal under a scenario giving the same answers, and one that
        # does not line up drops out of the accuracy without a trace.
        "cases_produced": sum(len(c["by_scenario"]) for c in ours_cases["cases"]),
        "cases_compared": len(cells),
        "cases_matched": matched,
        "cases_mismatches": [{k: c[k] for k in ("id", "scenario", "ours", "expected")}
                             for c in cells if not c["match"]],
        "cells": cells,
        "acc": (matched / len(cells)) if cells else None,
    }


_RENAMED = (("assumptions", "extract_assumptions", rename_assumptions),
            ("properties", "extract_properties", rename_properties))


def _aligned(env: RunEnv, vocab: tuple[dict, dict]
             ) -> tuple[tuple[dict, dict], dict, list[str]]:
    """The run's ``(assumptions, properties)`` renamed onto the corpus's
    symbols, how each was renamed, and a warning per map that could not be
    used."""
    out, record, warnings = list(vocab), {}, []
    for i, (slug, node, rename) in enumerate(_RENAMED):
        if node in env.pinned():
            record[slug] = {"supplied": True}
            continue
        try:
            mapping, path = latest_alignment(env.layout.run_dir / "eval", slug)
        except ValueError as e:
            record[slug] = {"unavailable": str(e)}
            warnings.append(f"warning: {e}; {slug} symbols compared as written")
            continue
        out[i] = rename(vocab[i], mapping)
        record[slug] = {"source": env.layout.rel(path), "mapping": mapping}
    return tuple(out), record, warnings


class CrossCheckNode(Node):
    name = "cross_check"
    short = "cross-check"
    task = "Compare against ground truth, cell by cell"

    def is_done(self, env: RunEnv) -> bool:
        if env.ground_truth is None:
            return True       # Not enabled: counts as done on re-entry.
        return env.layout.has(self.name, "cross_check.json")

    async def run(self, env: RunEnv) -> None:
        if env.ground_truth is None:
            # Nothing to compare, yet the step still finishes ok and the strip
            # ticks it. Said out loud, because a tick with no accuracy reads
            # the same as "compared, all matched".
            if env.bus is not None:
                env.bus.emit(NodeProgress(
                    run=env.layout.run_name, node=self.name,
                    text="no ground truth was given for this protocol; "
                         "nothing to compare against"))
            return
        gt = Path(env.ground_truth)
        claims = env.layout.node_dir("extract_claims")

        def lib(path: Path, kind: str) -> dict:
            # Version gating: an older schema encodes scenarios differently,
            # which would surface as a silently empty intersection.
            return require_vocab_version(json.loads(path.read_text()),
                                         kind=kind, path=str(path))

        ours_vocab, renamed, warnings = _aligned(env, (
            json.loads((claims / "assumptions.json").read_text()),
            json.loads((claims / "properties.json").read_text())))
        try:
            report = compare(
                json.loads(env.layout.results_json.read_text()),
                json.loads(env.layout.cases_results_json.read_text()),
                lib(gt / "results" / "results.json", "results"),
                lib(gt / "results" / "cases_results.json", "cases_results"),
                ours_vocab=ours_vocab,
                gt_vocab=(lib(gt / "claims" / "assumptions.json", "assumptions"),
                          lib(gt / "claims" / "properties.json", "properties")),
            )
        except FileNotFoundError as e:
            raise NodeError(f"cross_check failed: ground truth missing; {e}") from None
        report["symbol_alignment"] = renamed
        report["warnings"] = warnings
        write_json(env.layout.cross_check_json, report)
        if env.bus is not None:
            for text in warnings:
                env.bus.emit(NodeProgress(run=env.layout.run_name,
                                          node=self.name, text=text))
        if env.bus is not None:
            # Into the ledger before the failure below, so work.md can put each
            # scenario's verdict next to the answer it was supposed to give.
            # Cells locate a disagreement; results rows name the right answer.
            env.bus.emit(CrossChecked(
                run=env.layout.run_name, node=self.name,
                cells=report["cells"], results=report["results"]))
        if report["cases_produced"] and not report["cases_compared"]:
            # Nothing lined up at all. Silent until now: with no cells there
            # are no mismatches, so the node passed, acc was null and the run
            # reported ok — an answer of "we agree" from a comparison that
            # never happened. Measured once in 254 runs, and it hid a run that
            # was in fact right about every cell.
            #
            # Whether that is a failed check depends on whose vocabulary the
            # cells are written in. Supplied, it is the corpus's own, and
            # nothing lining up means the two sides encode their cells
            # differently. Extracted, the run may simply have asked about
            # other goals or other worlds than the corpus: the comparison has
            # no denominator and says so, and nothing failed.
            if "extract_assumptions" not in env.pinned():
                if env.bus is not None:
                    env.bus.emit(NodeProgress(
                        run=env.layout.run_name, node=self.name,
                        text=f"no cell accuracy: none of the "
                             f"{report['cases_produced']} cell(s) is about a "
                             f"goal and a scenario the corpus also has; only "
                             f"the per-goal results were compared"))
                return
            raise CheckFailed(
                f"the {report['cases_produced']} cell(s) this run produced "
                f"share no scenario with the ground truth, so nothing was "
                f"compared and there is no accuracy. A cell pairs on its goal "
                f"and on the answers its scenario gives, and this run was "
                f"handed the corpus's own vocabulary, so the two sides encode "
                f"their cells differently: check that the corpus's "
                f"cases_results.json is written against its own claims.")
        if report["cases_mismatches"]:
            # The cells decide, not the results rows. A results row is the
            # conjunction of its own cells, so it can agree with ground truth
            # while individual worlds disagree; the reverse never happens.
            # CheckFailed, not NodeError: the comparison ran and its report is
            # written, and the message carries no failure word of its own
            # because every caller prefixes one.
            raise CheckFailed(
                f"{len(report['cases_mismatches'])} of "
                f"{report['cases_compared']} cells differ from the ground "
                f"truth; see this step's own cross_check.json. Check the "
                f"ground truth itself first, then the flow model or apply."
            )
