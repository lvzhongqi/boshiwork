"""Input bundles for the document loader: discovery, validation and parsing.

``ProtocolSource`` names a protocol's documents and annotation directory;
``DocumentLoaderService`` parses them into a ``DocumentSet`` keyed by file
stem. A bundle is ``source/main/<one file>`` plus optional ``source/refs/*``,
``annotations/`` and ``subprotocols/<sub>/``; other shapes raise RuntimeError.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from orrery.modules.document.model.document import Document
from orrery.modules.document.model.document_set import DocumentSet
from orrery.modules.document.parsing.factory import (
    infer_protocol_format,
    make_document_loader,
)
from orrery.modules.document.tags import apply_annotations

logger = logging.getLogger(__name__)

# Shared annotation directory, at the version level and sub-agnostic.
_ANNOTATIONS_DIRNAME = "annotations"
# Single-file annotation names; their presence triggers a migration error.
_LEGACY_ANNOTATION_FILENAMES = ("annotations.yaml", "annotation.yaml")

# Extensions the per-format loaders understand (see parsing/factory.py), split
# by whether the loader reads the document's structure or reconstructs it.
_TEXT_EXTS = {".md", ".markdown", ".txt"}
_BINARY_EXTS = {".pdf", ".docx", ".doc"}
_SUPPORTED_EXTS = _TEXT_EXTS | _BINARY_EXTS


def is_document(path: Path) -> bool:
    """Whether the pipeline can read this file at all.

    Exported so the launch panel can answer the same question one step
    earlier, before offering a file the loader would refuse.
    """
    return path.is_file() and path.suffix.lower() in _SUPPORTED_EXTS


def is_text_document(path: Path) -> bool:
    """Whether this document's structure is read rather than reconstructed."""
    return Path(path).suffix.lower() in _TEXT_EXTS


def bundle_reads_text(root: Path) -> bool:
    """Whether this bundle's subject document is text.

    That one fact fixes how the whole bundle is read, references included, so
    the console can answer the same question the loader will
    (``ProtocolSource._find_ref_docs``) without parsing anything.
    """
    main_dir = Path(root) / "source" / "main"
    if not main_dir.is_dir():
        return False
    mains = prefer_text([p for p in main_dir.iterdir() if is_document(p)])
    return bool(mains) and is_text_document(mains[0])


def prefer_text(paths: Sequence[Path]) -> list[Path]:
    """A directory's text documents, or its originals when it has none.

    Text wins outright. The corpus keeps the authoritative original beside the
    copy it is read from — ``9798-1.pdf`` next to ``9798-1.md``,
    ``33501-f00.doc`` next to ``33501-f00.md`` — and a curated conversion is
    always the better read, so a directory holding any Markdown or RFC text is
    read from that and the originals beside it are left alone, whatever they
    are named. Reconstructing a PDF or a Word file is what happens when there
    is nothing else in the directory to read.
    """
    paths = list(paths)
    text = [p for p in paths if p.suffix.lower() in _TEXT_EXTS]
    if text:
        dropped = [p for p in paths if p.suffix.lower() in _BINARY_EXTS]
        if dropped:
            logger.info(
                "Reading this directory's text documents and leaving the "
                "originals beside them: %s", [p.name for p in dropped],
            )
        return sorted(text)
    if paths:
        # Worth saying out loud: this text was reconstructed from a PDF or a
        # Word file, not read from a conversion someone checked. It is what the
        # run was given, so it belongs in the run's log.
        logger.warning(
            "Reading %s directly — the directory carries no text version. The "
            "section structure is reconstructed by the loader.",
            [p.name for p in paths],
        )
    return sorted(paths)


