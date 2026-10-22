"""Cosmetic Markdown cleanup that runs before structural parsing.

Removes the noise a ``pdf → markdown`` conversion leaves behind: page-number
lines, ``<span id>`` anchors, asterisk-wrapped heading titles, and internal
page-anchor links. Heading numbering is the normalizer's job.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


# A line matching any of these is a page number and is dropped whole.
_PAGE_PATTERNS = [
    (re.compile(r'^\s*\d+\s*$'), 'pure digits'),
    (re.compile(r'^\s*[-–—]\s*\d+\s*[-–—]\s*$'), 'dash-wrapped, e.g. - 12 -'),
    (re.compile(r'^\s*第\s*\d+\s*页\s*$'), 'Chinese page, e.g. 第 12 页'),
    (re.compile(r'^\s*Page\s+\d+(\s*/\s*\d+)?\s*$', re.I), 'English page, e.g. Page 12'),
    (re.compile(r'^\s*\d+\s*/\s*\d+\s*$'), 'fraction form, e.g. 12/34'),
]

_SPAN_PATTERN = re.compile(r'<span\s+id="[^"]*"\s*>\s*</span>')
_HEADING_DOUBLE_STAR = re.compile(r'^(\s*#{1,10}\s+)\*\*(.+?)\*\*(\s*)$')
_HEADING_SINGLE_STAR = re.compile(r'^(\s*#{1,10}\s+)\*(.+?)\*(\s*)$')
_PAGE_LINK_PATTERN = re.compile(r'\[([^\]]+)\]\(#page-[^)]*\)')


class MarkdownCleaner:
    """Strip cosmetic noise from Markdown before structural parsing."""

    def clean(self, content: str) -> str:
        lines = content.split('\n')
        cleaned: list[str] = []
        stats = {
            'page_numbers': 0,
            'spans': 0,
            'double_star_headings': 0,
            'single_star_headings': 0,
            'page_links': 0,
        }

        for lineno, original in enumerate(lines, start=1):
            line = original

            if self._is_page_number(line, lineno, stats):
                continue

            line = self._strip_spans(line, lineno, stats)
            # The heading-emphasis patterns anchor on the whole line, so a
            # wrapping page link has to be unwrapped before them.
            line = self._strip_page_links(line, lineno, stats)
            line = self._strip_heading_emphasis(line, lineno, stats)

            cleaned.append(line)

        logger.info(
            "MarkdownCleaner: pages=%d spans=%d **headings=%d *headings=%d "
            "page_links=%d",
            stats['page_numbers'],
            stats['spans'],
            stats['double_star_headings'],
            stats['single_star_headings'],
            stats['page_links'],
        )
        return '\n'.join(cleaned)

    @staticmethod
    def _is_page_number(line: str, lineno: int, stats: dict) -> bool:
        for pattern, desc in _PAGE_PATTERNS:
            if pattern.match(line):
                logger.info(
                    "Line %d | page number (%s) | drop | %r",
                    lineno, desc, line,
                )
                stats['page_numbers'] += 1
                return True
        return False

    @staticmethod
    def _strip_spans(line: str, lineno: int, stats: dict) -> str:
        matches = _SPAN_PATTERN.findall(line)
        if not matches:
            return line
        new_line = _SPAN_PATTERN.sub('', line)
        logger.info(
            "Line %d | %d span anchor(s) removed | %r → %r",
            lineno, len(matches), line, new_line,
        )
        stats['spans'] += len(matches)
        return new_line

    @staticmethod
    def _strip_page_links(line: str, lineno: int, stats: dict) -> str:
        matches = _PAGE_LINK_PATTERN.findall(line)
        if not matches:
            return line
        new_line = _PAGE_LINK_PATTERN.sub(r'\1', line)
        logger.info(
            "Line %d | %d internal page link(s) unwrapped | %r → %r",
            lineno, len(matches), line, new_line,
        )
        stats['page_links'] += len(matches)
        return new_line

    @staticmethod
    def _strip_heading_emphasis(line: str, lineno: int, stats: dict) -> str:
        # The longer token goes first; the single-star pattern would otherwise
        # eat one star off a ``**...**`` title.
        m = _HEADING_DOUBLE_STAR.match(line)
        if m:
            new_line = f"{m.group(1)}{m.group(2)}{m.group(3)}"
            logger.info(
                "Line %d | '**' heading emphasis stripped | %r → %r",
                lineno, line, new_line,
            )
            stats['double_star_headings'] += 1
            return new_line

        m = _HEADING_SINGLE_STAR.match(line)
        if m:
            new_line = f"{m.group(1)}{m.group(2)}{m.group(3)}"
            logger.info(
                "Line %d | '*' heading emphasis stripped | %r → %r",
                lineno, line, new_line,
            )
            stats['single_star_headings'] += 1
            return new_line

        return line
