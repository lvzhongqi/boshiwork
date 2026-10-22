"""Legacy Word binary (``.doc``) document loader.

Pipeline: OLE compound file (``olecf``) → piece-table text (``extractor``) →
clause-number heading markup (``parsing.headings``) → the Markdown pipeline.
``loader`` holds DocLoader, the public entry point.
"""

from orrery.modules.document.parsing.doc.loader import DocLoader

__all__ = ["DocLoader"]
