"""Section node: a structural container of content blocks and child sections.

Structure only. Tags, references and scope live section-keyed in
:class:`orrery.modules.document.model.overlay.AnnotationOverlay` and are
composed at read time, which keeps deterministic parser output separate from
revisable annotation output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Iterator

from orrery.modules.document.model.block import ContentBlock


@dataclass
class Section:
    """Hierarchical structural section node.

    Level 0 is the virtual root (no number, no title), level 1 a top-level
    section (``## 1 ...`` in Markdown), level n the n-th nesting depth.
    """

    number: str
    title: str
    level: int
    blocks: list[ContentBlock] = field(default_factory=list)
    children: list[Section] = field(default_factory=list)

    def add_child(self, child: Section) -> None:
        self.children.append(child)

    def is_leaf(self) -> bool:
        return not self.children

    def walk(self) -> Iterator[Section]:
        """Pre-order traversal, yields self first then all descendants."""
        yield self
        for c in self.children:
            yield from c.walk()

    def find_block(self, block_id: str) -> ContentBlock | None:
        for b in self.blocks:
            if b.block_id == block_id:
                return b
        return None

    def title_with_number(self) -> str:
        return f"{self.number} {self.title}".strip()

    def title_with_hashes(self) -> str:
        hashes = "#" * max(self.level, 1)
        if self.number:
            return f"{hashes} {self.number} {self.title}"
        return f"{hashes} {self.title}" if self.title else ""

    def __repr__(self) -> str:
        indent = "  " * max(self.level - 1, 0)
        return (
            f"{indent}[{self.number}] {self.title} "
            f"(children={len(self.children)}, blocks={len(self.blocks)})"
        )
