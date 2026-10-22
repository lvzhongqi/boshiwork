"""Two ways of writing to disk, chosen by the kind of file.

Artifacts (.pv / json / md) are written whole through a temp file and a rename,
so the path always holds one complete version. Streams (transcript / event jsonl)
are appended line by line: a kill damages at most the last line, which readers
drop, while a broken middle line means the file was edited outside the pipeline.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def write_text(path: Path, text: str) -> None:
    """Artifact write: temp file in the same directory, then os.replace.

    The temp file shares the directory because a rename is only atomic within
    one volume. The temp file is removed if anything fails.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def write_json(path: Path, obj) -> None:
    """Artifact write of obj as indented UTF-8 JSON with a trailing newline."""
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def append_line(path: Path, line: str) -> None:
    """Stream write: append one line and flush; raises ValueError on a newline.

    Flushed without fsync, so the bytes sit in the kernel buffer and survive the
    process being killed, but not the machine losing power. A partial line left
    by such a kill is cut before the append (``_drop_partial_tail``), so every
    line in the file stays a whole record.
    """
    if "\n" in line:
        raise ValueError("append_line takes one line; newlines are not allowed")
    path.parent.mkdir(parents=True, exist_ok=True)
    _drop_partial_tail(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


#: How far back to look for the newline that ends the last whole record. One
#: read covers any line these ledgers write; a longer tail means the file is
#: not line-oriented, which is a fault rather than something to search for.
_TAIL_SCAN = 1 << 20


def _drop_partial_tail(path: Path) -> None:
    """Cut a trailing partial line, so every line in the file is a whole record.

    A kill between a write and its flush leaves bytes with no closing newline.
    They are debris, not history: no reader can parse them, and appending after
    them is what makes the damage permanent — the half line stops being the
    last line, and ``read_jsonl_tolerant`` then reads it as the signature of a
    file edited from outside and refuses the whole thing. That verdict has to
    stay true, so the debris goes rather than the guarantee.

    Binary throughout. Every writer here dumps JSON with ensure_ascii=False, so
    a half line can end inside a multi-byte character, where a text-mode
    seek(tell() - 1) lands mid-character and read() raises UnicodeDecodeError —
    the very case this repair exists for.
    """
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return
    if not size:
        return
    with open(path, "rb+") as f:
        f.seek(max(0, size - _TAIL_SCAN))
        tail = f.read()
        if tail.endswith(b"\n"):
            return
        cut = tail.rfind(b"\n")
        if cut < 0 and size > len(tail):
            raise ValueError(
                f"{path}: no line ending in the last {_TAIL_SCAN} bytes; this "
                f"is not the line-oriented file append_line writes")
        f.truncate(size - (len(tail) - cut - 1))


def _lines(path: Path) -> tuple[list[bytes], bool]:
    """The file's lines as bytes, and whether the last one ends in a newline.

    Split on ``\\n`` alone, in bytes. ``str.splitlines`` also breaks on
    U+2028, U+2029 and U+0085, which ``json.dumps(ensure_ascii=False)`` leaves
    unescaped inside a string — one such character in a model reply would then
    read as a line break the writer never wrote, and the record after it as a
    broken middle line. Bytes, because a kill can cut a line inside a
    multi-byte character, and decoding the whole file first would raise before
    the damaged line is ever looked at.
    """
    raw = path.read_bytes()
    if not raw:
        return [], True
    lines = raw.split(b"\n")
    terminated = lines[-1] == b""
    if terminated:
        lines.pop()
    return lines, terminated


def read_jsonl_tolerant(path: Path) -> list[dict]:
    """Read jsonl: a broken last line is dropped (kill semantics), a broken
    middle line is an error."""
    if not path.exists():
        return []
    lines, _ = _lines(path)
    out: list[dict] = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError):
            if i == len(lines) - 1:
                break  # half line left by a kill; dropping it is the recovery
            raise ValueError(
                f"{path}:{i + 1}: invalid JSON on a middle line; only the last line may "
                f"be damaged by a kill, so this file was edited externally"
            )
    return out


def read_jsonl_records(path: Path, *, what: str) -> list[tuple[int, dict]]:
    """Read jsonl whose every line matters: ``(line number, record)`` pairs.

    Only the signature a kill leaves — a last line with no closing newline —
    is dropped, the same recovery ``append_line`` makes on the next write. Any
    other line that does not parse raises RuntimeError naming ``what`` the
    file is, since a record silently skipped changes the answer the file
    gives instead of degrading it.
    """
    if not path.exists():
        return []
    lines, terminated = _lines(path)
    out: list[tuple[int, dict]] = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            out.append((i + 1, json.loads(line.decode("utf-8"))))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            if i == len(lines) - 1 and not terminated:
                break  # the half line a kill leaves; the next append cuts it
            raise RuntimeError(
                f"{path}:{i + 1}: unreadable line in {what}; only an unterminated "
                f"last line can be left by a kill, so this file was edited "
                f"externally") from e
    return out
