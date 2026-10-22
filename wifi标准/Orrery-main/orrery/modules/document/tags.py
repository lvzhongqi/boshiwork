"""Read the three annotation files (subprotocols / tags / references.yaml) and
assemble them into an overlay.

One shared annotations/ directory per version, joined onto the parsed tree by
section number; scope is declared only at a subtree's root and inherited down
the tree. Entry points: build_overlay and apply_annotations.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from orrery.modules.document.model.document_set import DocumentSet
from orrery.modules.document.model.overlay import (
    Annotation,
    AnnotationOverlay,
)
from orrery.modules.document.model.reference import SegmentReference
from orrery.modules.document.model.types import SectionType

logger = logging.getLogger(__name__)

# Keep in sync with annotation_loader.SCHEMA_VERSION.
SCHEMA_VERSION = 4

_SUBPROTOCOLS_FILE = "subprotocols.yaml"
_TAGS_FILE = "tags.yaml"
_REFERENCES_FILE = "references.yaml"


def build_overlay(
    doc_set: DocumentSet, annotations_dir: Path | None
) -> AnnotationOverlay:
    """Read the three annotation files under ``annotations_dir`` into an overlay.

    ``annotations_dir=None`` gives an empty overlay. Section numbers and block
    ids are validated against the main document's parsed tree and reference
    ``target_doc`` against the DocumentSet; a mismatch raises RuntimeError.
    """
    overlay = AnnotationOverlay()
    if annotations_dir is None:
        return overlay
    annotations_dir = Path(annotations_dir)
    if not annotations_dir.is_dir():
        raise RuntimeError(
            f"annotations path is not a directory: {annotations_dir}"
        )

    main = doc_set.main()
    valid_sections = {s.number for s in main.sections.walk() if s.level > 0}
    valid_block_ids = {
        s.number: {b.block_id for b in s.blocks}
        for s in main.sections.walk()
        if s.level > 0
    }
    known_doc_ids = set(doc_set.doc_ids()) | {"self"}

    scope = _read_file(annotations_dir / _SUBPROTOCOLS_FILE, "subprotocols")
    tags = _read_file(annotations_dir / _TAGS_FILE, "tags")
    refs = _read_file(annotations_dir / _REFERENCES_FILE, "references")

    _ingest_scope(overlay, scope, valid_sections)
    _ingest_tags(overlay, tags, valid_sections, valid_block_ids)
    _ingest_refs(overlay, refs, valid_sections, valid_block_ids, known_doc_ids)

    logger.info(
        "Built annotation overlay for doc '%s' "
        "(scope_roots=%d, section_tags/refs=%d, block annotations=%d, subs=%s)",
        main.doc_id,
        len(overlay.scope_roots),
        len(overlay.sections),
        len(overlay.blocks),
        overlay.subprotocols() or "<single>",
    )
    return overlay


def apply_annotations(
    doc_set: DocumentSet, annotations_dir: Path | None
) -> AnnotationOverlay:
    """Build the overlay, set it on ``doc_set.overlay`` and return it. The
    Section tree itself is left untouched — annotation stays alongside it."""
    overlay = build_overlay(doc_set, annotations_dir)
    doc_set.overlay = overlay
    return overlay


def _read_file(path: Path, top_key: str) -> dict:
    """Read one annotation file and return its ``top_key`` mapping. A missing
    file gives an empty mapping; a schema_version mismatch raises."""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise RuntimeError(f"{path}: must be a YAML mapping, got {type(data).__name__}")
    schema = data.get("schema_version")
    if schema != SCHEMA_VERSION:
        raise RuntimeError(
            f"{path}: schema_version {schema!r} != expected {SCHEMA_VERSION}"
        )
    payload = data.get(top_key)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"{path}: top-level {top_key!r} must be a mapping, "
            f"got {type(payload).__name__}"
        )
    return payload


def _check_section(path_label: str, sec: str, valid_sections: set) -> None:
    if sec not in valid_sections:
        raise RuntimeError(
            f"{path_label}: references unknown section {sec!r} in main document"
        )


def _ingest_scope(
    overlay: AnnotationOverlay, raw: dict, valid_sections: set
) -> None:
    for sec, entry in raw.items():
        _check_section("subprotocols.yaml", sec, valid_sections)
        if not isinstance(entry, dict):
            raise RuntimeError(
                f"subprotocols.yaml: section {sec!r} entry must be a mapping"
            )
        subs = entry.get("sub") or []
        if not isinstance(subs, list) or not all(isinstance(x, str) for x in subs):
            raise RuntimeError(
                f"subprotocols.yaml: section {sec!r} 'sub' must be a list of strings"
            )
        if subs:
            overlay.scope_roots[sec] = list(subs)


def _section_anno(overlay: AnnotationOverlay, sec: str) -> Annotation:
    a = overlay.sections.get(sec)
    if a is None:
        a = Annotation()
        overlay.sections[sec] = a
    return a


def _block_anno(overlay: AnnotationOverlay, sec: str, block_id: str) -> Annotation:
    key = (sec, block_id)
    a = overlay.blocks.get(key)
    if a is None:
        a = Annotation()
        overlay.blocks[key] = a
    return a


def _block_id(path_label: str, sec: str, locate) -> str:
    if not isinstance(locate, dict) or "paragraph" not in locate:
        raise RuntimeError(
            f"{path_label}: section {sec!r} block missing locate.paragraph"
        )
    return f"p{int(locate['paragraph'])}"


def _ingest_tags(
    overlay: AnnotationOverlay,
    raw: dict,
    valid_sections: set,
    valid_block_ids: dict,
) -> None:
    for sec, entry in raw.items():
        _check_section("tags.yaml", sec, valid_sections)
        if not isinstance(entry, dict):
            raise RuntimeError(f"tags.yaml: section {sec!r} entry must be a mapping")
        section_tags = [SectionType.from_str(t) for t in entry.get("tags") or []]
        if section_tags:
            a = _section_anno(overlay, sec)
            a.tags = _merge_unique(a.tags, section_tags)
            a.source = entry.get("source", "human")
        for blk in entry.get("blocks") or []:
            if not isinstance(blk, dict):
                raise RuntimeError(
                    f"tags.yaml: section {sec!r} block entry must be a mapping"
                )
            bid = _block_id("tags.yaml", sec, blk.get("locate"))
            if bid not in valid_block_ids.get(sec, set()):
                raise RuntimeError(
                    f"tags.yaml: section {sec!r} block {bid!r} not found"
                )
            btags = [SectionType.from_str(t) for t in blk.get("tags") or []]
            if btags:
                ba = _block_anno(overlay, sec, bid)
                ba.tags = _merge_unique(ba.tags, btags)
                ba.source = blk.get("source", "human")


def _ingest_refs(
    overlay: AnnotationOverlay,
    raw: dict,
    valid_sections: set,
    valid_block_ids: dict,
    known_doc_ids: set,
) -> None:
    for sec, entry in raw.items():
        _check_section("references.yaml", sec, valid_sections)
        if not isinstance(entry, dict):
            raise RuntimeError(
                f"references.yaml: section {sec!r} entry must be a mapping"
            )
        srefs = _parse_refs(
            entry.get("references"), sec, "<section>", known_doc_ids
        )
        if srefs:
            a = _section_anno(overlay, sec)
            a.references = _merge_refs(a.references, srefs)
        for blk in entry.get("blocks") or []:
            if not isinstance(blk, dict):
                raise RuntimeError(
                    f"references.yaml: section {sec!r} block entry must be a mapping"
                )
            bid = _block_id("references.yaml", sec, blk.get("locate"))
            if bid not in valid_block_ids.get(sec, set()):
                raise RuntimeError(
                    f"references.yaml: section {sec!r} block {bid!r} not found"
                )
            brefs = _parse_refs(blk.get("references"), sec, bid, known_doc_ids)
            if brefs:
                ba = _block_anno(overlay, sec, bid)
                ba.references = _merge_refs(ba.references, brefs)


def _parse_refs(
    raw, section_number: str, scope: str, known_doc_ids: set
) -> list[SegmentReference]:
    if not raw:
        return []
    if not isinstance(raw, list):
        raise RuntimeError(
            f"references.yaml: section {section_number!r} ({scope}): "
            f"'references' must be a list"
        )
    out: list[SegmentReference] = []
    for item in raw:
        if not isinstance(item, dict):
            raise RuntimeError(
                f"references.yaml: section {section_number!r} ({scope}): "
                f"each reference must be a mapping"
            )
        ref = SegmentReference.from_dict(item)
        if ref.target_doc not in known_doc_ids:
            raise RuntimeError(
                f"references.yaml: section {section_number!r} ({scope}): "
                f"target_doc {ref.target_doc!r} not in DocumentSet "
                f"(known: {sorted(known_doc_ids)})"
            )
        if ref.mode not in ("replace", "append"):
            raise RuntimeError(
                f"references.yaml: section {section_number!r} ({scope}): "
                f"mode {ref.mode!r} must be 'replace' or 'append'"
            )
        out.append(ref)
    return out


def _merge_unique(existing: list, incoming: list) -> list:
    out = list(existing)
    for item in incoming:
        if item not in out:
            out.append(item)
    return out


def _merge_refs(
    existing: list[SegmentReference], incoming: list[SegmentReference]
) -> list[SegmentReference]:
    out = list(existing)
    keys = {(r.target_doc, r.target_section, r.ref_kind, r.mode) for r in out}
    for r in incoming:
        k = (r.target_doc, r.target_section, r.ref_kind, r.mode)
        if k not in keys:
            out.append(r)
            keys.add(k)
    return out
