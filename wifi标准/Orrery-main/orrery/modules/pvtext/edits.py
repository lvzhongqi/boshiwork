"""A few mechanical rewrites of `.pv` text for the framework's own purposes.

The model decides what assumptions and goals change and submits anchored edits
(:mod:`orrery.modules.pvtext.anchored`); the functions here cover the rewrites
the framework does itself, namely inject's declaration block and query section.
All are deterministic and raise on anything they cannot do. The honest-run
probe's own rewrites live in :mod:`orrery.modules.pvtext.probe`.
"""
from __future__ import annotations

from orrery.modules.pvtext.parse import (
    PvTextError,
    process_blocks,
    query_spans,
)


def replace_queries(text: str, queries: list[str]) -> str:
    """Delete the existing ``query ….`` statements and insert ``queries`` before
    the first process definition. Each item is a complete statement carrying its
    own ``query`` keyword and period; an empty list only deletes. Raises
    :class:`PvTextError` when the text has no process definition to insert
    before.
    """
    spans = query_spans(text)
    out = text
    for start, end in reversed(spans):
        out = out[:start] + out[end:]

    blocks = process_blocks(out)
    if not queries:
        return out
    if not blocks:
        raise PvTextError(
            "replace_queries failed: no process definition found; appending at the end "
            "of the file would produce an invalid .pv"
        )
    anchor = min(b.start for b in blocks.values())
    block = "\n".join(queries)
    return out[:anchor] + block + "\n\n" + out[anchor:]


def append_declarations(text: str, lines: list[str]) -> str:
    """Insert declaration lines (events, free names, and the like) before the
    first process definition. Raises :class:`PvTextError` when the text has no
    process definition."""
    if not lines:
        return text
    blocks = process_blocks(text)
    if not blocks:
        raise PvTextError(
            "append_declarations failed: no process definition found; appending at the "
            "end of the file would produce an invalid .pv"
        )
    anchor = min(b.start for b in blocks.values())
    return text[:anchor] + "\n".join(lines) + "\n\n" + text[anchor:]
