"""No backtick may sit inside an HTML comment in a console script.

The console's Vue templates are JavaScript template literals, so a backtick in a
markup comment closes the literal early and everything after it parses as code:
a blank page and a SyntaxError pointing at some unrelated word. ``node --check``
misses it, because the stray backtick pairs with a later one and the file stays
valid JavaScript that simply means something else.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[2] / "orrery" / "web" / "static" / "js"

#: Any HTML comment, across lines: the templates are one long literal, so a
#: comment spanning several lines is normal.
COMMENT = re.compile(r"<!--.*?-->", re.S)


def _scripts() -> list[Path]:
    return sorted(p for p in JS.glob("*.js"))


def test_the_console_has_scripts_to_check() -> None:
    """The glob is the test's own subject; an empty one would pass everything."""
    assert _scripts(), f"no console scripts under {JS}"


@pytest.mark.parametrize("path", _scripts(), ids=lambda p: p.name)
def test_no_backtick_inside_a_markup_comment(path: Path) -> None:
    """Scan one console script and report every markup comment holding a
    backtick, with its line number."""
    text = path.read_text(encoding="utf-8")
    bad = []
    for m in COMMENT.finditer(text):
        if "`" not in m.group(0):
            continue
        line = text.count("\n", 0, m.start()) + 1
        bad.append(f"{path.name}:{line}: {' '.join(m.group(0).split())[:90]}")
    assert not bad, (
        "a backtick inside a markup comment ends the template literal it sits "
        "in, and the page goes blank with a syntax error pointing somewhere "
        "else:\n  " + "\n  ".join(bad))
