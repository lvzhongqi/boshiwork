"""Legacy Word binary (``.doc``) → plain text.

The text of a ``.doc`` is not stored in one place: the FIB in the
``WordDocument`` stream points at a piece table in the table stream, and each
piece names a byte range that is either CP1252 ("compressed") or UTF-16.
Concatenating the pieces in CP order rebuilds the document part, which the FIB
then splits — only the first ``ccpText`` characters are the body, and the
headers, footers and footnotes that follow are dropped.

What comes out is text, not structure: the binary format keeps paragraph styles
in a separate property stream this reader does not open, so headings are
recovered from their clause numbers afterwards (``parsing/headings.py``). Table
cells survive as tab-separated lines. Field instructions are dropped and the
result of a ``TOC`` field with them, so the table of contents does not come
back as a second copy of every heading.

Reference: [MS-DOC], Word (.doc) Binary File Format.
"""
from __future__ import annotations

import logging
import struct
from pathlib import Path

from orrery.modules.document.parsing.doc.olecf import CompoundFile

logger = logging.getLogger(__name__)

_FIB_MAGIC = 0xA5EC
# Word 97 is nFib 193; 6.0/95 files (nFib 101/104) have a different FIB layout
# and no piece table at these offsets.
_MIN_NFIB = 193

_OFF_WIDENT = 0x0000
_OFF_NFIB = 0x0002
_OFF_FLAGS = 0x000A
_OFF_FCMIN = 0x0018
_OFF_CCPTEXT = 0x004C
_OFF_FCCLX = 0x01A2
_OFF_LCBCLX = 0x01A6

_FWHICH_TBL_STM = 0x0200

_PIECE_UNICODE_FLAG = 0x40000000
_PIECE_FC_MASK = 0x3FFFFFFF

# Word control characters inside the text stream.
_CHAR_PICTURE = "\x01"
_CHAR_FOOTNOTE = "\x02"
_CHAR_CELL_END = "\x07"
_CHAR_DRAWN_OBJECT = "\x08"
_CHAR_LINE_BREAK = "\x0b"
_CHAR_PAGE_BREAK = "\x0c"
_CHAR_PARA_END = "\r"
_CHAR_FIELD_BEGIN = "\x13"
_CHAR_FIELD_SEPARATOR = "\x14"
_CHAR_FIELD_END = "\x15"
_CHAR_NB_HYPHEN = "\x1e"
_CHAR_OPT_HYPHEN = "\x1f"

_DROPPED = {
    _CHAR_PICTURE,
    _CHAR_FOOTNOTE,
    _CHAR_DRAWN_OBJECT,
    _CHAR_OPT_HYPHEN,
    "\x03",  # short date / auto-list
    "\x04",  # abbreviated date
    "\x05",  # annotation reference
    "\n",    # always paired with \r; the \r is the paragraph mark
}

#: Field instructions whose *result* is dropped along with the instruction.
#: A table of contents replays every heading; keeping it would duplicate the
#: whole clause numbering as body text.
_SUPPRESSED_FIELDS = ("TOC", "INDEX", "HYPERLINK \\l")


def extract_text(source_path: Path) -> str:
    """The body text of a legacy ``.doc``, one paragraph per line."""
    data = Path(source_path).read_bytes()
    cf = CompoundFile(data)
    word = cf.read_stream("WordDocument")
    if len(word) < _OFF_LCBCLX + 4:
        raise RuntimeError(
            f"{source_path}: WordDocument stream is too short to hold a FIB "
            f"({len(word)} bytes)"
        )

    ident = struct.unpack_from("<H", word, _OFF_WIDENT)[0]
    if ident != _FIB_MAGIC:
        raise RuntimeError(
            f"{source_path}: WordDocument stream does not start with the FIB "
            f"magic 0x{_FIB_MAGIC:04X} (got 0x{ident:04X})"
        )
    nfib = struct.unpack_from("<H", word, _OFF_NFIB)[0]
    if nfib < _MIN_NFIB:
        raise RuntimeError(
            f"{source_path}: Word {nfib} format (pre-Word 97) is not "
            f"supported; open it in Word and save as .docx"
        )

    flags = struct.unpack_from("<H", word, _OFF_FLAGS)[0]
    table_name = "1Table" if flags & _FWHICH_TBL_STM else "0Table"
    table = cf.read_stream(table_name)

    fc_clx = struct.unpack_from("<I", word, _OFF_FCCLX)[0]
    lcb_clx = struct.unpack_from("<I", word, _OFF_LCBCLX)[0]
    ccp_text = struct.unpack_from("<I", word, _OFF_CCPTEXT)[0]
    if lcb_clx == 0:
        raise RuntimeError(
            f"{source_path}: FIB declares an empty piece table (lcbClx=0); "
            f"the document text cannot be located"
        )
    if fc_clx + lcb_clx > len(table):
        raise RuntimeError(
            f"{source_path}: piece table runs past the end of {table_name} "
            f"({fc_clx}+{lcb_clx} > {len(table)})"
        )

    pieces = _parse_piece_table(table[fc_clx:fc_clx + lcb_clx], source_path)
    raw = _read_pieces(word, pieces, ccp_text)
    logger.info(
        "DOC extractor: %d pieces, %d body characters (table stream %s)",
        len(pieces), len(raw), table_name,
    )
    return _to_text(raw)


