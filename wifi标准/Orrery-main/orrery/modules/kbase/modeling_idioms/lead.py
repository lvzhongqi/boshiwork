"""The one sentence each library puts in front of what retrieval hands back.

It is prompt text, so it lives in the library's own YAML beside the cards it
introduces. One loader serves all three libraries.
"""

from __future__ import annotations


def load_lead(raw: dict, label: str) -> str:
    """The library's ``lead`` sentence, stripped. ``label`` only names the
    library in the error. Raises RuntimeError when ``lead`` is missing or
    blank."""
    text = raw.get("lead")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError(f"[{label}] lead is required")
    return text.strip()