def resolve_subprotocol_name(root: Path, target_name: str | None = None) -> str | None:
    """Resolve the selected analysis target without parsing any document.

    A lone directory under ``subprotocols/`` is the default target; several
    require ``target_name``. Returns None when there is no ``subprotocols/``,
    and raises RuntimeError on an empty, ambiguous or unknown target.
    """
    root = Path(root)
    subs_dir = root / "subprotocols"
    if subs_dir.is_dir():
        available = sorted(p.name for p in subs_dir.iterdir() if p.is_dir())
        if not available:
            raise RuntimeError(
                f"ProtocolSource: {subs_dir} exists but contains no sub-protocol directories")
        if target_name is None:
            if len(available) == 1:
                return available[0]
            raise RuntimeError(
                f"ProtocolSource: {root} is a multi-sub bundle; `target_name` is required. "
                f"Available sub-protocols: {available}")
        if target_name not in available:
            raise RuntimeError(
                f"ProtocolSource: sub-protocol {target_name!r} not found under "
                f"{subs_dir}. Available: {available}")
        return target_name
    if target_name is not None:
        raise RuntimeError(
            f"ProtocolSource: {root} has no subprotocols/ directory, but "
            f"target_name={target_name!r} was supplied")
    return None


@dataclass
class ProtocolSource:
    """Paths describing one protocol's main document and its dependencies.

    Fields are pure Paths; the annotation directory is read by the loader
    service at load time, not at construction. Run artifacts (``claims/``,
    ``results/``, ``formal/``) sit under the sub-protocol directory and are
    parsed by the entry point.
    """

    main_doc: Path
    ref_docs: list[Path] = field(default_factory=list)
    # Directory holding subprotocols.yaml / tags.yaml / references.yaml, shared
    # at the version level. None when there are no annotations.
    annotations: Path | None = None
    sub: str | None = None
    #: Body of subprotocol.md with the frontmatter stripped, injected into the
    #: extraction prompts throughout.
    sub_description: str | None = None

    @classmethod
    def from_directory(
        cls,
        root: Path,
        target_name: str | None = None,
    ) -> ProtocolSource:
        """Discover a ProtocolSource by walking a VerdictBench-shaped directory.

        ``root`` holds ``source/``, an optional ``annotations/`` and an
        optional ``subprotocols/``; ``target_name`` is required only when the
        bundle offers more than one sub-protocol. Raises RuntimeError on any
        layout mismatch.
        """
        root = Path(root)
        if not root.exists() or not root.is_dir():
            raise RuntimeError(f"ProtocolSource root is not a directory: {root}")

        source_dir = cls._resolve_source_dir(root)
        main_doc = cls._find_main_doc(source_dir)
        ref_docs = cls._find_ref_docs(source_dir, main_doc)
        annotations = cls._resolve_annotations_dir(root)
        artifact_root, resolved_sub = cls._resolve_subprotocol(root, target_name)
        sub_description = (
            cls._read_subprotocol_md(artifact_root) if resolved_sub else None
        )

        logger.info(
            "ProtocolSource discovered: root=%s sub=%s main=%s refs=%s annotations=%s",
            root,
            resolved_sub or "<single>",
            main_doc.name,
            [p.name for p in ref_docs],
            annotations.name if annotations else "<none>",
        )
        return cls(
            main_doc=main_doc,
            ref_docs=ref_docs,
            annotations=annotations,
            sub=resolved_sub,
            sub_description=sub_description,
        )

    @classmethod
    def from_documents(
        cls,
        main_doc: Path,
        ref_docs: Sequence[Path] = (),
    ) -> ProtocolSource:
        """A bundle whose documents the caller names outright.

        The console uses this when a reader names the subject document
        directly. ``ref_docs`` stays empty unless named: a reference is a
        declared relation, and guessing one costs the corpus block that four
        nodes share as one cached prefix. The bundle carries no annotations.
        """
        main_doc = Path(main_doc)
        if not main_doc.is_file():
            raise RuntimeError(
                f"ProtocolSource: main document is not a file: {main_doc}")
        if not is_document(main_doc):
            raise RuntimeError(
                f"ProtocolSource: {main_doc.name} is not a document this "
                f"pipeline can read (expected one of "
                f"{sorted(_SUPPORTED_EXTS)})")
        refs = [Path(r) for r in ref_docs]
        for r in refs:
            if not is_document(r):
                raise RuntimeError(
                    f"ProtocolSource: reference {r} is not a readable document "
                    f"(expected one of {sorted(_SUPPORTED_EXTS)})")
        if main_doc in refs:
            raise RuntimeError(
                f"ProtocolSource: {main_doc.name} is named as both the main "
                f"document and one of its own references")
        logger.info("ProtocolSource given: main=%s refs=%s",
                    main_doc.name, [p.name for p in refs])
        return cls(main_doc=main_doc, ref_docs=refs)

    def all_docs(self) -> list[Path]:
        """All document paths to be parsed: main first, then refs."""
        return [self.main_doc, *self.ref_docs]

    # Directory discovery below is strict: there are no fallback layouts.

    @staticmethod
    def _resolve_source_dir(root: Path) -> Path:
        source_dir = root / "source"
        if not source_dir.is_dir():
            raise RuntimeError(
                f"ProtocolSource layout error: missing `source/` directory "
                f"under {root}"
            )
        return source_dir

    @staticmethod
    def _find_main_doc(source_dir: Path) -> Path:
        """The one document this unit is analysed from.

        A missing ``main/`` and an empty ``main/`` both report a missing
        document rather than a layout fault: the corpus does not carry this
        unit's document. Two or more readable files there is a layout fault.
        """
        main_dir = source_dir / "main"
        if not main_dir.is_dir():
            raise RuntimeError(
                f"no document to analyse: {main_dir} does not exist. This "
                f"corpus does not carry this unit's document — check the unit "
                f"before running the pipeline on it."
            )
        candidates = prefer_text([
            p for p in main_dir.iterdir()
            if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTS
        ])
        if not candidates:
            raise RuntimeError(
                f"no document to analyse: {main_dir} holds no readable "
                f"document (expected one of {sorted(_SUPPORTED_EXTS)}). This "
                f"corpus does not carry this unit's document — check the unit "
                f"before running the pipeline on it."
            )
        if len(candidates) > 1:
            raise RuntimeError(
                f"ProtocolSource layout error: {main_dir} must contain "
                f"exactly one document, got {[p.name for p in candidates]}"
            )
        return candidates[0]

    @staticmethod
    def _find_ref_docs(source_dir: Path, main_doc: Path) -> list[Path]:
        """The bundle's references, in the format its main document set.

        A bundle whose subject is Markdown is a Markdown bundle throughout: the
        PDF sitting unconverted in ``refs/`` is the original of a reference
        nobody converted, and pulling it in would enlarge the corpus block of a
        unit that reads the same today as it did yesterday. A bundle whose
        subject is a PDF has no conversions to prefer, so its references are
        read the same way its subject is.
        """
        refs_dir = source_dir / "refs"
        if not refs_dir.exists():
            return []
        if not refs_dir.is_dir():
            raise RuntimeError(
                f"ProtocolSource layout error: `refs` is not a directory: {refs_dir}"
            )
        readable = [p for p in sorted(refs_dir.iterdir())
                    if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTS]
        unreadable = [p for p in sorted(refs_dir.iterdir())
                      if p.is_file() and p.suffix.lower() not in _SUPPORTED_EXTS]
        if unreadable:
            logger.info("refs: skipping files in no readable format %s",
                        [p.name for p in unreadable])
        if main_doc.suffix.lower() in _TEXT_EXTS:
            originals = [p for p in readable if p.suffix.lower() in _BINARY_EXTS]
            if originals:
                logger.info(
                    "refs: %s is read from text, so its unconverted originals "
                    "stay unread: %s",
                    main_doc.name, [p.name for p in originals],
                )
            return [p for p in readable if p.suffix.lower() in _TEXT_EXTS]
        return prefer_text(readable)

    @staticmethod
    def _resolve_annotations_dir(root: Path) -> Path | None:
        """Locate the shared, version-level ``annotations/`` directory.

        There is exactly one per version, sub-agnostic; returns None when the
        bundle has none. A single-file ``annotations.yaml`` is rejected with a
        migration hint rather than silently ignored.
        """
        ann_dir = root / _ANNOTATIONS_DIRNAME
        if ann_dir.is_dir():
            return ann_dir
        for legacy in _LEGACY_ANNOTATION_FILENAMES:
            if (root / legacy).exists():
                raise RuntimeError(
                    f"ProtocolSource: {root}/{legacy} is a legacy v3 "
                    f"single-file annotation. v4 expects a shared "
                    f"`{_ANNOTATIONS_DIRNAME}/` directory with "
                    f"subprotocols.yaml / tags.yaml / references.yaml. "
                    f"Run the VerdictBench split migration."
                )
        return None

    @staticmethod
    def _resolve_subprotocol(
        root: Path, target_name: str | None
    ) -> tuple[Path, str | None]:
        """Resolve the per-sub artifact root under ``subprotocols/``.

        Returns ``(artifact_root, resolved_sub)``. Without ``subprotocols/``
        the protocol is single: artifacts live at ``root``, the resolved sub
        is None and ``target_name`` must be None too.
        """
        resolved = resolve_subprotocol_name(root, target_name)
        return ((root / "subprotocols" / resolved, resolved)
                if resolved is not None else (root, None))

    @staticmethod
    def _read_subprotocol_md(sub_dir: Path) -> str | None:
        """Read ``subprotocols/<sub>/subprotocol.md`` with frontmatter stripped.

        The body names the sub-protocol and its characteristics and is
        injected into every extraction node's prompt, so extraction only
        recognises that sub-protocol. Returns None when the file is absent or
        its body is empty.
        """
        md = sub_dir / "subprotocol.md"
        if not md.is_file():
            return None
        text = md.read_text(encoding="utf-8")
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end != -1:
                text = text[end + 4:]
        body = text.strip()
        return body or None


