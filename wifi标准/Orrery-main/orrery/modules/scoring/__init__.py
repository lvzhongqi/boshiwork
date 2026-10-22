"""Scoring: what each extraction step produced, against what the corpus says.

The judgements live in :mod:`rules` and take two parsed documents; :data:`PRODUCTS`
says, for each step, which file is its product and which corpus file answers it.
The orchestrator reads the files and writes the result, so nothing here opens a
file or reaches a corpus path. A score is output only: it is not in RunEnv, no
repair round sees it, and it gates nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from orrery.modules.scoring.rules import (  # noqa: F401  (re-exported)
    greedy_match, item, score_assumptions, score_assumptions_aligned,
    score_claims, score_claims_aligned, score_flow, score_principals,
    score_principals_aligned, score_properties, score_properties_aligned,
    score_results, score_results_aligned, score_verdicts,
    score_verdicts_aligned,
)


@dataclass(frozen=True)
class Spec:
    """How to score one step: its own product, the corpus file that answers it,
    and any other steps' products the judgement needs on both sides.

    ``needs`` serves the judgements over scenarios. A scenario is a set of
    assumption references, so claims and verdicts have to be said in the corpus's
    ids, and that map is built from both sides' assumption and property files.
    """
    slug: str
    product: str
    gold: str | None
    fn: object
    needs: tuple[str, ...] = field(default=())
    #: Further ``(product, gold)`` pairs written by this same step, read after
    #: the first pair and before ``needs``. The aggregate step's two files are
    #: two levels of one answer and are scored together so they cannot disagree.
    also: tuple[tuple[str, str], ...] = field(default=())


#: step name → Spec. Keys are node names, which is what the caller has in hand;
#: nothing here imports a node.
PRODUCTS: dict[str, Spec] = {
    "extract_principals": Spec(
        "principals", "principals.json", "flow/principals.json",
        score_principals),
    "extract_flow": Spec(
        "flow", "checks.json", None, score_flow),
    "extract_assumptions": Spec(
        "assumptions", "assumptions.json", "claims/assumptions.json",
        score_assumptions),
    "extract_properties": Spec(
        "properties", "properties.json", "claims/properties.json",
        score_properties),
    "extract_claims": Spec(
        "claims", "claims.json", "claims/claims.json", score_claims,
        needs=("extract_assumptions", "extract_properties")),
    "aggregate": Spec(
        "verdicts", "results.json", "results/results.json", score_results,
        also=(("cases_results.json", "results/cases_results.json"),),
        needs=("extract_assumptions", "extract_properties")),
}