def _parse_piece_table(clx: bytes, source_path: Path) -> list[tuple[int, int, bool]]:
    """``[(byte_offset, char_count, is_cp1252), ...]`` in character order."""
    pos = 0
    # Prc entries (clxt=1) carry paragraph/character property grprls; skip them
    # to reach the single Pcdt (clxt=2) that holds the piece table.
    while pos < len(clx) and clx[pos] == 1:
        cb_grpprl = struct.unpack_from("<H", clx, pos + 1)[0]
        pos += 3 + cb_grpprl
    if pos >= len(clx) or clx[pos] != 2:
        raise RuntimeError(
            f"{source_path}: no Pcdt (clxt=2) in the piece table"
        )
    lcb = struct.unpack_from("<I", clx, pos + 1)[0]
    plc = clx[pos + 5:pos + 5 + lcb]
    if len(plc) < lcb:
        raise RuntimeError(
            f"{source_path}: piece table truncated ({len(plc)} < {lcb})"
        )
    # PlcPcd: (n+1) character positions of 4 bytes, then n descriptors of 8.
    n = (lcb - 4) // 12
    if n <= 0:
        raise RuntimeError(f"{source_path}: piece table holds no pieces")
    cps = struct.unpack_from(f"<{n + 1}I", plc, 0)
    descriptors = plc[4 * (n + 1):]

    pieces: list[tuple[int, int, bool]] = []
    for i in range(n):
        fc_raw = struct.unpack_from("<I", descriptors, 8 * i + 2)[0]
        if fc_raw & _PIECE_UNICODE_FLAG:
            # The flag means the opposite of its name: set = one byte per
            # character, and the offset is doubled.
            offset = (fc_raw & _PIECE_FC_MASK) >> 1
            cp1252 = True
        else:
            offset = fc_raw & _PIECE_FC_MASK
            cp1252 = False
        pieces.append((offset, cps[i + 1] - cps[i], cp1252))
    return pieces


def _read_pieces(
    word: bytes, pieces: list[tuple[int, int, bool]], ccp_text: int
) -> str:
    out: list[str] = []
    seen = 0
    for offset, count, cp1252 in pieces:
        if seen >= ccp_text:
            break
        take = min(count, ccp_text - seen)
        if cp1252:
            chunk = word[offset:offset + take].decode("cp1252", errors="replace")
        else:
            chunk = word[offset:offset + 2 * take].decode("utf-16-le", errors="replace")
        if len(chunk) < take:
            raise RuntimeError(
                f"Piece at byte {offset} is short: wanted {take} characters, "
                f"the WordDocument stream holds {len(chunk)}"
            )
        out.append(chunk)
        seen += take
    return "".join(out)


def _to_text(raw: str) -> str:
    """Word control characters → line structure; fields resolved or dropped."""
    lines: list[str] = []
    buf: list[str] = []
    # One entry per open field: [instruction chars, past_separator, suppress].
    fields: list[list] = []
    i = 0
    n = len(raw)

    def flush() -> None:
        lines.append("".join(buf).rstrip())
        buf.clear()

    while i < n:
        ch = raw[i]
        i += 1

        if ch == _CHAR_FIELD_BEGIN:
            fields.append([[], False, False])
            continue
        if ch == _CHAR_FIELD_SEPARATOR:
            if fields:
                instruction = "".join(fields[-1][0]).strip().upper()
                fields[-1][1] = True
                fields[-1][2] = any(
                    instruction.startswith(f) for f in _SUPPRESSED_FIELDS
                )
            continue
        if ch == _CHAR_FIELD_END:
            if fields:
                fields.pop()
            continue

        if fields:
            top = fields[-1]
            if not top[1]:
                # Still inside the instruction: never body text.
                top[0].append(ch)
                continue
            if any(f[2] for f in fields):
                continue

        if ch in _DROPPED:
            continue
        if ch == _CHAR_PARA_END or ch == _CHAR_LINE_BREAK or ch == _CHAR_PAGE_BREAK:
            flush()
            continue
        if ch == _CHAR_CELL_END:
            # Two in a row: the second is the row mark, so the row ends here.
            if i < n and raw[i] == _CHAR_CELL_END:
                i += 1
                flush()
            else:
                buf.append("\t")
            continue
        if ch == _CHAR_NB_HYPHEN:
            buf.append("-")
            continue
        if ch == "\xa0":
            buf.append(" ")
            continue
        if ch < " ":
            continue
        buf.append(ch)

    if buf:
        flush()
    return "\n".join(lines)


__all__ = ["extract_text"]
