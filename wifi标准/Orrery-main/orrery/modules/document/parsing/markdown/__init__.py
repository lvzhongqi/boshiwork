"""Markdown protocol document loader.

Pipeline, one module per step: read bytes → cosmetic clean (``cleaner``) →
heading-number canonicalization (``normalizer``) → structural parse
(``parser``) → body split into typed blocks (``blocks``). ``loader`` holds
MarkdownLoader, the public entry point that chains them.
"""

from orrery.modules.document.parsing.markdown.loader import MarkdownLoader

__all__ = ["MarkdownLoader"]
