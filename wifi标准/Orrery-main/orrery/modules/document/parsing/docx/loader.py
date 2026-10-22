"""DocxLoader: ``.docx`` → Markdown → SectionTree."""
from __future__ import annotations

from pathlib import Path

from orrery.modules.document.model.section_tree import SectionTree
from orrery.modules.document.parsing.base import DocumentLoader
from orrery.modules.document.parsing.docx.extractor import extract_markdown
from orrery.modules.document.parsing.markdown import MarkdownLoader


class DocxLoader(DocumentLoader):
    """Office Open XML loader.

    Word heading styles carry the outline, so the levels are read rather than
    guessed; the clause numbers come from the heading text, which is how the
    3GPP and ISO templates write them.
    """

    protocol_format = "docx"

    def __init__(self) -> None:
        self._markdown = MarkdownLoader()

    async def load(self, source_path: Path) -> SectionTree:
        if not source_path.exists():
            raise RuntimeError(f"DOCX source not found: {source_path}")
        return self._markdown.parse_text(extract_markdown(source_path))
