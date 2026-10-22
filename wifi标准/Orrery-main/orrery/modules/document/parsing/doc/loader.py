"""DocLoader: legacy ``.doc`` → text → heading markup → SectionTree."""
from __future__ import annotations

from pathlib import Path

from orrery.modules.document.model.section_tree import SectionTree
from orrery.modules.document.parsing.base import DocumentLoader
from orrery.modules.document.parsing.doc.extractor import extract_text
from orrery.modules.document.parsing.headings import mark_numbered_headings
from orrery.modules.document.parsing.markdown import MarkdownLoader


class DocLoader(DocumentLoader):
    """Pre-2007 Word binary loader.

    The binary format hides paragraph styles in a property stream this reader
    does not open, so structure comes from clause numbers alone: a numbered
    line that continues the section tree becomes a heading, everything else
    stays body text. A ``.doc`` whose clauses are not numbered therefore has no
    sections — save such a document as ``.docx``, where the heading styles are
    readable.
    """

    protocol_format = "doc"

    def __init__(self) -> None:
        self._markdown = MarkdownLoader()

    async def load(self, source_path: Path) -> SectionTree:
        if not source_path.exists():
            raise RuntimeError(f"DOC source not found: {source_path}")
        text = extract_text(source_path)
        lines = mark_numbered_headings(text.split("\n"), str(source_path))
        return self._markdown.parse_text("\n".join(lines))
