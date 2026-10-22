"""All documents involved in one analysis run: the main document plus the
dependency documents that :class:`SegmentReference` resolves against.

DocumentSet also owns the view layer — ``get_sections`` / ``get_section`` /
``grep`` answer everything by walking the already-loaded section tree,
synchronously and without side effects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Iterator

from orrery.modules.document.model.block import (
    CodeBlock,
    ContentBlock,
    Image,
    Paragraph,
    Table,
)
from orrery.modules.document.model.content import (
    AnnotatedContent,
    SectionSummary,
)
from orrery.modules.document.model.document import Document
from orrery.modules.document.model.overlay import AnnotationOverlay
from orrery.modules.document.model.section import Section


@dataclass
class DocumentSet:
    main_doc_id: str
    documents: dict[str, Document] = field(default_factory=dict)
    # Section-keyed annotation overlay for the main document, composed at read
    # time and never baked into the structural Section tree. An empty overlay
    # means every view degrades to structure only.
    overlay: AnnotationOverlay = field(default_factory=AnnotationOverlay)
    # Sub-protocol view, set by the loader: the active sub-protocol name and the
    # description body from subprotocol.md. None means a single protocol.
    active_sub: str | None = None
    subprotocol_note: str = ""
    # Memoized {section_number -> effective sub set}; invalidated lazily
    # by identity of the overlay it was computed from.
    _resolved_subs: dict[str, frozenset[str]] | None = field(
        default=None, repr=False, compare=False
    )
    _resolved_for: int | None = field(
        default=None, repr=False, compare=False
    )
    # Sections cut by prune_to_sub: section number → the sub-protocols owning
    # it. Text and titles are off the tree; keeping the numbers lets an error
    # say "belongs to another sub-protocol" instead of "does not exist".
    pruned_sections: dict[str, frozenset[str]] = field(
        default_factory=dict, repr=False, compare=False
    )

    def _subs_map(self) -> dict[str, frozenset[str]]:
        if self._resolved_subs is None or self._resolved_for != id(self.overlay):
            self._resolved_subs = self.overlay.resolve_subs(self.main().sections)
            self._resolved_for = id(self.overlay)
        return self._resolved_subs

    def get_subprotocols(self) -> list[str]:
        """All sub-protocol names declared for the main document.

        An empty list is the single-protocol case: no scope partition, every
        section shared.
        """
        return self.overlay.subprotocols()

    def get_section_subs(self, number: str) -> frozenset[str]:
        """Effective sub set of one section (empty == shared background)."""
        return self._subs_map().get(number, frozenset())

    def prune_to_sub(self, sub: str) -> None:
        """Cut the sections that do not belong to ``sub``; called once at load.

        Whole subtrees go, so no view walking the tree can reach another
        sub-protocol's text afterwards; cut section numbers land in
        ``pruned_sections``. Raises RuntimeError on an incomplete or
        self-contradicting ownership map.
        """
        declared = self.overlay.subprotocols()
        # An empty ownership map is the single-protocol case: no sibling to
        # isolate, nothing cut. Membership is required only when the map really
        # partitions scope, where a missing declaration leaks text across subs.
        if declared and sub not in declared:
            raise RuntimeError(
                f"prune_to_sub failed: subprotocols.yaml declares no section for "
                f"sub-protocol {sub!r}; declared: {declared}. A multi-sub bundle "
                f"needs a complete ownership map or sections cannot be isolated"
            )
        resolved = self.overlay.resolve_subs(self.main().sections)

        def visible(sec: Section) -> bool:
            subs = resolved.get(sec.number, frozenset())
            return (not subs) or (sub in subs)

        def prune(parent: Section) -> None:
            keep: list[Section] = []
            for child in parent.children:
                if visible(child):
                    keep.append(child)
                    prune(child)
                    continue
                # Ownership is declared at a subtree root and inherited down, so
                # a descendant re-entering scope means the map is wrong: a
                # subsection used across subs must be shared or owned by both.
                reentry = [d.number for d in child.walk() if visible(d)]
                if reentry:
                    raise RuntimeError(
                        f"ownership map contradicts itself: section {child.number} is not in "
                        f"sub-protocol {sub!r}, but its descendants {reentry} are visible "
                        f"to {sub!r}; fix subprotocols.yaml (a subsection depended on "
                        f"across sub-protocols must be shared or owned by both)"
                    )
                for d in child.walk():
                    self.pruned_sections[d.number] = resolved.get(
                        d.number, frozenset()
                    )
            parent.children = keep

        prune(self.main().sections.root)
        self._resolved_subs = None      # the tree changed; invalidate the memo

    def add(self, doc: Document) -> None:
        if not doc.doc_id:
            raise RuntimeError("Document.doc_id must be non-empty")
        if doc.doc_id in self.documents:
            raise RuntimeError(f"Duplicate doc_id in DocumentSet: {doc.doc_id!r}")
        self.documents[doc.doc_id] = doc

    def main(self) -> Document:
        if self.main_doc_id not in self.documents:
            raise RuntimeError(
                f"main_doc_id {self.main_doc_id!r} not loaded "
                f"(available: {list(self.documents)})"
            )
        return self.documents[self.main_doc_id]

    def get(self, doc_id: str) -> Document:
        """Resolve a doc_id, with "self" mapping to the main document."""
        if doc_id == "self":
            return self.main()
        if doc_id not in self.documents:
            raise RuntimeError(
                f"Reference target doc {doc_id!r} not in DocumentSet "
                f"(available: {list(self.documents)})"
            )
        return self.documents[doc_id]

    def doc_ids(self) -> list[str]:
        return list(self.documents.keys())

    def __iter__(self) -> Iterator[Document]:
        return iter(self.documents.values())

    def get_sections(self) -> list[SectionSummary]:
        """Table-of-contents view of the main document.

        One ``SectionSummary`` per non-root section in tree order — the
        discovery primitive for "which sections exist and how are they nested".
        """
        return [
            SectionSummary(number=s.number, title=s.title, level=s.level)
            for s in self.main().sections.walk()
            if s.level > 0
        ]

    def get_section(self, number: str) -> AnnotatedContent:
        """Fetch one section of the main document by its number string.

        ``number`` is the parser's canonical numeric or appendix identifier,
        e.g. ``"4.1.3"``, ``"A"``, ``"A.1.2"``. Raises RuntimeError when the
        section is missing, with a distinct message for a pruned one.
        """
        for s in self.main().sections.walk():
            if s.level > 0 and s.number == number:
                rendered = _render_section(s)
                images = _collect_block_images(s, block_filter=None)
                return AnnotatedContent(text=rendered, images=_dedupe(images))
        owners = self.pruned_sections.get(number)
        if owners is not None:
            raise RuntimeError(
                f"section {number} is out of scope: it belongs to sub-protocol "
                f"{sorted(owners)} and this run models {self.active_sub!r}. "
                f"Do not model from it; if this sub-protocol really depends on "
                f"its content, that is an annotation problem — report it rather "
                f"than working around it"
            )
        raise RuntimeError(
            f"DocumentSet.get_section: section {number!r} not found in main "
            f"document {self.main_doc_id!r}"
        )

    def grep(
        self,
        pattern: str,
        *,
        max_matches: int = 10,
        context_lines: int = 3,
        ref_char_budget: int = 8000,
    ) -> str:
        """Case-insensitive substring search over the main document, with the
        annotated cross-references of the matching sections appended.

        Matches are grouped by section with ±``context_lines`` of surrounding
        text, overlapping windows merged. Bounded by ``max_matches`` (≤30),
        ``context_lines`` (≤8), a 4000-char snippet budget and
        ``ref_char_budget`` (≤32000); what the budgets drop is named in a
        trailing skipped marker.
        """
        if not pattern or not isinstance(pattern, str):
            return ""
        max_matches = min(max(int(max_matches), 1), 30)
        context_lines = min(max(int(context_lines), 0), 8)
        ref_char_budget = min(max(int(ref_char_budget), 0), 32000)
        pat_lower = pattern.lower()
        # Raw (section_obj, section_number, line_index, lines_of_section) hits.
        # Carrying the Section object lets phase 2 follow its references without
        # re-walking the tree.
        hits: list[tuple] = []
        for section in self.main().sections.walk():
            if section.level == 0:
                continue
            rendered = _render_section(section)
            if not rendered:
                continue
            lines = rendered.split("\n")
            for i, line in enumerate(lines):
                if pat_lower in line.lower():
                    hits.append((section, section.number or "?", i, lines))
        # Phase 1: build the snippets, merging adjacent windows in one section.
        # Emitted sections are tracked so phase 2 only follows the refs of
        # sections that actually surfaced.
        parts: list[str] = []
        total_chars = 0
        emitted = 0
        skipped_sections: list[str] = []
        emitted_section_objs: list[Section] = []
        seen_emitted_secs: set = set()
        i = 0
        while i < len(hits):
            section_obj, sec_num, line_idx, lines = hits[i]
            start = max(0, line_idx - context_lines)
            end = min(len(lines), line_idx + context_lines + 1)
            # merge subsequent hits in same section whose window overlaps
            j = i + 1
            while j < len(hits) and hits[j][1] == sec_num:
                next_idx = hits[j][2]
                next_start = max(0, next_idx - context_lines)
                if next_start <= end:
                    end = min(len(lines), next_idx + context_lines + 1)
                    j += 1
                else:
                    break
            snippet = "\n".join(lines[start:end])
            block = f"[§{sec_num}]\n{snippet}\n"
            if emitted >= max_matches:
                skipped_sections.append(str(sec_num))
                i = j
                continue
            if total_chars + len(block) > 4000:
                skipped_sections.append(str(sec_num))
                i = j
                continue
            parts.append(block)
            total_chars += len(block)
            emitted += 1
            if id(section_obj) not in seen_emitted_secs:
                emitted_section_objs.append(section_obj)
                seen_emitted_secs.add(id(section_obj))
            i = j
        if skipped_sections:
            # deduplicate while preserving order
            seen = set()
            uniq = [s for s in skipped_sections if not (s in seen or seen.add(s))]
            parts.append(
                f"\n... [{len(skipped_sections)} more matches in §"
                + ", §".join(uniq[:15])
                + (f", and {len(uniq) - 15} more sections" if len(uniq) > 15 else "")
                + "]; refine your pattern with a longer / more specific substring."
            )
        # Phase 2: follow annotated references on emitted sections.
        ref_blocks, ref_skipped = self._resolve_grep_refs(
            emitted_section_objs, ref_char_budget=ref_char_budget
        )
        if ref_blocks:
            parts.append("\n--- annotated cross-references ---")
            parts.extend(ref_blocks)
        if ref_skipped:
            parts.append(
                f"\n[... {len(ref_skipped)} reference(s) skipped (budget): "
                + ", ".join(ref_skipped[:6])
                + ("..." if len(ref_skipped) > 6 else "")
                + "]"
            )
        if not parts:
            return f"(no matches for {pattern!r} in main document)"
        return "\n".join(parts)

    def _resolve_grep_refs(
        self,
        sections: list[Section],
        *,
        ref_char_budget: int,
        per_ref_cap: int = 5000,
    ) -> tuple:
        """Resolve the ``SegmentReference``s of the given main-doc sections.

        Returns ``(blocks, skipped)``: rendered ref-section fragments, and
        ``"<doc> §<sec>"`` labels for refs the budget dropped. Each
        ``(target_doc, target_section)`` is emitted at most once, cross-document
        refs first with their descendants, self-document refs section-only.
        """
        cross_doc_refs: list[tuple] = []   # (src_sec, ref) for target_doc != "self"
        self_section_refs: list[tuple] = []  # (src_sec, ref) for target_doc == "self"
        seen_keys: set = set()
        for sec in sections:
            sec_refs = list(self.overlay.section_annotation(sec.number).references)
            for blk in sec.blocks:
                sec_refs.extend(
                    self.overlay.block_annotation(sec.number, blk.block_id).references
                )
            for ref in sec_refs:
                key = (ref.target_doc, ref.target_section)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                if ref.target_doc == "self":
                    self_section_refs.append((sec, ref))
                else:
                    cross_doc_refs.append((sec, ref))

        blocks: list[str] = []
        skipped: list[str] = []
        used_chars = 0

        def _resolve_one(src_sec: Section, ref, *, include_descendants: bool):
            nonlocal used_chars
            try:
                target_doc = self.get(ref.target_doc)
            except Exception as e:
                blocks.append(
                    f"\n[ref unresolved: {ref.target_doc} §"
                    f"{ref.target_section} — {e}]\n"
                )
                return
            target_sec = None
            for s in target_doc.sections.root.walk():
                if s.level > 0 and s.number == ref.target_section:
                    target_sec = s
                    break
            if target_sec is None:
                is_main = ref.target_doc in ("self", self.main_doc_id)
                owners = (self.pruned_sections.get(ref.target_section)
                          if is_main else None)
                if owners is not None:
                    blocks.append(
                        f"\n[ref out of scope: §{ref.target_section} belongs to sub-protocol "
                        f"{sorted(owners)}, not visible in this run]\n"
                    )
                    return
                blocks.append(
                    f"\n[ref unresolved: {ref.target_doc} §"
                    f"{ref.target_section} — not in target document]\n"
                )
                return
            doc_label = (
                ref.target_doc if ref.target_doc != "self" else self.main_doc_id
            )
            hint = f" — {ref.inline_hint}" if ref.inline_hint else ""
            header = (
                f"\n[via §{src_sec.number} → {doc_label} §{target_sec.number}"
                f"{hint}]\n"
            )
            body = (
                _render_section_with_descendants(target_sec)
                if include_descendants
                else _render_section(target_sec)
            )
            # Per-ref cap: a single standards-doc section can run 12k+ chars and
            # eat the whole budget. Keep the leading portion, where most of the
            # schemata and algorithms live, and mark the truncation.
            if len(body) > per_ref_cap:
                kept = body[:per_ref_cap]
                # Cut at the last newline so we don't slice mid-paragraph.
                nl = kept.rfind("\n")
                if nl > per_ref_cap * 0.7:
                    kept = kept[:nl]
                body = (
                    kept
                    + f"\n[... ref body truncated at {per_ref_cap} chars "
                    f"(full section is {len(body)} chars); read the "
                    f"specific section with read_section if you need more]"
                )
            block = header + body + "\n"
            if used_chars + len(block) > ref_char_budget:
                skipped.append(f"{doc_label} §{target_sec.number}")
                return
            blocks.append(block)
            used_chars += len(block)

        # Pass 1: cross-doc, with descendants — material seen nowhere else.
        for src_sec, ref in cross_doc_refs:
            _resolve_one(src_sec, ref, include_descendants=True)
        # Pass 2: self-section, section-only; the caller already sees main.
        for src_sec, ref in self_section_refs:
            _resolve_one(src_sec, ref, include_descendants=False)
        return blocks, skipped


def _render_section(
    section: Section,
    block_filter: list[str] | None = None,
) -> str:
    head = section.title_with_hashes()
    body_parts: list[str] = []
    for block in section.blocks:
        if block_filter is not None and block.block_id not in block_filter:
            continue
        body_parts.append(_block_text(block))
    body = "\n".join(p for p in body_parts if p)
    return f"{head}\n{body}".rstrip() if body else head


def _render_section_with_descendants(section: Section) -> str:
    """Render ``section`` together with every descendant, in tree order.

    Grep's reference-following needs this: an annotation targeting ``rfc5869
    §2`` means all of section 2 including subsections, and
    :func:`_render_section` alone yields just a header for a header-only parent.
    """
    parts: list[str] = []
    for s in section.walk():
        rendered = _render_section(s)
        if rendered:
            parts.append(rendered)
    return "\n".join(parts)


def _collect_block_images(
    section: Section, block_filter: list[str] | None
) -> list[str]:
    out: list[str] = []
    for block in section.blocks:
        if block_filter is not None and block.block_id not in block_filter:
            continue
        if isinstance(block, Image) and block.path:
            out.append(block.path)
    return out


def _block_text(block: ContentBlock) -> str:
    if isinstance(block, Paragraph):
        return block.text
    if isinstance(block, Image):
        cap = block.caption or ""
        return f"![{cap}]({block.path})"
    if isinstance(block, Table):
        return block.raw_markdown
    if isinstance(block, CodeBlock):
        return f"```{block.language}\n{block.text}\n```"
    return ""


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out
