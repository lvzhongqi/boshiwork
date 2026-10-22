"""Word ``.docx`` document loader.

Pipeline: ZIP part extraction and Markdown rendering (``extractor``) → the
Markdown pipeline. ``loader`` holds DocxLoader, the public entry point.
"""

from orrery.modules.document.parsing.docx.loader import DocxLoader

__all__ = ["DocxLoader"]
