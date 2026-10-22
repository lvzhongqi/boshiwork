"""The inline corpus: document text rendered at the head of reader prompts.

Selection depends on size: a main document within ``max_chars`` is inlined
whole, a larger one only through its tagged sections (flow, entities, or
assumption/security depending on the reader), otherwise contents only.
Reference documents are never inlined; the read_section / grep_document tools
stay available so a model can fetch whatever the selection missed.
"""

from __future__ import annotations

import logging

from orrery.modules.document.model.document_set import (
    DocumentSet,
    _render_section_with_descendants,
)
from orrery.modules.document.model.types import SectionType
from orrery.modules.document.sections import toc

logger = logging.getLogger(__name__)

_HEAD = (
    "The protocol document corpus. Read the inlined text below first; any "
    "section not inlined — and any reference document — is fetchable with "
    "read_section / grep_document. Figures are available through read_section "
    "only."
)


def inline_corpus(
    doc_set: DocumentSet,
    max_chars: int,
    *,
    get_flow: bool = False,
) -> str:
    """Render the corpus block, deterministic for a given document set and
    limit — byte-stable output is what makes the prefix cache hit. ``get_flow``
    adds a bounded ``mode=append`` reference closure of the visible flow
    sections, which only ``extract_flow`` needs.
    """
    parts = [_HEAD, "", "[contents — main document]", toc(doc_set)]
    refs = [d for d in doc_set.doc_ids() if d != doc_set.main_doc_id]
    if refs:
        parts += ["", "[reference documents, not inlined]", ", ".join(sorted(refs))]
        for doc_id in sorted(refs):
            parts += ["", f"[contents — reference document {doc_id}]", toc(doc_set, doc_id)]

    top = [s for s in doc_set.main().sections.walk() if s.level == 1]
    whole = "\n\n".join(_render_section_with_descendants(s) for s in top)
    if len(whole) <= max_chars:
        parts += ["", "[document text — complete]", whole]
        _append_flow_references(
            parts, doc_set, max_chars, get_flow=get_flow,
            main_fully_inlined=True,
        )
        return "\n".join(parts)

    flow = _flow_roots(doc_set)
    if flow:
        body = "\n\n".join(_render_section_with_descendants(s) for s in flow)
        numbers = ", ".join(s.number for s in flow)
        parts += ["", f"[document text — flow sections only ({numbers}); "
                      f"fetch the rest by section number]", body]
        _append_flow_references(
            parts, doc_set, max_chars, get_flow=get_flow,
            main_fully_inlined=False,
        )
        return "\n".join(parts)

    parts += ["", "[document text not inlined — no flow tags and the document "
                  "exceeds the inline limit; fetch sections by number]"]
    return "\n".join(parts)


def inline_principals_corpus(doc_set: DocumentSet, max_chars: int) -> str:
    """Corpus for principal and initial-knowledge extraction: ``entities`` plus
    ``flow`` roots, the flow showing who sends each value and the entity
    sections the component boundaries and provisioned knowledge. Falls back to
    :func:`inline_corpus` for a document within the limit or with neither tag.
    """
    top = [s for s in doc_set.main().sections.walk() if s.level == 1]
    whole = "\n\n".join(_render_section_with_descendants(s) for s in top)
    if len(whole) <= max_chars:
        return inline_corpus(doc_set, max_chars)

    roots = _tag_roots(
        doc_set,
        include={SectionType.ENTITIES, SectionType.FLOW},
    )
    if not roots:
        return inline_corpus(doc_set, max_chars)

    parts = [_HEAD, "", "[contents — main document]", toc(doc_set)]
    refs = [d for d in doc_set.doc_ids() if d != doc_set.main_doc_id]
    if refs:
        parts += ["", "[reference documents, not inlined]", ", ".join(sorted(refs))]
        for doc_id in sorted(refs):
            parts += ["", f"[contents — reference document {doc_id}]",
                      toc(doc_set, doc_id)]

    body = "\n\n".join(_render_section_with_descendants(s) for s in roots)
    numbers = ", ".join(s.number for s in roots)
    parts += [
        "",
        f"[document text — entity/flow sections only ({numbers}); "
        "fetch the rest by section number]",
        body,
    ]
    return "\n".join(parts)


def inline_analysis_corpus(doc_set: DocumentSet, max_chars: int) -> str:
    """Corpus for assumptions, properties and claims extraction: the union of
    ``assumption`` and ``security`` roots, keeping sections that also carry
    ``flow``. A document within the limit goes through :func:`inline_corpus`;
    a large one carrying neither tag raises RuntimeError.
    """
    top = [s for s in doc_set.main().sections.walk() if s.level == 1]
    whole = "\n\n".join(_render_section_with_descendants(s) for s in top)
    if len(whole) <= max_chars:
        return inline_corpus(doc_set, max_chars)

    roots = _tag_roots(
        doc_set,
        include={SectionType.ASSUMPTION, SectionType.SECURITY},
    )
    if not roots:
        raise RuntimeError(
            "large document has no sections tagged assumption or security; "
            "analysis extraction refuses to fall back to unrelated text")

    parts = [_HEAD, "", "[contents — main document]", toc(doc_set)]
    refs = [d for d in doc_set.doc_ids() if d != doc_set.main_doc_id]
    if refs:
        parts += ["", "[reference documents, not inlined]", ", ".join(sorted(refs))]
        for doc_id in sorted(refs):
            parts += ["", f"[contents — reference document {doc_id}]",
                      toc(doc_set, doc_id)]

    body = "\n\n".join(_render_section_with_descendants(s) for s in roots)
    numbers = ", ".join(s.number for s in roots)
    parts += [
        "",
        f"[document text — assumption/security sections only ({numbers}); "
        "mixed-tag sections included; fetch the rest by section number]",
        body,
    ]
    return "\n".join(parts)


