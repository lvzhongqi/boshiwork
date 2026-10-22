"""Format-specific document loader interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from orrery.modules.document.model.section_tree import SectionTree


class DocumentLoader(ABC):
    """Source file → SectionTree (raw, unannotated).

    One concrete loader per ``protocol_format`` (Markdown, RFC plain text,
    PDF, Word DOCX, Word DOC). DocumentSet assembly and annotation belong to
    the caller.
    """

    protocol_format: str = ""

    @abstractmethod
    async def load(self, source_path: Path) -> SectionTree:
        raise NotImplementedError
