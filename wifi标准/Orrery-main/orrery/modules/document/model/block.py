"""Typed content blocks, the atomic units of a section's content.

Structure only: block-level tags and references live in
:class:`orrery.modules.document.model.overlay.AnnotationOverlay`, keyed by
``(section_number, block_id)`` and joined at read time.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ContentBlock:
    """Abstract base for all content blocks."""

    # Stable identifier within the parent section, e.g. "p3" for paragraph 3,
    # and the join key for block-level overlay annotations.
    block_id: str

    @property
    def kind(self) -> str:
        return type(self).__name__.lower()


@dataclass
class Paragraph(ContentBlock):
    text: str = ""


@dataclass
class Image(ContentBlock):
    path: str = ""
    caption: str = ""


@dataclass
class Table(ContentBlock):
    # Complex tables that resist parsing keep raw_markdown only.
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    raw_markdown: str = ""


@dataclass
class CodeBlock(ContentBlock):
    language: str = ""
    text: str = ""
