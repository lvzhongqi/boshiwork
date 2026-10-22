"""Section-body splitter: a section's raw lines → typed ContentBlocks.

A code fence becomes a CodeBlock, a ``|...|`` header plus separator row becomes
a Table carrying the raw markdown, a standalone ``![cap](path)`` line becomes an
Image, and everything else is grouped by blank lines into Paragraphs.
"""
from __future__ import annotations

import re

from orrery.modules.document.model.block import (
    CodeBlock,
    ContentBlock,
    Image,
    Paragraph,
    Table,
)


_IMG_ONLY = re.compile(r"^\s*!\[([^\]]*)\]\(([^)]+)\)\s*$")
_TABLE_SEP_CELL = re.compile(r"^:?-+:?$")


def lines_to_blocks(lines: list[str]) -> list[ContentBlock]:
    """Turn a section's raw body lines into a list of typed ContentBlocks.

    block_id runs ``p1``, ``p2``, … across the whole section regardless of
    block kind, so an id stays stable only while the blocks before it do.
    """
    blocks: list[ContentBlock] = []
    n = len(lines)
    i = 0
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"p{counter}"

    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        if line.lstrip().startswith(("```", "~~~")):
            # Both fence forms, closed by the same one that opened: the
            # normalizer already treats ``~~~`` as code, so a block it kept
            # whole must not be split into paragraphs here.
            fence = line.lstrip()[:3]
            lang = line.lstrip()[3:].strip()
            i += 1
            start = i
            while i < n and not lines[i].lstrip().startswith(fence):
                i += 1
            code_text = "\n".join(lines[start:i])
            i += 1  # consume closing fence (or EOF)
            blocks.append(CodeBlock(block_id=next_id(), language=lang, text=code_text))
            continue

        if line.lstrip().startswith("|") and i + 1 < n and _is_table_separator(lines[i + 1]):
            start = i
            i += 1
            while i < n and lines[i].lstrip().startswith("|"):
                i += 1
            raw = "\n".join(lines[start:i])
            blocks.append(Table(block_id=next_id(), raw_markdown=raw))
            continue

        # An image line only counts as an Image block when nothing follows it
        # on the next line; otherwise it is part of a paragraph.
        m_img = _IMG_ONLY.match(line)
        if m_img and (i + 1 >= n or not lines[i + 1].strip()):
            blocks.append(Image(
                block_id=next_id(),
                caption=m_img.group(1),
                path=m_img.group(2),
            ))
            i += 1
            continue

        start = i
        while i < n and lines[i].strip():
            i += 1
        text = "\n".join(lines[start:i])
        blocks.append(Paragraph(block_id=next_id(), text=text))

    return blocks


def _is_table_separator(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return False
    inner = stripped.strip("|").strip()
    if not inner:
        return False
    for cell in inner.split("|"):
        if not _TABLE_SEP_CELL.fullmatch(cell.strip()):
            return False
    return True
