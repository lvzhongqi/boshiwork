"""Content sniffing: what a file actually is, regardless of what it is called.

The extension is a convention; the first bytes are a fact. Every binary
container this package reads carries a signature — ``%PDF-`` for PDF, the ZIP
local-file header for DOCX, the OLE compound-file signature for legacy DOC —
so the format is read off the content and the extension only settles the plain
text case, where there is nothing to sniff.

A container we recognize but cannot analyse (an XLSX, an RTF that someone named
``.doc``) is named in the error rather than left to fail deep inside a parser.
"""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

# PDF files may carry junk before the header; the spec lets the header sit
# anywhere in the first 1024 bytes.
_PDF_MAGIC = b"%PDF-"
_PDF_SEARCH_WINDOW = 1024
# ZIP local file header. Empty and spanned archives use different signatures,
# neither of which a real Office document has.
_ZIP_MAGIC = b"PK\x03\x04"
# OLE2 / Compound File Binary, the container of every pre-2007 Office file.
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_RTF_MAGIC = b"{\\rt"

#: Entry inside the OOXML package that identifies the application.
_OOXML_PARTS = {
    "word/document.xml": "docx",
    "ppt/presentation.xml": "pptx",
    "xl/workbook.xml": "xlsx",
}

#: Stream inside the OLE2 directory that identifies the application.
_OLE_STREAMS = {
    "WordDocument": "doc",
    "Workbook": "xls",
    "Book": "xls",
    "PowerPoint Document": "ppt",
}

#: What this package can parse. Anything else recognized here is reported by
#: name so the caller knows what they handed over.
_ANALYSABLE = {"pdf", "docx", "doc"}


def sniff_binary_format(path: Path) -> str | None:
    """The binary document format of ``path``, or None when it is plain text.

    Returns ``"pdf"``, ``"docx"`` or ``"doc"``. Raises RuntimeError for a
    binary container this package recognizes but cannot analyse (XLSX, PPT,
    RTF), naming what it found.
    """
    path = Path(path)
    with path.open("rb") as fh:
        head = fh.read(_PDF_SEARCH_WINDOW)
    if not head:
        # Not a format question. The text route treated an empty file as empty
        # Markdown before there was a sniffer, and still does; a binary
        # extension over an empty file is caught by the caller.
        return None

    offset = head.find(_PDF_MAGIC)
    if offset == 0:
        return "pdf"
    if offset > 0 and not _looks_like_text(head):
        # Some PDFs carry junk ahead of the header. A Markdown file that merely
        # writes "%PDF-" in a sentence is text and stays text.
        logger.warning("%s: PDF header at byte %d; reading it as PDF", path, offset)
        return "pdf"
    if head.startswith(_ZIP_MAGIC):
        return _sniff_ooxml(path)
    if head.startswith(_OLE_MAGIC):
        return _sniff_ole(path)
    if head.lstrip().startswith(_RTF_MAGIC):
        raise RuntimeError(
            f"{path} is an RTF document (it starts with '{{\\rtf'), not a Word "
            f"binary. Save it as .docx and try again."
        )
    return None


def _looks_like_text(head: bytes) -> bool:
    """Whether these opening bytes could be a text document."""
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        # The read window can cut a multi-byte character in half; that alone
        # does not make the file binary.
        try:
            head[:-4].decode("utf-8")
        except UnicodeDecodeError:
            return False
    return True


def _sniff_ooxml(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
    except zipfile.BadZipFile as exc:
        raise RuntimeError(
            f"{path} starts with a ZIP signature but is not a readable "
            f"archive: {exc}"
        ) from exc
    for part, fmt in _OOXML_PARTS.items():
        if part in names:
            if fmt not in _ANALYSABLE:
                raise RuntimeError(
                    f"{path} is an Office {fmt.upper()} package, which this "
                    f"pipeline does not read; it reads Word documents, PDF, "
                    f"Markdown and RFC plain text."
                )
            return fmt
    raise RuntimeError(
        f"{path} is a ZIP archive with no Office main part "
        f"(looked for {sorted(_OOXML_PARTS)}); it is not a .docx."
    )


def _sniff_ole(path: Path) -> str:
    # Imported here so the sniffer stays usable when only Markdown and RFC
    # text are in play — the OLE reader is only ever needed for a legacy .doc.
    from orrery.modules.document.parsing.doc.olecf import CompoundFile

    with path.open("rb") as fh:
        entries = CompoundFile(fh.read()).entry_names()
    for stream, fmt in _OLE_STREAMS.items():
        if stream in entries:
            if fmt not in _ANALYSABLE:
                raise RuntimeError(
                    f"{path} is a legacy Office {fmt.upper()} file, which this "
                    f"pipeline does not read; it reads Word documents, PDF, "
                    f"Markdown and RFC plain text."
                )
            return fmt
    raise RuntimeError(
        f"{path} is an OLE compound file with no recognized main stream "
        f"(found {sorted(entries)[:10]}); it is not a Word .doc."
    )


__all__ = ["sniff_binary_format"]
