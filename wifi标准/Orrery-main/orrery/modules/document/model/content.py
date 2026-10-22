"""Rendered-content types shared by ``DocumentSet`` views and ``Normalizer``.

They live in a module of their own so both sides can depend on them without
forming an import cycle.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AnnotatedContent:
    """Concatenated text + the in-text images encountered."""

    text: str
    images: list[str]


@dataclass
class SectionSummary:
    """One row of the table-of-contents view."""

    number: str
    title: str
    level: int


__all__ = ["AnnotatedContent", "SectionSummary"]
