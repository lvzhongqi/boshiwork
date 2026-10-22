"""PDFLoader: PDF → Markdown → SectionTree."""
from __future__ import annotations

from pathlib import Path

from orrery.modules.document.model.section_tree import SectionTree
from orrery.modules.document.parsing.base import DocumentLoader
from orrery.modules.document.parsing.markdown import MarkdownLoader
from orrery.modules.document.parsing.pdf.extractor import extract_markdown


class PDFLoader(DocumentLoader):
    """Text-layer PDF loader.

    Structure is reconstructed from font emphasis and clause numbering, so a
    specification with numbered clauses reads well and a scanned page image
    does not read at all — the latter fails with a message saying so rather
    than producing an empty document.
    """

    protocol_format = "pdf"

    def __init__(self) -> None:
        self._markdown = MarkdownLoader()

    async def load(self, source_path: Path) -> SectionTree:
        if not source_path.exists():
            raise RuntimeError(f"PDF source not found: {source_path}")
        return self._markdown.parse_text(extract_markdown(source_path))
