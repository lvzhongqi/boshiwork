"""PDF → Markdown.

A PDF has no document structure — only glyphs at coordinates — so everything a
section tree needs is reconstructed here from three signals: pdfminer's layout
analysis groups glyphs into lines and paragraphs, the font tells a heading from
body text, and the clause number tells a heading from a numbered list item.
The last one does the real work: emphasis alone promotes every bold list item,
so a candidate is a heading only if its number also continues the section tree
(``parsing.headings``).

Three kinds of non-content are removed first, because each of them otherwise
reappears in the middle of a section: the running header and footer that repeat
on every page, the table-of-contents lines with their dot leaders, and text
rotated out of the reading direction (the vertical notice down the margin of a
NIST publication, for one).

The result is Markdown, and the Markdown pipeline takes it from there.
"""
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from orrery.modules.document.parsing.headings import (
    HeadingSequence,
    escape_body_line,
    split_numbered,
)

logger = logging.getLogger(__name__)

#: A line is in the header/footer band when it sits in the outer tenth of the
#: page. Running heads live there; body text does not.
_MARGIN_BAND = 0.10
#: Share of pages a line has to repeat on before it counts as a running head.
_RUNNING_SHARE = 0.25
_MIN_PAGES_FOR_RUNNING = 4
#: Dot leaders — the table of contents and nothing else.
_DOT_LEADER = re.compile(r"(?:\.\s?){4,}")
#: Two text lines this close vertically sat on one printed baseline. As a
#: share of page height, about two points on a letter page.
_BASELINE_EPSILON = 0.0025
#: A page this many leader lines deep, and this much of it, is a contents page.
_MIN_TOC_LEADERS = 3
_TOC_SHARE = 0.2
#: Font size above the body size that marks a heading on its own.
_HEADING_SIZE_MARGIN = 0.5
#: Share of a line's characters that must be bold for it to read as emphasized.
_BOLD_SHARE = 0.6
_DIGITS = re.compile(r"\d+")
#: A heading whose title is on the next line — the ISO term-definition layout
#: (``3.1`` / ``asymmetric cryptographic technique``) and the annex opener
#: (``Annex A`` / ``(informative)`` / ``Use of text field``).
_NUMBER_ONLY = re.compile(r"^(?:\d+(?:\.\d+)*|[A-Z](?:\.\d+)+)\.?$")
_ANNEX_ONLY = re.compile(r"^(?:Annex|Appendix)\s+[A-Z]\.?$", re.IGNORECASE)
_QUALIFIER = re.compile(r"^\((?:in)?formative\)$|^\(normative\)$", re.IGNORECASE)


@dataclass
class _Line:
    page: int
    block: int
    x0: float
    text: str
    size: float
    bold: float
    top_ratio: float


def extract_markdown(source_path: Path) -> str:
    """Render a PDF as Markdown for the Markdown pipeline."""
    source_path = Path(source_path)
    lines = _read_lines(source_path)
    if not lines:
        raise RuntimeError(
            f"{source_path}: no extractable text. A scanned PDF carries page "
            f"images and no text layer; run OCR on it first."
        )
    n_pages = 1 + max(line.page for line in lines)
    kept = _drop_furniture(lines, n_pages)
    if not kept:
        raise RuntimeError(
            f"{source_path}: every line was removed as running header, footer "
            f"or table of contents; nothing is left to parse."
        )
    body_size = _body_size(kept)
    headings, consumed = _detect_headings(kept, body_size, str(source_path))
    logger.info(
        "PDF extractor: %d pages, %d lines (%d dropped as furniture), "
        "body size %.1f, %d headings",
        n_pages, len(kept), len(lines) - len(kept), body_size, len(headings),
    )
    return _render(kept, headings, consumed)


# -- reading ---------------------------------------------------------------


def _read_lines(source_path: Path) -> list[_Line]:
    extract_pages, layout = _pdfminer()
    out: list[_Line] = []
    for page_no, page in enumerate(extract_pages(str(source_path), laparams=layout.LAParams())):
        height = page.height or 1.0
        for block_no, element in enumerate(page):
            if not isinstance(element, layout.LTTextContainer):
                continue
            for line in element:
                if not isinstance(line, layout.LTTextLine):
                    continue
                # Rotated glyphs are margin furniture, never body text, and
                # pdfminer hands them over one character per line.
                chars = [
                    c for c in line
                    if isinstance(c, layout.LTChar) and c.upright
                ]
                text = " ".join(line.get_text().split())
                if not text or not chars:
                    continue
                bold = sum(1 for c in chars if "bold" in c.fontname.lower())
                out.append(_Line(
                    page=page_no,
                    block=block_no,
                    x0=line.x0,
                    text=text,
                    size=round(max(c.size for c in chars), 1),
                    bold=bold / len(chars),
                    top_ratio=(height - line.y1) / height,
                ))
    return _merge_baselines(out)


