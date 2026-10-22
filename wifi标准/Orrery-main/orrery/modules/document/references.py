"""The references façade behind the get_reference tool: which sections and which
external documents a given section points at.

Forward direction only; the reverse is covered by grep. The data comes from the
references.yaml annotation, so ``resolved=False`` means no annotation was
available — a different fact from ``resolved=True`` with an empty list, which
means the section genuinely references nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from orrery.modules.document.model.document_set import DocumentSet
from orrery.modules.document.model.reference import SegmentReference


@dataclass(frozen=True)
class SectionReferences:
    resolved: bool                      # False = no annotation, references unresolved
    references: list[SegmentReference]  # always empty when resolved=False


def section_references(doc_set: DocumentSet, number: str) -> SectionReferences:
    """The outgoing references of one main-document section, from its
    section-level annotation. A nonexistent section number raises RuntimeError."""
    doc_set.get_section(number)         # reuse its existence check and error wording
    if doc_set.overlay.is_empty():
        return SectionReferences(resolved=False, references=[])
    ann = doc_set.overlay.section_annotation(number)
    return SectionReferences(resolved=True, references=list(ann.references))
