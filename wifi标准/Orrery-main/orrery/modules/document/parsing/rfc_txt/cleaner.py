"""RFC plain-text cleaner, run before the parser.

Strips a UTF-8 BOM, removes the per-page headers and footers that form-feed
paginated v2 RFCs carry (v3 text has no form feeds and passes through), then
discards everything before the first column-0 numbered heading — abstract,
status, copyright and table of contents. Section structure is the parser's job.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Column-0 headings: ``1.  Title``, ``Appendix A.  Title``, ``A.1.  Title``. The
# trailing period is optional here and in the parser: RFC 2617 writes headings as
# ``2 Basic Authentication Scheme``, and requiring one loses the whole body.
_HEADING_NUMERIC = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+\S.*$")
_HEADING_APPENDIX = re.compile(r"^Appendix\s+([A-Z])\.?\s+\S.*$")
_HEADING_SUBAPPENDIX = re.compile(r"^([A-Z]\.\d+(?:\.\d+)*)\.?\s+\S.*$")

# Per-page footer, e.g. ``Iyengar & Thomson  Standards Track  [Page 14]``.
_FOOTER = re.compile(r"\[Page\s+\d+\]\s*$")
# Per-page header, e.g. ``RFC 4253  SSH Transport Layer Protocol  January 2006``
# or, for I-Ds, ``Internet-Draft  TLS 1.3  October 2017``.
_HEADER = re.compile(r"^(?:RFC\s+\d+|Internet-Draft)\b.*\b\d{4}\s*$")


class RFCTxtCleaner:
    def clean(self, text: str) -> str:
        text = text.lstrip("﻿")
        if "\f" in text:
            logger.warning(
                "RFC text contains form-feed page breaks — treating as v2 layout "
                "(stripping per-page headers/footers)."
            )
            text = self._strip_pages(text)
        text = self._strip_frontmatter_and_toc(text)
        return text

    @staticmethod
    def _strip_pages(text: str) -> str:
        """Split on form-feeds; drop the footer from every page and the header
        from every page after the first."""
        pages = text.split("\f")
        out: list[str] = []
        for i, page in enumerate(pages):
            lines = page.split("\n")
            while lines and not lines[-1].strip():
                lines.pop()
            if lines and _FOOTER.search(lines[-1]):
                lines.pop()
            # Page 1 opens with the document title block, not a page header.
            if i > 0:
                while lines and not lines[0].strip():
                    lines.pop(0)
                if lines and _HEADER.match(lines[0]):
                    lines.pop(0)
            out.append("\n".join(lines))
        return "\n".join(out)

    @staticmethod
    def _strip_frontmatter_and_toc(text: str) -> str:
        """Drop everything before the first column-0 numbered heading, raising
        RuntimeError if there is none. Table-of-contents entries are indented,
        so a column-0 match skips them and lands on the real heading.
        """
        lines = text.split("\n")
        for idx, line in enumerate(lines):
            if _HEADING_NUMERIC.match(line):
                return "\n".join(lines[idx:])
        raise RuntimeError(
            "RFC cleaner: no numbered top-level heading (e.g. '1.  Title') "
            "found at column 0; cannot locate document body."
        )


__all__ = [
    "RFCTxtCleaner",
    "_HEADING_NUMERIC",
    "_HEADING_APPENDIX",
    "_HEADING_SUBAPPENDIX",
]