def _merge_baselines(lines: list[_Line]) -> list[_Line]:
    """Put fragments of one printed line back together, left to right.

    A heading set as ``2`` in one column and its title in another reaches
    pdfminer as two text lines on one baseline, and not always in reading
    order — NIST publications hand over the title first. Merging inside a
    single text box keeps a two-column page apart, because layout analysis
    already put its columns in different boxes.
    """
    out: list[_Line] = []
    group: list[_Line] = []

    def flush() -> None:
        if not group:
            return
        ordered = sorted(group, key=lambda l: l.x0)
        head = ordered[0]
        chars = sum(len(l.text) for l in ordered) or 1
        out.append(_Line(
            page=head.page,
            block=head.block,
            x0=head.x0,
            text=" ".join(l.text for l in ordered),
            size=max(l.size for l in ordered),
            bold=sum(l.bold * len(l.text) for l in ordered) / chars,
            top_ratio=head.top_ratio,
        ))
        group.clear()

    for line in lines:
        if group and (
            line.page == group[0].page
            and line.block == group[0].block
            and abs(line.top_ratio - group[0].top_ratio) <= _BASELINE_EPSILON
        ):
            group.append(line)
            continue
        flush()
        group.append(line)
    flush()
    return out


def _pdfminer():
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer import layout
    except ImportError as exc:  # pragma: no cover - install-time failure
        raise RuntimeError(
            "Reading a PDF needs pdfminer.six, which this package does not "
            "install: PDF is an optional input, and the dependency list stays "
            "the closure the reported experiments ran against. Install it with "
            "`pip install pdfminer.six` and run again."
        ) from exc
    return extract_pages, layout


# -- furniture -------------------------------------------------------------


def _drop_furniture(lines: list[_Line], n_pages: int) -> list[_Line]:
    running = _running_texts(lines, n_pages)
    toc_blocks, toc_pages = _contents(lines)
    kept: list[_Line] = []
    for line in lines:
        if line.page in toc_pages or (line.page, line.block) in toc_blocks:
            continue
        if (
            _in_margin(line)
            and not _NUMBER_ONLY.match(line.text)
            and _normalize(line.text) in running
        ):
            continue
        kept.append(line)
    return kept


def _contents(lines: list[_Line]) -> tuple[set[tuple[int, int]], set[int]]:
    """``(contents blocks, contents pages)``.

    A contents entry that wraps puts its leader on the last line only, so the
    whole block goes — otherwise its first line survives as body text, and a
    line reading "Appendix B: ..." becomes a second Appendix B. And when the
    layout sets the clause numbers in their own column, that column has no
    leaders at all, so a page that is mostly leaders takes its whole page with
    it.
    """
    per_page: dict[int, int] = defaultdict(int)
    total: dict[int, int] = defaultdict(int)
    blocks: set[tuple[int, int]] = set()
    for line in lines:
        total[line.page] += 1
        if _DOT_LEADER.search(line.text):
            per_page[line.page] += 1
            blocks.add((line.page, line.block))
    pages = {
        page for page, leaders in per_page.items()
        if leaders >= _MIN_TOC_LEADERS and leaders >= _TOC_SHARE * total[page]
    }
    return blocks, pages


def _running_texts(lines: list[_Line], n_pages: int) -> set[str]:
    """Header/footer texts that repeat across pages, page numbers normalized."""
    if n_pages < _MIN_PAGES_FOR_RUNNING:
        return set()
    pages_by_text: dict[str, set[int]] = defaultdict(set)
    for line in lines:
        # A lone number in the margin is as often a clause number at the top of
        # its page as a page number, and normalizing digits makes the two
        # identical. Leave them here; a page number that survives is dropped by
        # the Markdown cleaner, and a clause number is picked up as a heading.
        if _in_margin(line) and not _NUMBER_ONLY.match(line.text):
            pages_by_text[_normalize(line.text)].add(line.page)
    threshold = max(3, int(_RUNNING_SHARE * n_pages))
    return {text for text, pages in pages_by_text.items() if len(pages) >= threshold}


def _in_margin(line: _Line) -> bool:
    return line.top_ratio < _MARGIN_BAND or line.top_ratio > 1.0 - _MARGIN_BAND


def _normalize(text: str) -> str:
    return _DIGITS.sub("#", text).strip().lower()


