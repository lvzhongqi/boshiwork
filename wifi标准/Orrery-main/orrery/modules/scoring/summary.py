"""The shape of one row in a run's ``eval/summary.json``.

Two pure transforms: dicts in, dicts out, no filesystem and no run layout.
``pipeline.main`` writes the file as a run scores each step, and which files
hold the score and the alignment is its business, not this module's.
"""

from __future__ import annotations


def score_row(slug: str, score: dict) -> dict:
    """One product's numbers, named by its slug.

    ``detail`` is dropped: this file is what an experiment table reads, and the
    per-entry breakdown stays in the sidecar it came from.
    """
    return {"slug": slug,
            **{k: v for k, v in score.items() if k != "detail"}}


def public_alignment(alignment: dict) -> dict:
    """The part of a symbol alignment a summary row carries: its status, plus
    either the mappings or the failure reason.

    A failed alignment keeps its reason, since a score computed without an
    alignment means something different from one computed with it.
    """
    public = {"status": alignment.get("status", "failed")}
    if public["status"] != "ok":
        public["error"] = alignment.get("error", "alignment failed")
        return public
    if "mappings" in alignment:
        public["mappings"] = alignment["mappings"]
    else:
        public["principal_mappings"] = alignment.get("principal_mappings", [])
        public["symbol_mappings"] = alignment.get("symbol_mappings", [])
    return public
