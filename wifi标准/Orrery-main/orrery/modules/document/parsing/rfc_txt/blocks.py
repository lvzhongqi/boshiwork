"""Section-body splitter for RFC plain text.

The input is one section's body lines, cleaned of page artifacts and still at
their original column positions. Blank lines separate chunks; a chunk becomes a
reflowed ``Paragraph``, or a ``CodeBlock`` dedented only to the chunk's common
indent when it carries layout a newline-to-space reflow would destroy.
"""
from __future__ import annotations

import re

from orrery.modules.document.model.block import (
    CodeBlock,
    ContentBlock,
    Paragraph,
)

# Internal column alignment (3+ spaces between non-space chars): tables and
# aligned key-value lists.
_INTERIOR_GAP = re.compile(r"\S {3,}\S")
_BOX_CHARS = re.compile(r"[+|]")


def lines_to_blocks(lines: list[str]) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"p{counter}"

    for chunk in _split_chunks(lines):
        if _is_verbatim(chunk):
            text = _dedent(chunk)
            blocks.append(CodeBlock(block_id=next_id(), text=text))
        else:
            text = _reflow(chunk)
            if text:
                blocks.append(Paragraph(block_id=next_id(), text=text))
    return blocks


def _split_chunks(lines: list[str]) -> list[list[str]]:
    """Split into blank-line-separated groups of non-blank lines."""
    chunks: list[list[str]] = []
    cur: list[str] = []
    for line in lines:
        if line.strip():
            cur.append(line)
        elif cur:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def _is_verbatim(chunk: list[str]) -> bool:
    """True when the chunk carries layout a reflow would destroy: box or pipe
    characters, interior column alignment, or leading whitespace still left on
    a line after the chunk's common indent is removed."""
    for line in chunk:
        if _BOX_CHARS.search(line):
            return True
        if _INTERIOR_GAP.search(line):
            return True
    common = _common_indent(chunk)
    for line in chunk:
        rest = line[common:]
        if rest and rest[0] == " ":
            return True
    return False


def _common_indent(chunk: list[str]) -> int:
    widths = [len(line) - len(line.lstrip(" ")) for line in chunk if line.strip()]
    return min(widths) if widths else 0


def _dedent(chunk: list[str]) -> str:
    common = _common_indent(chunk)
    return "\n".join(line[common:] if line.strip() else "" for line in chunk)


def _reflow(chunk: list[str]) -> str:
    """Collapse a hard-wrapped prose chunk back into one logical line. RFCs do
    not hyphenate at line breaks, so a plain space-join is safe."""
    return " ".join(line.strip() for line in chunk if line.strip())


__all__ = ["lines_to_blocks"]
