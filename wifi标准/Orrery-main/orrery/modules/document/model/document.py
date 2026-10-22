"""Per-document container: identity + format + parsed section tree."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from orrery.modules.document.model.section_tree import SectionTree


@dataclass
class Document:
    """A parsed protocol document within a DocumentSet."""

    doc_id: str               # Stable identifier (typically the source filename stem).
    protocol_format: str      # "markdown" | "rfc_txt" | "pdf" | "docx" | "doc".
    source_path: Path
    sections: SectionTree
