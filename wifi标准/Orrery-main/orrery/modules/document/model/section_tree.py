"""Per-document section tree: document title + virtual root + top-level sections."""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Iterator

from orrery.modules.document.model.section import Section


@dataclass
class SectionTree:
    """Parsed section structure of a single document."""

    doc_title: str = ""
    # Free-form pre-section text (preamble before the first numbered section).
    header: str = ""
    # Virtual root (level=0) — actual sections hang from its children.
    root: Section = field(default_factory=lambda: Section(number="", title="", level=0))

    @property
    def top_level(self) -> list[Section]:
        return self.root.children

    def walk(self) -> Iterator[Section]:
        """Pre-order traversal including the virtual root."""
        yield from self.root.walk()
