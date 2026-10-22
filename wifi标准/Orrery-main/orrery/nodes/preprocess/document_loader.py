"""Node 1, load_document: pure code that builds the document set — the section
tree plus the reference annotations.

The result lives in memory on ``env.doc_set`` and is never written to disk, so
the node is ``always_run`` and rebuilds the tree on every re-entry.
"""

from __future__ import annotations

from orrery.modules.document import DocumentLoaderService, ProtocolSource
from orrery.nodes.base import Node, RunEnv


class DocumentLoaderNode(Node):
    name = "load_document"
    short = "load"
    task = (
        "Load the protocol document set (the main document and its "
        "dependencies)")
    always_run = True

    def is_done(self, env: RunEnv) -> bool:
        return env.doc_set is not None

    async def run(self, env: RunEnv) -> None:
        # The producing node owns the supplied-input branch; there is no
        # separate reader node forwarding a path.
        given = env.documents_input
        source = (
            ProtocolSource.from_documents(given["main"], given.get("refs") or ())
            if given is not None else
            ProtocolSource.from_directory(env.protocol_dir,
                                          target_name=env.subprotocol)
        )
        env.doc_set = await DocumentLoaderService().load(source)
