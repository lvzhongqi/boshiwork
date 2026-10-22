"""Factory: build a DocumentLoader, and decide which one a file needs.

Five formats: Markdown, RFC plain text, PDF, Word ``.docx`` and Word ``.doc``.
The three binary ones are identified by their content (``parsing/sniff.py``),
so a mislabelled file is read correctly and a ``.docx`` that is really a
spreadsheet is refused by name instead of failing deep inside a parser. Only
the two text formats are decided by extension, because nothing in a plain text
file says whether it is Markdown or an RFC.
"""
from __future__ import annotations

import logging
from pathlib import Path

from orrery.modules.document.parsing.base import DocumentLoader
from orrery.modules.document.parsing.sniff import sniff_binary_format

logger = logging.getLogger(__name__)

#: Extension → format, for the formats an extension can settle. The binary
#: entries are here to be *checked* against the content, not to decide.
_TEXT_FORMATS = {".md": "markdown", ".markdown": "markdown", ".txt": "rfc_txt"}
_BINARY_FORMATS = {".pdf": "pdf", ".docx": "docx", ".doc": "doc"}


def make_document_loader(protocol_format: str) -> DocumentLoader:
    fmt = protocol_format.strip().lower()
    if fmt == "markdown":
        from orrery.modules.document.parsing.markdown import MarkdownLoader

        return MarkdownLoader()
    if fmt == "rfc_txt":
        from orrery.modules.document.parsing.rfc_txt import RFCTxtLoader

        return RFCTxtLoader()
    if fmt == "pdf":
        from orrery.modules.document.parsing.pdf import PDFLoader

        return PDFLoader()
    if fmt == "docx":
        from orrery.modules.document.parsing.docx import DocxLoader

        return DocxLoader()
    if fmt == "doc":
        from orrery.modules.document.parsing.doc import DocLoader

        return DocLoader()
    raise RuntimeError(f"Unknown protocol_format: {protocol_format!r}")


def infer_protocol_format(path: Path) -> str:
    """Which loader reads this file: content first, extension second.

    PDF, DOCX and DOC each carry a signature, so the content decides and a
    disagreement with the extension is only logged. Plain text carries nothing,
    so ``.md``/``.markdown`` → markdown and ``.txt`` → rfc_txt stay corpus
    conventions, warned about on every call and enforced inside the loader. A
    file with a binary extension whose content is text is an error: it is not
    the document it claims to be.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    sniffed = sniff_binary_format(path)

    if sniffed is not None:
        expected = _BINARY_FORMATS.get(suffix)
        if expected is None:
            logger.warning(
                "Reading %s as %s: the extension %r says otherwise, but the "
                "file's content does not.",
                path, sniffed.upper(), suffix,
            )
        elif expected != sniffed:
            logger.warning(
                "Reading %s as %s, not %s: the extension and the file's "
                "content disagree, and the content wins.",
                path, sniffed.upper(), expected.upper(),
            )
        return sniffed

    if suffix in _BINARY_FORMATS:
        what = "is empty" if path.stat().st_size == 0 else "is plain text"
        raise RuntimeError(
            f"{path} has a {suffix} extension but its content {what}, not "
            f"{_BINARY_FORMATS[suffix].upper()}. Rename it to .md or .txt if "
            f"that is what it is."
        )
    if suffix in (".md", ".markdown"):
        logger.warning(
            "Treating %s as generic Markdown (.md/.markdown → markdown is a "
            "convention; the file must follow our Markdown conventions "
            "— numbered ATX headings, standard tables — otherwise the parser "
            "will fail).",
            path,
        )
        return "markdown"
    if suffix == ".txt":
        logger.warning(
            "Treating %s as RFC plain text (.txt → rfc_txt is a convention; "
            "the file must be an RFC or Internet-Draft, otherwise the loader "
            "will fail).",
            path,
        )
        return "rfc_txt"
    raise RuntimeError(
        f"Cannot infer protocol_format from path {str(path)!r} "
        f"(extension {suffix!r} unrecognized, and the content is not PDF, "
        f"DOCX or DOC)"
    )