# What the CLI and the front end may hand over as a protocol input.
SourceLike = "ProtocolSource | Path | str"


def coerce_source(source, target_name: str | None = None) -> "ProtocolSource":
    """Normalise a SourceLike into one concrete ProtocolSource.

    Paths are discovered against the VerdictBench layout by
    :meth:`ProtocolSource.from_directory`; ``target_name`` is meaningful only
    when ``source`` is a path. Any other type raises RuntimeError.
    """
    if isinstance(source, ProtocolSource):
        if target_name is not None:
            raise RuntimeError(
                "`target_name` is only meaningful when `source` is a path; "
                "a ProtocolSource has already been constructed."
            )
        return source
    if isinstance(source, str):
        source = Path(source)
    if isinstance(source, Path):
        return ProtocolSource.from_directory(source, target_name=target_name)
    raise RuntimeError(
        f"`source` must be a ProtocolSource, a Path, or a str path, got "
        f"{type(source).__name__}"
    )



class DocumentLoaderService:
    """Stateless orchestrator turning a ProtocolSource into a DocumentSet."""

    async def load(self, source: ProtocolSource) -> DocumentSet:
        doc_set = await self._load_documents(source)
        # The description travels with the doc_set; get_*_content injects it
        # ahead of the extraction prompt.
        doc_set.subprotocol_note = source.sub_description or ""
        # get_*_content scopes sections by the active sub, so each sub-protocol
        # extracts only the flow that belongs to it (per subprotocols.yaml).
        # Sections with no declared owner are shared background. A single-sub
        # protocol has None here and nothing is filtered.
        doc_set.active_sub = source.sub
        overlay = apply_annotations(doc_set, source.annotations)
        # Sub-protocol isolation is structural: the other subs' sections are
        # physically cut here, so no later view (toc / get_section / grep) can
        # reach their text. A sub with no declaration makes prune_to_sub fail.
        if source.sub:
            doc_set.prune_to_sub(source.sub)
        logger.info(
            "Document set loaded: main='%s', docs=%s%s",
            doc_set.main_doc_id,
            list(doc_set.documents),
            ""
            if overlay.is_empty()
            else f" (annotated; subs={overlay.subprotocols() or '<single>'})",
        )
        return doc_set

    @staticmethod
    async def _load_documents(source: ProtocolSource) -> DocumentSet:
        all_docs = source.all_docs()
        ids = [p.stem for p in all_docs]
        if len(ids) != len(set(ids)):
            raise RuntimeError(
                f"Duplicate doc_id (filename stem) in ProtocolSource: {ids}"
            )

        doc_set = DocumentSet(main_doc_id=source.main_doc.stem)
        for path in all_docs:
            if not path.exists():
                raise RuntimeError(f"Source file not found: {path}")
            if not path.is_file():
                raise RuntimeError(f"Source path is not a file: {path}")
            fmt = infer_protocol_format(path)
            loader = make_document_loader(fmt)
            tree = await loader.load(path)
            doc_set.add(Document(
                doc_id=path.stem,
                protocol_format=fmt,
                source_path=path,
                sections=tree,
            ))
            logger.info("Loaded doc '%s' (format=%s)", path.stem, fmt)
        return doc_set
