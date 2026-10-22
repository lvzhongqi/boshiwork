"""Cross-section reference (lazy: only metadata, never resolved content)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RefKind(str, Enum):
    SECTION = "section"            # General cross-section reference.
    TERM = "term"                  # Term-definition reference.
    SELF_SECTION = "self_section"  # Self-document section reference.

    @classmethod
    def from_str(cls, value: str) -> RefKind:
        v = value.strip().lower()
        for item in cls:
            if item.value == v:
                return item
        raise ValueError(f"Unknown RefKind: {value!r}")


@dataclass
class SegmentReference:
    """Pointer to another section.

    Identified at annotation time and dereferenced at render time; the target
    content is never stored on the reference itself.
    """

    target_doc: str           # doc_id, or "self" for the current document.
    target_section: str       # Normalized section number, e.g. "5.2.3".
    ref_kind: RefKind = RefKind.SECTION
    mode: str = "append"      # "replace" | "append" — how to combine with source.
    inline_hint: str = ""     # Phrase in the source text that triggered it.

    def to_dict(self) -> dict:
        d: dict = {
            "target_doc": self.target_doc,
            "target_section": self.target_section,
            "ref_kind": self.ref_kind.value,
            "mode": self.mode,
        }
        if self.inline_hint:
            d["inline_hint"] = self.inline_hint
        return d

    @classmethod
    def from_dict(cls, d: dict) -> SegmentReference:
        try:
            return cls(
                target_doc=d["target_doc"],
                target_section=d["target_section"],
                ref_kind=RefKind.from_str(d.get("ref_kind", "section")),
                mode=d.get("mode", "append"),
                inline_hint=d.get("inline_hint", ""),
            )
        except KeyError as e:
            raise RuntimeError(f"SegmentReference missing required field: {e}") from e
