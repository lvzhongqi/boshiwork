"""The node order table: the single source of truth for node order, re-entry
and supersession.

Two things about the order are load-bearing. The four document readers
(tag_sections, extract_principals, extract_assumptions, extract_properties)
mount the same tools and render the same corpus, so they share one cached copy
of it; extract_assumptions and extract_properties sit after extract_flow
because the names they use are flow-model names, which forces the shared corpus
to outlive the flow node (``llm.cache_ttl``).
"""

from __future__ import annotations

from orrery.nodes.base import Node
from orrery.nodes.aggregate.node import AggregateNode
from orrery.nodes.assumptions.node import AssumptionsNode
from orrery.nodes.claims.node import ExtractClaimsNode
from orrery.nodes.cross_check.node import CrossCheckNode
from orrery.nodes.flow.node import FlowNode
from orrery.nodes.preprocess.document_loader import DocumentLoaderNode
from orrery.nodes.preprocess.section_tagger import SectionTaggerNode
from orrery.nodes.properties.node import PropertiesNode
from orrery.nodes.reproduce_attacks.node import ReproduceAttacksNode
from orrery.nodes.principals.node import PrincipalsNode
from orrery.nodes.root.node import BuildRootNode
from orrery.nodes.world.node import BuildWorldNode
from orrery.pipeline.scenarios import ScenariosNode


def build_table() -> list[Node]:
    """The node table in execution order, as fresh instances. Nodes are
    stateless, and instances are never shared between runs."""
    return [
        DocumentLoaderNode(),
        SectionTaggerNode(),
        PrincipalsNode(),
        FlowNode(),
        AssumptionsNode(),
        PropertiesNode(),
        ExtractClaimsNode(),
        BuildWorldNode(),
        BuildRootNode(),
        ScenariosNode(),
        AggregateNode(),
        CrossCheckNode(),
        ReproduceAttacksNode(),
    ]


def index_of(table: list[Node], name: str) -> int:
    """Position of the node called ``name``. Raises ValueError if the table has
    no such node."""
    for i, n in enumerate(table):
        if n.name == name:
            return i
    raise ValueError(f"node {name!r} is not in the node table; table has {[n.name for n in table]}")
