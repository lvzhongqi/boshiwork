"""The scoped-main search façade behind the grep_document tool.

It searches the already sub-protocol-pruned main document, reports which section
each hit sits in plus a few lines of context, and follows the hit sections'
annotated references to pull in referenced text under a character budget
(overflow is listed in a skipped marker). Reference documents themselves are
reachable only through ``read_section``. The work happens in ``DocumentSet.grep``.
"""

from __future__ import annotations

from orrery.modules.document.model.document_set import DocumentSet


def grep(doc_set: DocumentSet, pattern: str, *, max_matches: int = 10,
         context_lines: int = 3, ref_char_budget: int = 8000) -> str:
    """Case-insensitive substring search over the main document, rendered as
    text. An empty pattern returns an empty string."""
    return doc_set.grep(
        pattern,
        max_matches=max_matches,
        context_lines=context_lines,
        ref_char_budget=ref_char_budget,
    )
