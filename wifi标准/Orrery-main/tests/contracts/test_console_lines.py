"""Every ledger event the engine can write has a line the console can render
it as, in both languages, and a case that folds it.

The renderer falls back to raw JSON for a type it has no builder for
(format.js), and the store banners a type it has no case for. Both are the
silent-degradation the console rules forbid, and neither is a test the page
can run on itself, so the vocabularies are compared here: the engine's KNOWN
against the keys of LINE_EN / LINE_ZH and of HANDLED, read off the scripts.
"""

from __future__ import annotations

import re
from pathlib import Path

from orrery.services.events import KNOWN

JS = Path(__file__).resolve().parents[2] / "orrery" / "web" / "static" / "js"


def _keys_of(block: str) -> set[str]:
    """The keys of one object literal written one entry per line."""
    return set(re.findall(r"^  ([a-z_]+): ", block, flags=re.M))


def _block(text: str, name: str) -> str:
    m = re.search(rf"^const {name} = \{{\n(.*?)^\}}", text, flags=re.M | re.S)
    assert m, f"{name} not found"
    return m.group(1)


def test_every_ledger_event_has_a_line_in_both_languages() -> None:
    text = (JS / "i18n.js").read_text(encoding="utf-8")
    for name in ("LINE_EN", "LINE_ZH"):
        missing = set(KNOWN) - _keys_of(_block(text, name))
        assert not missing, f"{name} renders no line for {sorted(missing)}"


def test_the_two_line_tables_carry_the_same_keys() -> None:
    text = (JS / "i18n.js").read_text(encoding="utf-8")
    assert _keys_of(_block(text, "LINE_EN")) == _keys_of(_block(text, "LINE_ZH"))


def test_every_ledger_event_is_folded_by_the_store() -> None:
    text = (JS / "store.js").read_text(encoding="utf-8")
    m = re.search(r"export const HANDLED = new Set\(\[(.*?)\]\)", text, flags=re.S)
    assert m, "HANDLED not found"
    handled = set(re.findall(r"'([a-z_]+)'", m.group(1)))
    missing = set(KNOWN) - handled
    assert not missing, f"the store has no case for {sorted(missing)}"
