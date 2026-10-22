"""The binary document formats: what the file is, and what comes out of it.

PDF, DOCX and DOC all end in the Markdown pipeline, so these tests check the
two things that are theirs alone — the format is read off the content, and the
source's structure survives the trip to a SectionTree. The PDF and DOCX
fixtures are written byte by byte here rather than committed, so what they
exercise is visible in the test.
"""

from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path

import pytest

from orrery.modules.document import DocumentLoaderService, ProtocolSource
from orrery.modules.document.parsing import (
    infer_protocol_format,
    make_document_loader,
    sniff_binary_format,
)
from orrery.modules.document.parsing.doc.extractor import _to_text
from orrery.modules.document.parsing.headings import (
    HeadingSequence,
    mark_numbered_headings,
    split_numbered,
)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


# ── fixtures written by hand ─────────────────────────────────────────────────


def _pdf(page_lines: list[list[tuple[str, float, bool, float]]]) -> bytes:
    """A PDF of ``(text, y, bold, size)`` lines, one list per page.

    Uncompressed content streams and the two base-14 Helvetica faces, so
    pdfminer reports the font name this loader keys "bold" off.
    """
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")  # placeholder, rewritten below
    pages = add(b"")
    page_ids, content_ids = [], []
    for lines in page_lines:
        stream = b"\n".join(
            f"BT /{'F2' if bold else 'F1'} {size} Tf 72 {y} Td "
            f"({text}) Tj ET".encode("latin-1")
            for text, y, bold, size in lines
        )
        content_ids.append(add(
            b"<</Length %d>>stream\n" % len(stream) + stream + b"\nendstream"
        ))
        page_ids.append(add(b""))
    regular = add(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>")
    bold_font = add(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica-Bold>>")

    objects[catalog - 1] = b"<</Type/Catalog/Pages %d 0 R>>" % pages
    objects[pages - 1] = (
        b"<</Type/Pages/Count %d/Kids[" % len(page_ids)
        + b" ".join(b"%d 0 R" % i for i in page_ids)
        + b"]>>"
    )
    for page_id, content_id in zip(page_ids, content_ids):
        objects[page_id - 1] = (
            b"<</Type/Page/Parent %d 0 R/MediaBox[0 0 612 792]"
            b"/Resources<</Font<</F1 %d 0 R/F2 %d 0 R>>>>/Contents %d 0 R>>"
            % (pages, regular, bold_font, content_id)
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += (
        b"trailer<</Size %d/Root %d 0 R>>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, catalog, xref)
    )
    return bytes(out)


def _docx(body: str, *, styles: str = "", core: str = "") -> bytes:
    """A .docx holding ``body`` as the children of ``w:body``."""
    import io

    heading_styles = "".join(
        f'<w:style w:type="paragraph" w:styleId="Heading{n}">'
        f'<w:name w:val="heading {n}"/></w:style>'
        for n in range(1, 10)
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr(
            "word/document.xml",
            f'<?xml version="1.0"?><w:document xmlns:w="{W}">'
            f"<w:body>{body}</w:body></w:document>",
        )
        zf.writestr(
            "word/styles.xml",
            f'<?xml version="1.0"?><w:styles xmlns:w="{W}">'
            f"{heading_styles}{styles}</w:styles>",
        )
        if core:
            zf.writestr("docProps/core.xml", core)
    return buffer.getvalue()


def _para(text: str, style: str | None = None) -> str:
    pPr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{pPr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def _load(path: Path):
    return asyncio.run(make_document_loader(infer_protocol_format(path)).load(path))


# ── what the file is ─────────────────────────────────────────────────────────


def test_content_decides_the_format_not_the_extension(tmp_path):
    pdf = tmp_path / "looks-like-text.txt"
    pdf.write_bytes(_pdf([[("1 Scope", 700, True, 14)]]))
    assert sniff_binary_format(pdf) == "pdf"
    assert infer_protocol_format(pdf) == "pdf"

    docx = tmp_path / "looks-legacy.doc"
    docx.write_bytes(_docx(_para("1 Scope", "Heading1")))
    assert infer_protocol_format(docx) == "docx"


def test_plain_text_keeps_the_extension_convention(tmp_path):
    md = tmp_path / "spec.md"
    md.write_text("# Title\n\n## 1 Scope\n\nText.\n")
    assert sniff_binary_format(md) is None
    assert infer_protocol_format(md) == "markdown"
    txt = tmp_path / "rfc.txt"
    txt.write_text("1.  Introduction\n\n   Text.\n")
    assert infer_protocol_format(txt) == "rfc_txt"


def test_a_binary_extension_over_plain_text_is_an_error(tmp_path):
    fake = tmp_path / "spec.pdf"
    fake.write_text("not a pdf at all\n")
    with pytest.raises(RuntimeError, match="content is plain text"):
        infer_protocol_format(fake)


def test_a_container_we_cannot_read_is_named(tmp_path):
    rtf = tmp_path / "spec.doc"
    rtf.write_bytes(rb"{\rtf1\ansi hello}")
    with pytest.raises(RuntimeError, match="RTF"):
        sniff_binary_format(rtf)

    xlsx = tmp_path / "book.docx"
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("xl/workbook.xml", "<workbook/>")
    xlsx.write_bytes(buffer.getvalue())
    with pytest.raises(RuntimeError, match="XLSX"):
        sniff_binary_format(xlsx)


# ── PDF ──────────────────────────────────────────────────────────────────────


def test_pdf_sections_come_from_emphasis_and_numbering(tmp_path):
    body = [("Body text that sets the dominant font size here.", y, False, 12)
            for y in (680, 660, 640)]
    path = tmp_path / "spec.pdf"
    path.write_bytes(_pdf([[
        ("1 Scope", 700, True, 14),
        *body,
        ("2 Protocol", 600, True, 14),
        ("2.1 Overview", 580, True, 12),
        ("A sends B a nonce.", 560, False, 12),
        ("1. A numbered list item, not a section.", 540, False, 12),
        ("Annex A", 500, True, 14),
        ("Test vectors", 480, True, 14),
    ]]))
    tree = _load(path)
    assert [s.number for s in tree.top_level] == ["1", "2", "A"]
    assert [s.number for s in tree.top_level[1].children] == ["2.1"]
    assert tree.top_level[2].title.startswith("Annex A")
    # The list item stayed inside 2.1 rather than opening a clause 1.
    text = " ".join(b.text for b in tree.top_level[1].children[0].blocks)
    assert "numbered list item" in text


def test_pdf_with_no_text_layer_says_so(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(_pdf([[]]))
    with pytest.raises(RuntimeError, match="no extractable text"):
        _load(path)


# ── DOCX ─────────────────────────────────────────────────────────────────────


def test_docx_outline_comes_from_the_heading_styles(tmp_path):
    path = tmp_path / "spec.docx"
    path.write_bytes(_docx(
        _para("1\tScope", "Heading1")
        + _para("This clause defines the scope.")
        + _para("2\tProtocol", "Heading1")
        + _para("2.1\tOverview", "Heading2")
        + _para("A sends B a nonce.")
        + _para("1.2 Overview .......... 4", "TOC1"),
        styles='<w:style w:type="paragraph" w:styleId="TOC1">'
               '<w:name w:val="toc 1"/></w:style>',
        core='<?xml version="1.0"?><cp:coreProperties '
             'xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
             'metadata/core-properties" '
             'xmlns:dc="http://purl.org/dc/elements/1.1/">'
             "<dc:title>Foobar Protocol</dc:title></cp:coreProperties>",
    ))
    tree = _load(path)
    assert tree.doc_title == "Foobar Protocol"
    assert [s.number for s in tree.top_level] == ["1", "2"]
    assert [s.number for s in tree.top_level[1].children] == ["2.1"]
    # The contents entry was dropped, not carried in as body text.
    everything = " ".join(
        b.text for s in tree.walk() for b in s.blocks if hasattr(b, "text")
    )
    assert ".........." not in everything
    assert "A sends B a nonce." in everything


def test_docx_tables_become_markdown_tables(tmp_path):
    row = ("<w:tr><w:tc><w:p><w:r><w:t>Field</w:t></w:r></w:p></w:tc>"
           "<w:tc><w:p><w:r><w:t>Length</w:t></w:r></w:p></w:tc></w:tr>"
           "<w:tr><w:tc><w:p><w:r><w:t>Nonce</w:t></w:r></w:p></w:tc>"
           "<w:tc><w:p><w:r><w:t>16</w:t></w:r></w:p></w:tc></w:tr>")
    path = tmp_path / "spec.docx"
    path.write_bytes(_docx(
        _para("1\tScope", "Heading1") + f"<w:tbl>{row}</w:tbl>"
    ))
    tree = _load(path)
    tables = [b for b in tree.top_level[0].blocks if hasattr(b, "raw_markdown")]
    assert len(tables) == 1
    assert "| Field | Length |" in tables[0].raw_markdown
    assert "| Nonce | 16 |" in tables[0].raw_markdown


def test_docx_without_heading_styles_fails_loudly(tmp_path):
    path = tmp_path / "flat.docx"
    path.write_bytes(_docx(_para("1 Scope") + _para("Just body text.")))
    with pytest.raises(RuntimeError, match="heading style"):
        _load(path)


# ── DOC (the parts that do not need a binary fixture) ────────────────────────


def test_doc_control_characters_become_line_structure():
    """Paragraph marks end lines, a cell mark separates cells and a doubled one
    ends the row, and a TOC field takes its own result with it."""
    toc_field = "\x13" + r' TOC \o "1-3" ' + "\x14" + "6.1 Something\t12" + "\x15"
    page_ref = "\x13 PAGEREF _x \x14" + "17" + "\x15"
    raw = "1 Scope\rBody.\ra\x07b\x07\x07" + toc_field + page_ref + "\r"
    assert _to_text(raw).split("\n") == ["1 Scope", "Body.", "a\tb", "17"]


def test_doc_headings_are_recovered_from_clause_numbers():
    lines = [
        "1 Scope",
        "Body text.",
        "2 Protocol",
        "2.1 Overview",
        "1. A numbered list item.",
        "2. Another list item.",
        "2.2 Flow",
    ]
    marked = mark_numbered_headings(lines, "test")
    assert marked[0] == "## 1 Scope"
    assert marked[3] == "### 2.1 Overview"
    assert marked[4] == "1. A numbered list item."
    assert marked[6] == "### 2.2 Flow"


# ── the successor rule ───────────────────────────────────────────────────────


@pytest.mark.parametrize("numbers,expected", [
    (["1", "2", "2.1", "2.2", "2.2.1", "3"], [True] * 6),
    (["1", "3"], [True, False]),          # a skipped sibling
    (["1", "1.2"], [True, False]),        # a first child must start at 0 or 1
    (["2"], [False]),                     # a document has to open at 0 or 1
    (["1", "A", "A.1", "B", "1"], [True, True, True, True, False]),
    (["1", "B"], [True, False]),          # annexes open at A
])
def test_heading_sequence(numbers, expected):
    sequence = HeadingSequence()
    assert [sequence.accept(n, n) for n in numbers] == expected


def test_split_numbered_ignores_a_lone_capital():
    assert split_numbered("U to party V") is None
    assert split_numbered("3.1 Definitions") == ("3.1", "Definitions")
    assert split_numbered("Annex A (informative) Vectors")[0] == "A"
    assert split_numbered("1 " + "x" * 200) is None


# ── the format a bundle is read in ───────────────────────────────────────────


def _bundle(root: Path, main: dict[str, bytes], refs: dict[str, bytes]) -> Path:
    for sub, files in (("main", main), ("refs", refs)):
        d = root / "source" / sub
        d.mkdir(parents=True)
        for name, data in files.items():
            (d / name).write_bytes(data)
    return root


def _md(title: str) -> bytes:
    return f"# {title}\n\n## 1 Scope\n\nText of {title}.\n".encode()


def test_a_markdown_bundle_never_reads_the_originals_beside_it(tmp_path):
    """The corpus keeps the authoritative PDF next to the copy it is read from.

    A unit that reads as Markdown today has to read the same tomorrow, so the
    subject document decides for the whole bundle: no PDF in it is opened, with
    or without a Markdown twin.
    """
    root = _bundle(
        tmp_path / "iso",
        main={"spec.md": _md("Spec"), "spec.pdf": _pdf([[("1 Scope", 700, True, 14)]])},
        refs={"ref.md": _md("Ref"),
              "other.pdf": _pdf([[("1 Scope", 700, True, 14)]])},
    )
    source = ProtocolSource.from_directory(root)
    assert source.main_doc.name == "spec.md"
    assert [p.name for p in source.ref_docs] == ["ref.md"]
    doc_set = asyncio.run(DocumentLoaderService().load(source))
    assert sorted(doc_set.documents) == ["ref", "spec"]


def test_a_bundle_with_only_an_original_is_read_from_it(tmp_path):
    root = _bundle(
        tmp_path / "nist",
        main={"spec.pdf": _pdf([[("1 Scope", 700, True, 14),
                                 ("Body text for the size.", 680, False, 12)]])},
        refs={"ref.pdf": _pdf([[("1 Scope", 700, True, 14),
                                ("Body text for the size.", 680, False, 12)]])},
    )
    source = ProtocolSource.from_directory(root)
    assert source.main_doc.name == "spec.pdf"
    assert [p.name for p in source.ref_docs] == ["ref.pdf"]
