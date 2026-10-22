"""Structural parser: cleaned RFC text → SectionTree.

Headings sit at column 0 and body lines are indented, so the parser opens a
``Section`` on every heading match and attaches it through a level-indexed
stack. Numeric (``5.2.``) and appendix (``Appendix A.``, ``A.1.``) headings
share one tree, appendices entering as level-1 siblings, so references reach
either kind through ``Section.number``. A non-contiguous number is accepted.
"""
from __future__ import annotations

import re

from orrery.modules.document.parsing.rfc_txt.blocks import (
    lines_to_blocks,
)
from orrery.modules.document.model.section import Section
from orrery.modules.document.model.section_tree import SectionTree

# The trailing period is optional: RFC 2617 writes ``2 Basic Authentication
# Scheme``, and requiring one collapses such a document into a single heading.
# Column 0 is what makes a line a heading; body text is indented.
_NUMERIC = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$")
_APPENDIX_TOP = re.compile(r"^Appendix\s+([A-Z])\.?\s+(\S.*)$")
_APPENDIX_SUB = re.compile(r"^([A-Z]\.\d+(?:\.\d+)*)\.?\s+(\S.*)$")


class RFCSectionTreeParser:
    def parse(self, text: str) -> SectionTree:
        lines = text.split("\n")
        tree = SectionTree(root=Section(number="", title="", level=0))

        stack: list[Section] = []
        cur: Section | None = None
        buf: list[str] = []

        def close_current() -> None:
            if cur is not None:
                cur.blocks = lines_to_blocks(buf)

        for line in lines:
            parsed = _try_heading(line)
            if parsed is None:
                if cur is not None:
                    buf.append(line)
                continue

            number, title, level = parsed
            close_current()
            buf = []

            while stack and stack[-1].level >= level:
                stack.pop()

            section = Section(number=number, title=title, level=level)
            parent = stack[-1] if stack else tree.root
            parent.add_child(section)
            stack.append(section)
            cur = section

        close_current()
        return tree


def _try_heading(line: str) -> tuple[str, str, int] | None:
    """Return (number, title, level) if ``line`` is a heading, else None.
    Heading lines start at column 0; level comes from the dot count."""
    if not line or line[0] == " ":
        return None

    m = _APPENDIX_TOP.match(line)
    if m:
        return m.group(1), m.group(2).rstrip(), 1

    m = _APPENDIX_SUB.match(line)
    if m:
        number = m.group(1)
        level = number.count(".") + 1
        return number, m.group(2).rstrip(), level

    m = _NUMERIC.match(line)
    if m:
        number = m.group(1)
        level = number.count(".") + 1
        return number, m.group(2).rstrip(), level

    return None


__all__ = ["RFCSectionTreeParser"]
