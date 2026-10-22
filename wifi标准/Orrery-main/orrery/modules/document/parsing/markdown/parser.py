"""Structural parser: normalized Markdown text → SectionTree.

The input must already be cleaned and normalized. Number depth has to match
``#`` depth and decimal siblings have to be contiguous, but appendix namespaces
(``A``, ``C.2.2``) may skip letters; one unnumbered ``#`` title is allowed.
Anything off-contract raises RuntimeError rather than being repaired here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from orrery.modules.document.parsing.markdown.blocks import (
    lines_to_blocks,
)
from orrery.modules.document.model.section import Section
from orrery.modules.document.model.section_tree import SectionTree


_HASHES = re.compile(r"^(#{1,10})\s+(.*\S)\s*$")
_NUMBERED = re.compile(
    r"^((?:\d+(?:\.\d+)*|[A-Z](?:\.\d+)*))\.?\s+(.+?)\s*$"
)


@dataclass
class _NumberingState:
    last_idx: dict[int, str]
    last_parent: dict[int, tuple[str, ...]]


class SectionTreeParser:
    """Parse already-canonical Markdown into a SectionTree."""

    def parse(self, text: str) -> SectionTree:
        lines = text.split("\n")
        tree = SectionTree(root=Section(number="", title="", level=0))

        idx, tree.header = self._consume_header(lines)
        idx, tree.doc_title = self._consume_doc_title(lines, idx)

        stack: list[Section] = []
        state = _NumberingState(last_idx={}, last_parent={})
        cur: Section | None = None
        buf: list[str] = []

        def close_current() -> None:
            if cur is not None:
                cur.blocks = lines_to_blocks(buf)

        for line in lines[idx:]:
            m_h = _HASHES.match(line)
            if not m_h:
                if cur is not None:
                    buf.append(line)
                continue

            hashes_level = len(m_h.group(1))
            rest = m_h.group(2).strip()
            if hashes_level == 1:
                raise RuntimeError(
                    f"Unexpected second top-level '# ' title: {line!r}"
                )
            m_n = _NUMBERED.match(rest)
            if not m_n:
                raise RuntimeError(f"Section title must be numbered: {line!r}")
            number_parts = m_n.group(1).split(".")
            title = m_n.group(2).strip()
            level = hashes_level - 1
            if len(number_parts) != level:
                raise RuntimeError(
                    f"Hashes/number depth mismatch (depth={level}, got "
                    f"{len(number_parts)} number parts): {line!r}"
                )

            self._validate_numbering(stack, level, number_parts, title, state)

            close_current()
            buf = []

            while stack and stack[-1].level >= level:
                stack.pop()

            section = Section(
                number=".".join(number_parts),
                title=title,
                level=level,
            )
            if stack:
                stack[-1].add_child(section)
            else:
                if level != 1:
                    raise RuntimeError(
                        f"First section must be level 1, got level {level}: {line!r}"
                    )
                tree.root.add_child(section)
            stack.append(section)

            state.last_idx[level] = number_parts[-1]
            state.last_parent[level] = tuple(number_parts[:-1])
            for deeper in [k for k in list(state.last_idx) if k > level]:
                state.last_idx.pop(deeper)
                state.last_parent.pop(deeper)
            cur = section

        close_current()
        return tree

    @staticmethod
    def _consume_header(lines: list[str]) -> tuple[int, str]:
        for i, line in enumerate(lines):
            if _HASHES.match(line):
                return i, "\n".join(lines[:i])
        return len(lines), "\n".join(lines)

    @staticmethod
    def _consume_doc_title(lines: list[str], idx: int) -> tuple[int, str]:
        if idx >= len(lines):
            return idx, ""
        m = _HASHES.match(lines[idx])
        if m and len(m.group(1)) == 1:
            rest = m.group(2).strip()
            if _NUMBERED.match(rest):
                raise RuntimeError(
                    f"Top-level '# ' title must not be numbered: {lines[idx]!r}"
                )
            return idx + 1, rest
        return idx, ""

    @staticmethod
    def _validate_numbering(
        stack: list[Section],
        level: int,
        number: list[str],
        title: str,
        state: _NumberingState,
    ) -> None:
        parent_prefix = tuple(number[:-1])
        if parent_prefix:
            if len(stack) < level - 1:
                raise RuntimeError(
                    f"Section {'.'.join(number)} {title!r}: "
                    f"no parent at level {level - 1}"
                )
            expected_parent = tuple(stack[level - 2].number.split("."))
            if expected_parent != parent_prefix:
                raise RuntimeError(
                    f"Section {'.'.join(number)} {title!r}: "
                    f"parent prefix {list(parent_prefix)} != current parent "
                    f"{list(expected_parent)}"
                )
        current = number[-1]
        same_parent = state.last_parent.get(level) == parent_prefix
        if not same_parent:
            if current.isdigit() and int(current) not in (0, 1):
                raise RuntimeError(
                    f"First section at level {level} under "
                    f"{'.'.join(map(str, parent_prefix)) or '<root>'} must "
                    f"start at 0 or 1, got {current} ({title!r})"
                )
        else:
            previous = state.last_idx[level]
            if current.isdigit() and previous.isdigit():
                expected = str(int(previous) + 1)
            else:
                # Annex letters are identifiers, not a promise that every
                # intervening annex exists. Duplicate identifiers still fail.
                expected = None
            if expected is not None and current != expected:
                raise RuntimeError(
                    f"Non-contiguous numbering at level {level}: expected "
                    f"{expected}, got {current} ({title!r})"
                )
            if expected is None and current == previous:
                raise RuntimeError(
                    f"Duplicate section number at level {level}: {current} "
                    f"({title!r})"
                )