# -- headings --------------------------------------------------------------


def _body_size(lines: list[_Line]) -> float:
    counts: Counter[float] = Counter()
    for line in lines:
        counts[line.size] += len(line.text)
    return counts.most_common(1)[0][0]


def _detect_headings(
    lines: list[_Line], body_size: float, what: str
) -> tuple[dict[int, str], set[int]]:
    """``(line index → heading line, indices swallowed by a heading)``.

    Emphasis is required on the first pass, because a numbered line that is
    neither bold nor larger is nearly always a list item. A document that sets
    its headings in the body face has none accepted that way, so the pass is
    repeated without the requirement rather than losing every section.
    """
    found, consumed = _scan(
        lines, body_size, require_emphasis=True, what=what, strict=False
    )
    if found:
        return found, consumed
    logger.warning(
        "%s: no emphasized numbered line found; falling back to clause "
        "numbering alone, which can promote a numbered list item.", what,
    )
    return _scan(lines, body_size, require_emphasis=False, what=what, strict=True)


def _scan(
    lines: list[_Line],
    body_size: float,
    *,
    require_emphasis: bool,
    what: str,
    strict: bool,
) -> tuple[dict[int, str], set[int]]:
    sequence = HeadingSequence()
    found: dict[int, str] = {}
    consumed: set[int] = set()
    i = 0
    while i < len(lines):
        candidate = _candidate(lines, i)
        if candidate is None:
            i += 1
            continue
        number, text, last = candidate
        # The line carrying the number is the one that has to look like a
        # heading. Checking the title line instead would let any bold line
        # promote the sentence that happens to end above it.
        if require_emphasis and not _emphasized(lines[i], body_size):
            i += 1
            continue
        if not sequence.accept(number, text):
            i += 1
            continue
        found[i] = text
        consumed.update(range(i + 1, last + 1))
        i = last + 1
    if strict:
        sequence.report(what)
    return found, consumed


def _candidate(lines: list[_Line], i: int) -> tuple[str, str, int] | None:
    """``(number, heading line, last line index)`` for a heading starting at i.

    One line usually carries the whole heading. When it carries only the
    number, the title is on the next line — with an ``(informative)`` qualifier
    possibly in between — and the two are put back together here so the rest of
    the pipeline sees one heading.
    """
    text = lines[i].text
    parsed = split_numbered(text)
    if parsed is not None:
        return parsed[0], text, i
    if not (_NUMBER_ONLY.match(text) or _ANNEX_ONLY.match(text)):
        return None
    j = i + 1
    while j < len(lines) and _QUALIFIER.match(lines[j].text):
        j += 1
    if j >= len(lines) or lines[j].page != lines[i].page:
        return None
    title = lines[j].text
    if _NUMBER_ONLY.match(title) or _ANNEX_ONLY.match(title):
        return None
    # A line that is already a whole heading is the next heading, not this
    # one's title: "...defined in Appendix A." sits right above "2 Encryption",
    # and joining them would bury clause 2 inside an annex.
    if split_numbered(title) is not None:
        return None
    merged = re.sub(r"\.$", "", text) + " " + title
    parsed = split_numbered(merged)
    if parsed is None:
        return None
    return parsed[0], merged, j


def _emphasized(line: _Line, body_size: float) -> bool:
    return line.bold >= _BOLD_SHARE or line.size >= body_size + _HEADING_SIZE_MARGIN


# -- rendering -------------------------------------------------------------


def _render(
    lines: list[_Line], headings: dict[int, str], consumed: set[int]
) -> str:
    out: list[str] = []
    paragraph: list[str] = []
    block: tuple[int, int] | None = None

    def flush() -> None:
        if paragraph:
            out.extend(["", escape_body_line(_join(paragraph)), ""])
            paragraph.clear()

    for i, line in enumerate(lines):
        if i in consumed:
            continue
        heading = headings.get(i)
        if heading is not None:
            flush()
            number, _title = split_numbered(heading)
            out.extend(["", "#" * (number.count(".") + 2) + " " + heading, ""])
            block = None
            continue
        here = (line.page, line.block)
        if block is not None and here != block:
            flush()
        block = here
        paragraph.append(line.text)
    flush()
    return "\n".join(out)


def _join(parts: list[str]) -> str:
    """Undo the hard wrapping, re-joining words split across a line break."""
    text = ""
    for part in parts:
        if not text:
            text = part
        elif text.endswith("-") and part[:1].islower():
            text = text[:-1] + part
        else:
            text = f"{text} {part}"
    return text


__all__ = ["extract_markdown"]
