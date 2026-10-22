"""MarkdownLoader: top-level orchestrator for the Markdown loader pipeline."""
from __future__ import annotations

from pathlib import Path

from orrery.modules.document.parsing.base import DocumentLoader
from orrery.modules.document.parsing.markdown.cleaner import MarkdownCleaner
from orrery.modules.document.parsing.markdown.normalizer import (
    MarkdownNormalizer,
)
from orrery.modules.document.parsing.markdown.parser import (
    SectionTreeParser,
)
from orrery.modules.document.model.section_tree import SectionTree


class MarkdownLoader(DocumentLoader):
    """Read → clean → normalize → parse → SectionTree.

    Both passes default on: real-world Markdown rarely satisfies the parser's
    strict structural rules without them. The flags serve tests and inputs
    that are already canonical.
    """

    protocol_format = "markdown"

    def __init__(self, *, clean: bool = True, normalize: bool = True) -> None:
        self._cleaner = MarkdownCleaner() if clean else None
        self._normalizer = MarkdownNormalizer() if normalize else None
        self._parser = SectionTreeParser()

    async def load(self, source_path: Path) -> SectionTree:
        if not source_path.exists():
            raise RuntimeError(f"Markdown source not found: {source_path}")
        return self.parse_text(source_path.read_text(encoding="utf-8"))

    def parse_text(self, text: str) -> SectionTree:
        """Same pipeline, from Markdown already in memory.

        The PDF, DOCX and DOC loaders render their source to Markdown and end
        here, so the four formats share one set of structural rules instead of
        each growing its own.
        """
        if self._cleaner is not None:
            text = self._cleaner.clean(text)
        if self._normalizer is not None:
            text = self._normalizer.normalize(text)
        return self._parser.parse(text)
