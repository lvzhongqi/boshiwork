"""Which numbered lines are section headings — for sources with no markup.

A PDF page and a legacy ``.doc`` paragraph both arrive as flat text: nothing in
them says "this line is a heading", only that it starts with something shaped
like ``5.2.1``. Numbered list items look identical, and one of them promoted by
mistake breaks the numbering of every real section after it, so the test here
is *continuity*: a candidate is a heading only when its number is a legal
successor of the last one accepted — the next sibling, a first child, or an
ancestor's next sibling.

The successor rule mirrors ``MarkdownNormalizer._assign_numbers`` exactly, so
whatever this accepts, the normalizer accepts too. Loaders that get real
structure from the source (Markdown headings, Word heading styles) do not need
this — they know.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

#: ``5``, ``5.2.1``, ``B.1.3`` followed by whitespace and a title. A lone
#: capital is not a clause number: ``U to party V`` and ``C O M P U T E R`` are
#: both real lines from real specifications. An annex reaches level 1 through
#: ANNEX_LINE, which needs the word.
NUMBERED_LINE = re.compile(
    r"^(?P<number>\d+(?:\.\d+)*|[A-Z](?:\.\d+)+)\.?[ \t]+(?P<title>\S.*)$"
)
#: ``Annex A``, ``Appendix B:``, ``Annex C (normative)`` — named, not numbered.
#: A title has to follow: a bare ``Annex A`` is a heading whose title is on the
#: next line, and the caller has to put the two together first.
ANNEX_LINE = re.compile(
    r"^(?:Annex|Appendix)\s+(?P<number>[A-Z])(?:\s|:|\.|—|-)\s*\S",
    re.IGNORECASE,
)

#: A heading is a label, not a sentence. Anything longer is body text that
#: happens to open with a number.
MAX_HEADING_CHARS = 150

#: What the normalizer would read as a heading in a line we mean as body text.
#: ``Appendix B: Rationale ...`` mid-sentence is a cross-reference, and ``#E``
#: is a symbol out of an ISO symbol table — both start at column 0, which is
#: what the normalizer looks at, so both have to be pushed off it.
_BARE_ANNEX = re.compile(
    r"^(?:Annex|Appendix)\s+[A-Z](?::|\.(?=\s)|\s*[-—])", re.IGNORECASE
)


def split_numbered(line: str) -> tuple[str, str] | None:
    """``("5.2", "Key derivation")`` for a numbered line, else None.

    The annex form is tried first: ``Annex A (normative)`` is recognized by its
    name, and its number is the letter.
    """
    text = line.strip()
    if not text or len(text) > MAX_HEADING_CHARS:
        return None
    m_annex = ANNEX_LINE.match(text)
    if m_annex:
        return m_annex.group("number").upper(), text
    m = NUMBERED_LINE.match(text)
    if not m:
        return None
    return m.group("number"), m.group("title").strip()


class HeadingSequence:
    """Accepts a numbered candidate only when it continues the section tree."""

    def __init__(self) -> None:
        self._last: list[str] | None = None
        self._rejected = 0
        self._accepted = 0

    @property
    def accepted(self) -> int:
        return self._accepted

    @property
    def rejected(self) -> int:
        return self._rejected

    def level_of(self, number: str) -> int:
        return number.count(".") + 1

    def accept(self, number: str, line: str) -> bool:
        """Whether ``number`` continues the sequence; records it if it does."""
        parts = number.split(".")
        if self._continues(parts):
            self._last = parts
            self._accepted += 1
            return True
        self._rejected += 1
        logger.info(
            "Numbered line %r does not continue section %s; kept as body text",
            line[:80],
            ".".join(self._last) if self._last else "<start>",
        )
        return False

    def _continues(self, cand: list[str]) -> bool:
        """The rule, in one place: sibling, first child, or ancestor's sibling.

        Annexes are their own namespace — lettered, opened at A after the last
        numbered clause, and never followed by a numbered one — but inside an
        annex the sub-numbers are an ordinary counter, because that is how both
        the normalizer and the section parser read them.
        """
        alpha = not cand[0].isdigit()
        if not all(part.isdigit() for part in cand[1:]):
            return False
        if alpha and len(cand[0]) != 1:
            return False

        last = self._last
        if last is None:
            return len(cand) == 1 and (
                cand[0] == "A" if alpha else cand[0] in ("0", "1")
            )
        if alpha != (not last[0].isdigit()):
            return alpha and len(cand) == 1 and cand[0] == "A"
        if alpha:
            if cand[0] != last[0]:
                # A further annex: letters run forwards and may skip.
                return len(cand) == 1 and cand[0] > last[0]
            if len(cand) == 1:
                return False

        if len(cand) == len(last) + 1:
            return cand[:-1] == last and cand[-1] in ("0", "1")
        if len(cand) > len(last):
            return False
        k = len(cand) - 1
        if k == 0:
            return cand[0] == str(int(last[0]) + 1)
        return cand[:k] == last[:k] and cand[k] == str(int(last[k]) + 1)

    def report(self, what: str) -> None:
        """Log the tally, and fail loudly when nothing at all was accepted."""
        if self._accepted == 0 and self._rejected >= 3:
            raise RuntimeError(
                f"{what}: {self._rejected} lines look like numbered headings "
                f"but none continues a section tree starting at 1 — the "
                f"document's clause numbering could not be recovered."
            )
        logger.info(
            "%s: %d numbered headings accepted, %d numbered lines kept as body",
            what, self._accepted, self._rejected,
        )


def escape_body_line(text: str) -> str:
    """A body line the Markdown pipeline will not mistake for markup.

    The loaders that call this decide what a heading is themselves, so every
    other line has to be inert: a leading ``#`` or code fence is escaped, and a
    line shaped like an annex opener is moved off column 0, where the
    normalizer stops treating it as one.
    """
    if text.startswith("#") or text.startswith("```"):
        return "\\" + text
    if _BARE_ANNEX.match(text):
        return " " + text
    return text


def mark_numbered_headings(lines: list[str], what: str) -> list[str]:
    """Prefix every line that continues the section tree with its ``#``s.

    For sources that arrive as flat text. A line is a candidate only when it
    opens with a clause number and is short enough to be a label; the sequence
    decides the rest. Non-headings are returned untouched, so a numbered list
    item stays body text.
    """
    seq = HeadingSequence()
    out: list[str] = []
    for line in lines:
        parsed = split_numbered(line)
        if parsed is None:
            out.append(escape_body_line(line))
            continue
        number, _title = parsed
        if not seq.accept(number, line):
            out.append(escape_body_line(line))
            continue
        out.append("#" * (seq.level_of(number) + 1) + " " + line.strip())
    seq.report(what)
    return out


__all__ = [
    "ANNEX_LINE",
    "HeadingSequence",
    "MAX_HEADING_CHARS",
    "escape_body_line",
    "mark_numbered_headings",
    "NUMBERED_LINE",
    "split_numbered",
]
