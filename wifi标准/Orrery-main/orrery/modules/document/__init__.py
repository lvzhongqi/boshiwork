"""Document capabilities: loading a document set, the section tree, the
reference graph, full-text search, and tags.

Consumers go through the façades — loader / sections / references / search /
tags; model/ and parsing/ are implementation detail.
"""

from orrery.modules.document.loader import (
    DocumentLoaderService,
    ProtocolSource,
    bundle_reads_text,
    is_document,
    is_text_document,
    prefer_text,
    resolve_subprotocol_name,
)

__all__ = ["DocumentLoaderService", "ProtocolSource", "bundle_reads_text",
           "is_document", "is_text_document", "prefer_text",
           "resolve_subprotocol_name"]
