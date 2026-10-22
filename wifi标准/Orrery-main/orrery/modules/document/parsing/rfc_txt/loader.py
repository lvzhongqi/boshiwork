"""RFCTxtLoader: read → clean → parse → SectionTree."""
from __future__ import annotations

from pathlib import Path

from orrery.modules.document.parsing.base import DocumentLoader
from orrery.modules.document.parsing.rfc_txt.cleaner import RFCTxtCleaner
from orrery.modules.document.parsing.rfc_txt.parser import (
    RFCSectionTreeParser,
)
from orrery.modules.document.model.section_tree import SectionTree


class RFCTxtLoader(DocumentLoader):
    """Plain-text RFC / Internet-Draft loader.

    Both v2 (form-feed paginated, with page headers and footers) and v3
    (continuous text) layouts go through the same cleaner and parser; a v2
    input makes the cleaner log one warning.
    """

    protocol_format = "rfc_txt"

    def __init__(self) -> None:
        self._cleaner = RFCTxtCleaner()
        self._parser = RFCSectionTreeParser()

    async def load(self, source_path: Path) -> SectionTree:
        if not source_path.exists():
            raise RuntimeError(f"RFC source not found: {source_path}")
        text = source_path.read_text(encoding="utf-8")
        text = self._cleaner.clean(text)
        return self._parser.parse(text)
