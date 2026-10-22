"""Heading-numbering normalizer for Markdown.

Rewrites headings into the shape the parser demands: one unnumbered ``#``
title, then ``##``/``###``/``####`` as levels 1/2/3 with a matching ``1``,
``1.2``, ``1.2.3`` prefix, filling in whatever the document left out. Decimal
siblings must run consecutively from 0 or 1; annex identifiers (``Annex C``,
``C.2.2``) are kept verbatim and may skip letters. Bare numbered lines count as
headings only in a document with no ``#``-prefixed numbered heading at all.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


class MarkdownNormalizationError(ValueError):
    """Raised when the markdown cannot be normalized automatically."""


_SECTION_NUMBER = r'(?:\d+(?:\.\d+)*|[A-Z](?:\.\d+)+)'
#: Same, plus a bare appendix letter (``## B Diffie-Hellman Groups``). Limited
#: to ``#``-prefixed headings, since on a plain line ``A short note …`` would
#: read as appendix A. Without it ``## B`` is stripped as unnumbered and its
#: ``## B.1`` child is left with no parent.
_HASH_SECTION_NUMBER = r'(?:\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)'
_NUMBER_ONLY_RE = re.compile(
    rf'^\s*(?P<number>{_SECTION_NUMBER})\.?\s+(?P<title>.+?)\s*$'
)
_ANNEX_RE = re.compile(
    r'^(?P<prefix>(?:Annex|Appendix)\s+)(?P<number>[A-Z])'
    r'(?P<title>(?:\s|:|—|-|\.).*)$',
    re.IGNORECASE,
)
#: The same heading with no ``#``, which is how RFC-derived Markdown usually
#: carries appendix titles (``Appendix D: Fragment Handling Rationale``). Two
#: conditions keep prose out: the line starts at column 0, and the letter is
#: followed by a separator, so ``Appendix C was expanded and clarified.`` does
#: not match. Without it the title is dropped and ``## D.1`` loses its parent.
_BARE_ANNEX_RE = re.compile(
    r'^(?:Annex|Appendix)\s+(?P<number>[A-Z])(?::|\.(?=\s)|\s*[-—])\s*'
    r'(?P<title>\S.*)$',
    re.IGNORECASE,
)
_LIST_OR_QUOTE_RE = re.compile(r'^\s*(?:[-*+]\s|>\s)')
_NUMBERED_HEADING_RE = re.compile(
    rf'^\s*(?:#{{1,10}}\s+)?(?:{_SECTION_NUMBER})\.?\s+\S'
    r'|^\s*(?:#{1,10}\s+)?Annex\s+[A-Z](?:\s|:|—|-)',
    re.IGNORECASE,
)
_HASH_NUMBERED_RE = re.compile(
    rf'^\s*#{{1,10}}\s+(?:{_SECTION_NUMBER})\.?\s+\S'
    r'|^\s*#{1,10}\s+Annex\s+[A-Z](?:\s|:|—|-)',
    re.IGNORECASE,
)
_BARE_NUMBERED_RE = re.compile(
    rf'^\s*(?:{_SECTION_NUMBER})\.?\s+\S'
    r'|^\s*Annex\s+[A-Z](?:\s|:|—|-)',
    re.IGNORECASE,
)


class MarkdownNormalizer:
    """Regularize heading levels and numbering in Markdown text."""

    def normalize(self, text: str) -> str:
        lines = text.splitlines()
        uses_numbering = self._document_uses_numbering(lines)
        if uses_numbering:
            bare_numbers_are_headings = self._bare_numbers_are_headings(lines)
            if bare_numbers_are_headings:
                logger.warning(
                    "Document uses explicit numbering (no `#` prefixes on "
                    "numbered sections); bare numbered lines will be treated "
                    "as sections"
                )
            else:
                logger.warning(
                    "Document uses explicit numbering with `#` prefixes; "
                    "bare numbered lines will be treated as plain text and "
                    "stray `#` lines without numbers will be stripped"
                )
            demote_single_hash = self._has_numbered_single_hash(lines)
        else:
            bare_numbers_are_headings = True
            demote_single_hash = self._should_demote_single_hash(lines)

        parsed = self._parse_lines(
            lines,
            demote_single_hash,
            uses_numbering,
            bare_numbers_are_headings,
        )
        self._validate_levels(parsed)
        self._assign_numbers(parsed)
        return self._render(parsed)

    @staticmethod
    def _document_uses_numbering(lines: list[str]) -> bool:
        in_code = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('```') or stripped.startswith('~~~'):
                in_code = not in_code
                continue
            if in_code:
                continue
            if _LIST_OR_QUOTE_RE.match(line):
                continue
            if _NUMBERED_HEADING_RE.match(line):
                return True
        return False

    @staticmethod
    def _has_numbered_single_hash(lines: list[str]) -> bool:
        """A single ``# 1. Foo`` line makes every ``#`` line a level-1 section."""
        in_code = False
        pattern = re.compile(
            rf'^#\s+(?:{_SECTION_NUMBER})\.?\s+\S'
            r'|^#\s+Annex\s+[A-Z](?:\s|:|—|-)',
            re.IGNORECASE,
        )
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('```') or stripped.startswith('~~~'):
                in_code = not in_code
                continue
            if in_code:
                continue
            if _LIST_OR_QUOTE_RE.match(line):
                continue
            if pattern.match(stripped):
                logger.warning(
                    "Found numbered single-`#` line (%r); treating all `#` "
                    "lines as level-1 sections (no document title)",
                    line,
                )
                return True
        return False

    @staticmethod
    def _bare_numbers_are_headings(lines: list[str]) -> bool:
        hash_numbered = 0
        bare_numbered = 0
        in_code = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('```') or stripped.startswith('~~~'):
                in_code = not in_code
                continue
            if in_code:
                continue
            if _LIST_OR_QUOTE_RE.match(line):
                continue
            if _HASH_NUMBERED_RE.match(line):
                hash_numbered += 1
            elif _BARE_NUMBERED_RE.match(line):
                bare_numbered += 1
        return hash_numbered == 0 and bare_numbered > 0

    @staticmethod
    def _should_demote_single_hash(lines: list[str]) -> bool:
        single_hash_count = 0
        in_code = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('```') or stripped.startswith('~~~'):
                in_code = not in_code
                continue
            if in_code:
                continue
            m = re.match(r'^(#{1,10})\s+\S', stripped)
            if m and len(m.group(1)) == 1:
                single_hash_count += 1
                if single_hash_count >= 2:
                    break
        if single_hash_count >= 2:
            logger.warning(
                "No document title found: %d `#` lines treated as level-1 sections",
                single_hash_count,
            )
            return True
        return False

    def _parse_lines(
        self,
        lines: list[str],
        demote_single_hash: bool,
        uses_numbering: bool,
        bare_numbers_are_headings: bool,
    ) -> list[dict]:
        result: list[dict] = []
        in_code = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('```') or stripped.startswith('~~~'):
                in_code = not in_code
                result.append({'index': i, 'kind': 'other', 'raw': line})
                continue
            if in_code:
                result.append({'index': i, 'kind': 'other', 'raw': line})
                continue
            result.append(
                self._classify_line(
                    line,
                    i,
                    demote_single_hash,
                    uses_numbering,
                    bare_numbers_are_headings,
                )
            )
        return result

    @staticmethod
    def _classify_line(
        line: str,
        index: int,
        demote_single_hash: bool,
        uses_numbering: bool,
        bare_numbers_are_headings: bool,
    ) -> dict:
        stripped = line.strip()
        if not stripped:
            return {'index': index, 'kind': 'other', 'raw': line}
        if _LIST_OR_QUOTE_RE.match(line):
            return {'index': index, 'kind': 'other', 'raw': line}

        # Case A: leading `#`s. When the two disagree the number sets the
        # level, not the hash depth.
        hash_match = re.match(r'^(#{1,10})\s*(.*)$', stripped)
        if hash_match:
            hashes = hash_match.group(1)
            rest = hash_match.group(2).strip()
            hash_level = len(hashes)
            if hash_level == 1 and demote_single_hash:
                hash_level = 2

            annex_match = _ANNEX_RE.match(rest)
            if annex_match:
                number = annex_match.group('number').upper()
                title = rest
                return {
                    'index': index,
                    'kind': 'heading',
                    'level': 1,
                    'title': title,
                    'orig_number': number,
                    'had_number': True,
                    'had_hash': True,
                    'raw': line,
                }

            num_match = re.match(
                rf'^(?P<number>{_HASH_SECTION_NUMBER})\.?\s+(?P<title>.+?)$',
                rest,
            )
            if num_match:
                number = num_match.group('number')
                title = num_match.group('title').strip()
                level_from_num = number.count('.') + 1
                expected_hash = level_from_num + 1
                if hash_level != expected_hash:
                    logger.warning(
                        "Hash level (%d) disagrees with number level (%d); "
                        "trusting the number | original: %r",
                        hash_level, level_from_num, line,
                    )
                return {
                    'index': index,
                    'kind': 'heading',
                    'level': level_from_num,
                    'title': title,
                    'orig_number': number,
                    'had_number': True,
                    'had_hash': True,
                    'raw': line,
                }

            if uses_numbering:
                if hash_level == 1:
                    return {'index': index, 'kind': 'title', 'title': rest, 'raw': line}
                logger.warning(
                    "Numbered doc; stripping `#` from unnumbered line | %r → %r",
                    line, rest,
                )
                return {'index': index, 'kind': 'other', 'raw': rest}

            if hash_level == 1:
                return {'index': index, 'kind': 'title', 'title': rest, 'raw': line}

            logger.warning(
                "Section has hashes but no number; numbering will be added "
                "based on hash level | %r",
                line,
            )
            return {
                'index': index,
                'kind': 'heading',
                'level': hash_level - 1,
                'title': rest,
                'had_number': False,
                'had_hash': True,
                'raw': line,
            }

        # Case B: no leading hashes. The appendix form is tried first because
        # it is recognized by name rather than by a number.
        if line == stripped:
            annex_match = _BARE_ANNEX_RE.match(stripped)
            if annex_match:
                return {
                    'index': index,
                    'kind': 'heading',
                    'level': 1,
                    'title': stripped,
                    'orig_number': annex_match.group('number').upper(),
                    'had_number': True,
                    'had_hash': False,
                    'raw': line,
                }

        num_match = _NUMBER_ONLY_RE.match(stripped)
        if num_match:
            if not bare_numbers_are_headings:
                return {'index': index, 'kind': 'other', 'raw': line}
            number = num_match.group('number')
            title = num_match.group('title').strip()
            level = number.count('.') + 1
            logger.warning(
                "Section has a number but no hashes; hashes will be added | %r",
                line,
            )
            return {
                'index': index,
                'kind': 'heading',
                'level': level,
                'title': title,
                'orig_number': number,
                'had_number': True,
                'had_hash': False,
                'raw': line,
            }

        return {'index': index, 'kind': 'other', 'raw': line}

    @staticmethod
    def _validate_levels(parsed: list[dict]) -> None:
        titles = [p for p in parsed if p['kind'] == 'title']
        if len(titles) > 1:
            raise MarkdownNormalizationError(
                f"Document contains {len(titles)} top-level titles (`#`); "
                f"exactly one is required: {[t['raw'] for t in titles]}"
            )

        current_level = 0
        for i, item in enumerate(parsed):
            if item['kind'] == 'title':
                current_level = 0
                continue
            if item['kind'] != 'heading':
                continue
            level = item['level']
            if level > current_level + 1:
                raise MarkdownNormalizationError(
                    f"Skipped heading level: jumped from {current_level} to "
                    f"{level} at line {i} | original: {item['raw']!r}"
                )
            current_level = level

    @staticmethod
    def _assign_numbers(parsed: list[dict]) -> None:
        counters: list[int] = []
        start_values: list[int] = []
        to_demote: list[int] = []

        for idx, item in enumerate(parsed):
            if item['kind'] != 'heading':
                if item['kind'] == 'title':
                    counters = []
                    start_values = []
                continue

            level = item['level']
            is_new_group = len(counters) < level
            if is_new_group:
                tentative_counters = counters + [0] * (level - len(counters))
                tentative_start = start_values + [0] * (level - len(start_values))
            else:
                tentative_counters = counters[:level]
                tentative_start = start_values[:level]
                tentative_counters[-1] += 1

            if item.get('had_number'):
                orig = item['orig_number']
                # Appendix namespaces (A, B.1, C.2.2) are stable identifiers
                # and standards routinely omit whole letters, so they are kept
                # verbatim and skip the contiguity check.
                if orig[0].isalpha():
                    item['new_number'] = orig.upper()
                    counters = []
                    start_values = []
                    continue

                orig_parts = [int(p) for p in orig.split('.')]

                if is_new_group:
                    last = orig_parts[-1]
                    if last not in (0, 1):
                        if level == 1 and not item.get('had_hash', False):
                            logger.warning(
                                "Out-of-sequence bare-number line (expected 0 "
                                "or 1, got %s); treating as plain text | %r",
                                orig, item['raw'],
                            )
                            to_demote.append(idx)
                            continue
                        raise MarkdownNormalizationError(
                            f"Section group must start at 0 or 1, got {orig} "
                            f"| {item['raw']!r}"
                        )
                    if last == 0:
                        logger.warning("Section group starts from 0 | %r", item['raw'])
                    tentative_counters[-1] = last
                    tentative_start[-1] = last

                    parent_expected = counters
                    parent_got = orig_parts[:-1]
                    if parent_expected != parent_got:
                        expected_full = '.'.join(
                            str(c) for c in (parent_expected + [last])
                        )
                        raise MarkdownNormalizationError(
                            f"Non-consecutive section number: expected "
                            f"{expected_full}, got {orig} | {item['raw']!r}"
                        )
                    expected_number = orig
                else:
                    expected_number = '.'.join(str(c) for c in tentative_counters)
                    if orig != expected_number:
                        is_bare_level1 = level == 1 and not item.get('had_hash', False)
                        if is_bare_level1:
                            logger.warning(
                                "Out-of-sequence bare-number line (expected %s, "
                                "got %s); treating as plain text | %r",
                                expected_number, orig, item['raw'],
                            )
                            to_demote.append(idx)
                            continue
                        raise MarkdownNormalizationError(
                            f"Non-consecutive section number: expected "
                            f"{expected_number}, got {orig} | {item['raw']!r}"
                        )
            else:
                if is_new_group:
                    tentative_counters[-1] = 1
                    tentative_start[-1] = 1
                expected_number = '.'.join(str(c) for c in tentative_counters)

            counters = tentative_counters
            start_values = tentative_start
            item['new_number'] = expected_number

            if not item.get('had_number') or not item.get('had_hash'):
                hashes = '#' * (level + 1)
                logger.warning(
                    "Fixed section | %r → %r",
                    item['raw'],
                    f"{hashes} {expected_number}  {item['title']}",
                )

        for idx in to_demote:
            parsed[idx] = {
                'index': parsed[idx]['index'],
                'kind': 'other',
                'raw': parsed[idx]['raw'],
            }

    @staticmethod
    def _render(parsed: list[dict]) -> str:
        out: list[str] = []
        for item in parsed:
            if item['kind'] == 'title':
                out.append(f"# {item['title']}")
            elif item['kind'] == 'heading':
                hashes = '#' * (item['level'] + 1)
                out.append(f"{hashes} {item['new_number']}  {item['title']}")
            else:
                out.append(item['raw'])
        return '\n'.join(out)
