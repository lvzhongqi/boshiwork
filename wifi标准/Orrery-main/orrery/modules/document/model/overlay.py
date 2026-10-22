"""Section-keyed annotation overlays, kept off the structural Section tree.

Scope, tags and references are flat dicts keyed by section number, joined to the
tree only at read time. Scope is declared on subtree-root sections and inherited
down the tree, while tags and references are per section and per block, so the
three stay separate maps.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from orrery.modules.document.model.reference import SegmentReference
from orrery.modules.document.model.section_tree import SectionTree
from orrery.modules.document.model.types import SectionType


@dataclass
class Annotation:
    """Type tags + outgoing references for one section or one block."""

    tags: list[SectionType] = field(default_factory=list)
    references: list[SegmentReference] = field(default_factory=list)
    source: str = "unannotated"

    def is_empty(self) -> bool:
        return not self.tags and not self.references


@dataclass
class AnnotationOverlay:
    """Read-time composable overlay: three flat section-keyed maps.

    Built by the annotation loader; consumers (DocumentSet views, grep) join by
    section number with O(1) lookups and never mutate the structural tree.
    """

    #: section number -> whole-section annotation
    sections: dict[str, Annotation] = field(default_factory=dict)
    #: (section number, block_id) -> block annotation
    blocks: dict[tuple[str, str], Annotation] = field(default_factory=dict)
    #: section number -> declared subs (subtree-root declarations only)
    scope_roots: dict[str, list[str]] = field(default_factory=dict)

    # Lookups never raise; an absent entry means unannotated.
    def section_annotation(self, number: str) -> Annotation:
        return self.sections.get(number) or Annotation()

    def block_annotation(self, number: str, block_id: str) -> Annotation:
        return self.blocks.get((number, block_id)) or Annotation()

    def subprotocols(self) -> list[str]:
        """All declared sub-protocol names, sorted, de-duplicated."""
        out: set[str] = set()
        for subs in self.scope_roots.values():
            out.update(subs)
        return sorted(out)

    def is_empty(self) -> bool:
        return not self.sections and not self.blocks and not self.scope_roots

    def resolve_subs(self, tree: SectionTree) -> dict[str, frozenset[str]]:
        """Map every section number to its effective sub set.

        A section inherits the subs of the nearest ancestor (or itself) that
        declares ``scope_roots``; with no declared ancestor it maps to the
        empty set, meaning shared background visible to every sub-protocol.
        """
        resolved: dict[str, frozenset[str]] = {}

        def walk(section, inherited: frozenset[str]) -> None:
            own = self.scope_roots.get(section.number)
            current = frozenset(own) if own else inherited
            if section.level > 0:
                resolved[section.number] = current
            for child in section.children:
                walk(child, current)

        walk(tree.root, frozenset())
        return resolved

    def section_in_sub(
        self,
        number: str,
        sub: str | None,
        resolved: dict[str, frozenset[str]],
    ) -> bool:
        """True if section ``number`` is in ``sub``'s view.

        ``sub is None`` means no scope filter. Otherwise a section passes when
        it is declared in ``sub`` or is shared background that no sub claims,
        so common definitions and assumptions stay visible to every sub.
        """
        if sub is None:
            return True
        subs = resolved.get(number, frozenset())
        return (not subs) or (sub in subs)
