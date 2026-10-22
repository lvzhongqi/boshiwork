"""DOCX (Office Open XML) → Markdown.

A ``.docx`` is a ZIP of XML parts. ``word/styles.xml`` says which paragraph
styles are headings and at what outline level, ``word/document.xml`` holds the
body in reading order, and ``word/_rels/document.xml.rels`` resolves the
pictures. That is everything needed to render the document as Markdown, so the
structural rules stay in one place — the Markdown pipeline — instead of being
reimplemented per format.

Three things are deliberately dropped: field *instructions* (a ``PAGEREF`` code
is not prose), paragraphs in a table-of-contents style (they replay every
heading), and tracked deletions. Textbox content is kept, but as its own lines
after the paragraph that anchors it, so a figure's labels do not run into the
surrounding sentence.

Word's own automatic heading numbers are *not* resolved: they live in
``numbering.xml`` as a counter machine, not as text. A document that relies on
them is reported, and the Markdown normalizer numbers its clauses by position.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
VML = "{urn:schemas-microsoft-com:vml}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
DC = "{http://purl.org/dc/elements/1.1/}"

_DOCUMENT_PART = "word/document.xml"
_STYLES_PART = "word/styles.xml"
_RELS_PART = "word/_rels/document.xml.rels"
_CORE_PART = "docProps/core.xml"

_HEADING_NAME = re.compile(r"^heading\s*([1-9])$")
_HEADING_ID = re.compile(r"^(?:heading|h)\s*([1-9])$", re.IGNORECASE)
_TOC_NAME = re.compile(r"^(?:toc\s*\d+|table of (?:contents|figures)|index\s*\d+)$")
_TOC_ID = re.compile(r"^(?:TOC|TableofFigures|Index)\d*$", re.IGNORECASE)
_NUMBER_START = re.compile(r"^(?:\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)[.\s]")
#: Field instructions whose result is dropped along with the instruction.
_SUPPRESSED_FIELDS = ("TOC", "INDEX")

#: Run-level elements that carry no body text.
_SKIPPED = frozenset({
    W + "instrText", W + "delText", W + "delInstrText",
    W + "proofErr", W + "bookmarkStart", W + "bookmarkEnd",
    W + "softHyphen", W + "lastRenderedPageBreak", W + "rPr", W + "pPr",
    W + "sectPr", W + "tblPr", W + "tcPr", W + "trPr", W + "commentRangeStart",
    W + "commentRangeEnd", W + "commentReference", W + "footnoteRef",
    W + "endnoteRef",
})


def extract_markdown(source_path: Path) -> str:
    """Render a ``.docx`` as Markdown for the Markdown pipeline."""
    source_path = Path(source_path)
    with zipfile.ZipFile(source_path) as zf:
        names = set(zf.namelist())
        if _DOCUMENT_PART not in names:
            raise RuntimeError(
                f"{source_path}: not a Word package — no {_DOCUMENT_PART}"
            )
        document = ET.fromstring(zf.read(_DOCUMENT_PART))
        styles = ET.fromstring(zf.read(_STYLES_PART)) if _STYLES_PART in names else None
        rels = ET.fromstring(zf.read(_RELS_PART)) if _RELS_PART in names else None
        core = ET.fromstring(zf.read(_CORE_PART)) if _CORE_PART in names else None

    levels, toc_styles = _style_roles(styles)
    if not levels:
        raise RuntimeError(
            f"{source_path}: no heading styles in {_STYLES_PART}; the document "
            f"has no outline this loader can read"
        )
    images = _image_targets(rels)

    body = document.find(W + "body")
    if body is None:
        raise RuntimeError(f"{source_path}: {_DOCUMENT_PART} has no <w:body>")

    renderer = _Renderer(levels, toc_styles, images)
    lines = renderer.render(body)
    title = _document_title(core)
    if title:
        lines = [f"# {title}", ""] + lines
    logger.info(
        "DOCX extractor: %d headings, %d tables, %d images, %d body lines",
        renderer.headings, renderer.tables, renderer.images_emitted, len(lines),
    )
    if renderer.auto_numbered_headings:
        logger.warning(
            "%s: %d headings are numbered by Word itself, not in their text; "
            "their clause numbers are assigned by position and may differ from "
            "the printed document.",
            source_path, renderer.auto_numbered_headings,
        )
    if renderer.headings == 0:
        raise RuntimeError(
            f"{source_path}: no paragraph uses a heading style, so the document "
            f"has no sections. Apply Word's Heading 1..9 styles, or convert to "
            f"Markdown by hand."
        )
    return "\n".join(lines)


def _style_roles(styles: ET.Element | None) -> tuple[dict[str, int], set[str]]:
    """``(styleId → heading level, table-of-contents styleIds)``.

    A style is a heading when Word's built-in name says so, when its id looks
    like one, or when it declares an outline level; ``w:basedOn`` carries all
    three down to derived styles.
    """
    if styles is None:
        return {}, set()
    levels: dict[str, int] = {}
    toc: set[str] = set()
    based_on: dict[str, str] = {}

    for style in styles.findall(W + "style"):
        style_type = style.get(W + "type")
        if style_type not in (None, "paragraph"):
            continue
        sid = style.get(W + "styleId")
        if not sid:
            continue
        name_el = style.find(W + "name")
        name = (name_el.get(W + "val") or "").strip().lower() if name_el is not None else ""
        parent = style.find(W + "basedOn")
        if parent is not None and parent.get(W + "val"):
            based_on[sid] = parent.get(W + "val")

        if _TOC_NAME.match(name) or _TOC_ID.match(sid):
            toc.add(sid)
            continue

        m = _HEADING_NAME.match(name) or _HEADING_ID.match(sid)
        if m:
            levels[sid] = int(m.group(1))
            continue
        outline = style.find(W + "pPr/" + W + "outlineLvl")
        if outline is not None:
            val = outline.get(W + "val")
            if val is not None and val.isdigit() and 0 <= int(val) <= 8:
                levels[sid] = int(val) + 1

    # A custom style based on Heading 2 is a level-2 heading; walk the chain
    # until it stops adding anything.
    for _ in range(len(based_on) + 1):
        changed = False
        for sid, parent in based_on.items():
            if sid in levels or sid in toc:
                continue
            if parent in levels:
                levels[sid] = levels[parent]
                changed = True
            elif parent in toc:
                toc.add(sid)
                changed = True
        if not changed:
            break
    return levels, toc


def _image_targets(rels: ET.Element | None) -> dict[str, str]:
    if rels is None:
        return {}
    out: dict[str, str] = {}
    for rel in rels.findall(PKG_REL + "Relationship"):
        rid, target = rel.get("Id"), rel.get("Target")
        if rid and target:
            out[rid] = target
    return out


def _document_title(core: ET.Element | None) -> str:
    """The package title, when it can serve as the document's ``#`` line.

    A numbered title would collide with the first clause, so it is left out.
    """
    if core is None:
        return ""
    el = core.find(DC + "title")
    title = " ".join((el.text or "").split()) if el is not None else ""
    if not title or _NUMBER_START.match(title):
        return ""
    return title


class _Renderer:
    """Body XML → Markdown lines."""

    def __init__(
        self,
        levels: dict[str, int],
        toc_styles: set[str],
        images: dict[str, str],
    ) -> None:
        self._levels = levels
        self._toc = toc_styles
        self._images = images
        self.headings = 0
        self.tables = 0
        self.images_emitted = 0
        self.auto_numbered_headings = 0

    def render(self, container: ET.Element) -> list[str]:
        lines: list[str] = []
        for child in container:
            tag = child.tag
            if tag == W + "p":
                lines.extend(self._paragraph(child))
            elif tag == W + "tbl":
                lines.extend(self._table(child))
            elif tag == W + "sdt":
                content = child.find(W + "sdtContent")
                if content is not None:
                    lines.extend(self.render(content))
        return lines

    # -- paragraphs --------------------------------------------------------

    def _paragraph(self, p: ET.Element) -> list[str]:
        style = _paragraph_style(p)
        if style in self._toc:
            return []
        text, boxed = _paragraph_text(p)
        pictures = self._pictures(p)
        level = self._levels.get(style) if style else None

        out: list[str] = []
        if level is not None:
            heading = " ".join(text.split())
            if not heading:
                return []
            if not _NUMBER_START.match(heading) and _has_numbering(p):
                self.auto_numbered_headings += 1
            self.headings += 1
            out += ["", "#" * (level + 1) + " " + heading, ""]
        elif text.strip():
            body = text if not _has_numbering(p) else "- " + text.lstrip()
            out += [line.rstrip() for line in body.split("\n")]
        for caption, target in pictures:
            self.images_emitted += 1
            out += ["", f"![{caption}]({target})", ""]
        if boxed:
            out += ["", *(line for line in boxed if line), ""]
        return out

    def _pictures(self, p: ET.Element) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        captions = [
            (el.get("descr") or el.get("name") or "").strip()
            for el in p.iter(WP + "docPr")
        ]
        rids = [el.get(R + "embed") for el in p.iter(A + "blip")]
        rids += [el.get(R + "id") for el in p.iter(VML + "imagedata")]
        for i, rid in enumerate([r for r in rids if r]):
            target = self._images.get(rid)
            if not target:
                continue
            caption = captions[i] if i < len(captions) else ""
            found.append((_safe_caption(caption), target))
        return found

    # -- tables ------------------------------------------------------------

    def _table(self, tbl: ET.Element) -> list[str]:
        rows: list[list[str]] = []
        for tr in tbl.findall(W + "tr"):
            cells = []
            for tc in tr.findall(W + "tc"):
                parts = [
                    " ".join(_paragraph_text(p)[0].split())
                    for p in tc.iter(W + "p")
                ]
                cells.append(" ".join(x for x in parts if x).replace("|", r"\|"))
            if cells:
                rows.append(cells)
        if not rows:
            return []
        self.tables += 1
        width = max(len(r) for r in rows)
        rendered = ["| " + " | ".join(r + [""] * (width - len(r))) + " |" for r in rows]
        separator = "| " + " | ".join(["---"] * width) + " |"
        return ["", rendered[0], separator, *rendered[1:], ""]


def _paragraph_style(p: ET.Element) -> str | None:
    style = p.find(W + "pPr/" + W + "pStyle")
    return style.get(W + "val") if style is not None else None


def _has_numbering(p: ET.Element) -> bool:
    return p.find(W + "pPr/" + W + "numPr") is not None


def _paragraph_text(p: ET.Element) -> tuple[str, list[str]]:
    """``(inline text, textbox lines)`` for one paragraph.

    Textbox paragraphs are pulled out rather than spliced in: a figure's labels
    belong on their own lines, not in the middle of the sentence that anchors
    the drawing.
    """
    parts: list[str] = []
    boxed: list[str] = []
    _collect(p, parts, boxed)
    return "".join(parts), boxed


def _collect(node: ET.Element, parts: list[str], boxed: list[str]) -> None:
    for child in node:
        tag = child.tag
        if tag in _SKIPPED:
            continue
        if tag == W + "t":
            parts.append(child.text or "")
        elif tag == W + "tab":
            parts.append(" ")
        elif tag in (W + "br", W + "cr"):
            parts.append("\n")
        elif tag == W + "noBreakHyphen":
            parts.append("-")
        elif tag == W + "txbxContent":
            for para in child.iter(W + "p"):
                inner: list[str] = []
                _collect(para, inner, boxed)
                line = " ".join("".join(inner).split())
                if line:
                    boxed.append(line)
        elif tag == W + "fldSimple":
            instruction = (child.get(W + "instr") or "").strip().upper()
            if not any(instruction.startswith(f) for f in _SUPPRESSED_FIELDS):
                _collect(child, parts, boxed)
        elif tag == MC + "AlternateContent":
            # Choice and Fallback hold the same content; rendering both would
            # duplicate every textbox.
            branch = child.find(MC + "Choice")
            if branch is None:
                branch = child.find(MC + "Fallback")
            if branch is not None:
                _collect(branch, parts, boxed)
        else:
            _collect(child, parts, boxed)


def _safe_caption(caption: str) -> str:
    return " ".join(caption.replace("]", " ").replace("[", " ").split())


__all__ = ["extract_markdown"]