def _append_flow_references(
    parts: list[str],
    doc_set: DocumentSet,
    max_chars: int,
    *,
    get_flow: bool,
    main_fully_inlined: bool,
) -> None:
    """Append the resolved ``append`` closure, used only by ``extract_flow``.
    Sections are atomic: present in full, or named in the skipped marker and
    left to ``read_section``. The block has its own ``max_chars`` budget, so a
    large standard's reference graph cannot make the prompt unbounded.
    """
    if not get_flow:
        return

    roots = _flow_roots(doc_set)
    if not roots:
        return

    visible_main = (
        {
            section.number
            for section in doc_set.main().sections.walk()
            if section.level > 0
        }
        if main_fully_inlined
        else {
            section.number
            for root in roots
            for section in root.walk()
            if section.level > 0
        }
    )
    queue: list[tuple[str, object]] = []

    def enqueue_from(section) -> None:
        refs = list(doc_set.overlay.section_annotation(section.number).references)
        for block in section.blocks:
            refs.extend(
                doc_set.overlay.block_annotation(
                    section.number, block.block_id
                ).references
            )
        queue.extend(
            (section.number, ref) for ref in refs if ref.mode == "append"
        )

    for root in roots:
        for section in root.walk():
            if section.level > 0:
                enqueue_from(section)

    emitted: list[str] = []
    skipped: list[str] = []
    seen: set[tuple[str, str]] = set()
    used = 0

    while queue:
        source_number, ref = queue.pop(0)
        key = (ref.target_doc, ref.target_section)
        if key in seen:
            continue
        seen.add(key)
        if ref.target_doc == "self" and ref.target_section in visible_main:
            continue

        try:
            target_doc = doc_set.get(ref.target_doc)
        except RuntimeError as e:
            raise RuntimeError(
                f"flow reference from §{source_number} cannot resolve "
                f"{ref.target_doc} §{ref.target_section}: {e}"
            ) from None
        target = next(
            (
                section
                for section in target_doc.sections.walk()
                if section.level > 0 and section.number == ref.target_section
            ),
            None,
        )
        if target is None:
            owners = (
                doc_set.pruned_sections.get(ref.target_section)
                if ref.target_doc in ("self", doc_set.main_doc_id)
                else None
            )
            if owners is not None:
                # The scope already pruned this section, so the target belongs
                # to another sub-protocol. Logged rather than dropped, because
                # a mistyped section number lands here too.
                logger.info(
                    "corpus: §%s → §%s skipped, it belongs to sub-protocol %s "
                    "and this run models %r",
                    source_number, ref.target_section, sorted(owners),
                    doc_set.active_sub,
                )
                continue
            raise RuntimeError(
                f"flow reference from §{source_number} cannot resolve "
                f"{ref.target_doc} §{ref.target_section}: target section absent"
            )

        label = ref.target_doc if ref.target_doc != "self" else doc_set.main_doc_id
        hint = f" — {ref.inline_hint}" if ref.inline_hint else ""
        body = _render_section_with_descendants(target)
        block = (
            f"[via §{source_number} → {label} §{target.number}{hint}]\n"
            f"{body}"
        )
        if used + len(block) > max_chars:
            skipped.append(f"{label} §{target.number}")
            continue
        emitted.append(block)
        used += len(block)

        # Only the main document carries an annotation overlay, so the closure
        # extends through self targets alone.
        if ref.target_doc == "self":
            for section in target.walk():
                if section.level > 0:
                    visible_main.add(section.number)
                    enqueue_from(section)

    if emitted:
        parts += ["", "[resolved flow reference sections]", "\n\n".join(emitted)]
    if skipped:
        parts += [
            "",
            "[flow reference sections not inlined — dependency budget exhausted; "
            "fetch with read_section]",
            ", ".join(skipped),
        ]


def flow_text(doc_set: DocumentSet) -> tuple[str, str]:
    """The protocol-flow sections as one block, plus which selection produced
    it (``"flow_sections"`` / ``"whole_document"``). Same selection as the
    corpus block, but unbounded and without the contents; the caller records
    the second value as the provenance of the reconciliation it feeds.
    """
    flow = _flow_roots(doc_set)
    if flow:
        return ("\n\n".join(_render_section_with_descendants(s) for s in flow),
                "flow_sections")
    top = [s for s in doc_set.main().sections.walk() if s.level == 1]
    return ("\n\n".join(_render_section_with_descendants(s) for s in top),
            "whole_document")


def _flow_roots(doc_set: DocumentSet):
    """Sections tagged ``flow``, minus any whose ancestor is already selected —
    rendering is subtree-deep, so a nested selection would duplicate text."""
    return _tag_roots(doc_set, include={SectionType.FLOW})


def _tag_roots(
    doc_set: DocumentSet,
    *,
    include: set[SectionType],
    exclude: set[SectionType] | None = None,
):
    """Tagged sections without nested duplicates, with explicit exclusions."""
    excluded = exclude or set()
    tagged = [
        s for s in doc_set.main().sections.walk()
        if s.level > 0
        and include & set(doc_set.overlay.section_annotation(s.number).tags)
        and not excluded & set(doc_set.overlay.section_annotation(s.number).tags)
    ]
    numbers = {s.number for s in tagged}
    return [
        s for s in tagged
        if not any(_is_ancestor(other, s.number) for other in numbers - {s.number})
    ]


def _is_ancestor(candidate: str, number: str) -> bool:
    return number.startswith(candidate + ".")
