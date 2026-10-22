"""The sections façade behind the read_section tool: render a table of contents,
and read a section's text by number.

``DocumentSet.get_section`` at the model layer only sees the main document, so
the same lookup is repeated here over the reference documents — the tool has to
reach "main, or one of the references".
"""

from __future__ import annotations

from orrery.modules.document.model.content import AnnotatedContent
from orrery.modules.document.model.document_set import (
    DocumentSet,
    _render_section,
)


def toc(doc_set: DocumentSet, doc_id: str | None = None) -> str:
    """One document's table of contents as indented text, one section per line.

    ``doc_id=None`` renders the main document, any other id that reference
    document. The main contents of a multi-sub-protocol bundle carry a scope
    note in front: the other sub-protocols' sections were cut at load time, so
    the numbering has gaps and the document is not damaged.
    """
    if doc_id is None or doc_id == doc_set.main_doc_id:
        sections = doc_set.get_sections()
        is_main = True
    else:
        doc = doc_set.get(doc_id)  # explicit error for an unknown reference id
        sections = [s for s in doc.sections.walk() if s.level > 0]
        is_main = False

    lines = [f"{'  ' * (s.level - 1)}{s.number}  {s.title}" for s in sections]
    body = "\n".join(lines)
    if not is_main:
        return body
    sub = doc_set.active_sub
    if not sub:
        return body
    head = [
        f"[scope] This protocol has several sub-protocols; this run models {sub} "
        f"only. The document view is narrowed to it: the other sub-protocols' "
        f"sections are absent from both the contents and the text, so the "
        f"numbering may have gaps. Shared background sections are kept."
    ]
    note = doc_set.subprotocol_note
    if note:
        head.append(note)
    return "\n".join(head) + "\n\n" + body


def read_section(
    doc_set: DocumentSet, number: str, doc_id: str | None = None
) -> AnnotatedContent:
    """Read a section's text by number. ``doc_id=None`` reads the main document,
    anything else that reference document. An unknown document id or section
    number raises RuntimeError.
    """
    if doc_id is None or doc_id == doc_set.main_doc_id:
        return doc_set.get_section(number)
    if doc_id not in doc_set.doc_ids():
        raise RuntimeError(
            f"read_section failed: no document {doc_id!r} in the set; available: {doc_set.doc_ids()}"
        )
    for s in doc_set.get(doc_id).sections.walk():
        if s.level > 0 and s.number == number:
            return AnnotatedContent(text=_render_section(s), images=[])
    raise RuntimeError(
        f"read_section failed: document {doc_id!r} has no section {number!r}"
    )
