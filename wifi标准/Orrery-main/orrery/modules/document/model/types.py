"""Section semantic types used by tags and downstream content queries."""
from __future__ import annotations

from enum import Enum


class SectionType(str, Enum):
    DEFINITION = "definition"
    FLOW = "flow"
    SECURITY = "security"
    ASSUMPTION = "assumption"
    ENTITIES = "entities"

    @classmethod
    def from_str(cls, value: str) -> SectionType:
        v = value.strip().lower()
        for item in cls:
            if item.value == v:
                return item
        raise ValueError(f"Unknown SectionType: {value!r}")
