"""PDF document loader.

Pipeline: pdfminer layout analysis and Markdown rendering (``extractor``) →
the Markdown pipeline. ``loader`` holds PDFLoader, the public entry point.
"""

from orrery.modules.document.parsing.pdf.loader import PDFLoader

__all__ = ["PDFLoader"]
