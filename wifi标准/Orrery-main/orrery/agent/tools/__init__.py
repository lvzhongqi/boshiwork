"""Tool definitions in one place, and one tool list per node that runs a session.

Every list is assembled from the same ``ToolDef`` objects, so one tool name has
one shape everywhere. The prefix cache runs tools → system → messages, so two
nodes share a cached prefix only when their tool arrays are byte-identical, and
the four document readers are the only group arranged that way.
"""

from orrery.agent.tools.document_tools import DOCUMENT_TOOLS
from orrery.agent.tools.gap_tools import gap_tool
from orrery.agent.tools.model_tools import MODEL_TOOLS
from orrery.agent.tools.modeling_tools import (
    IDENTITY_MODELING_TOOLS, STRUCTURE_MODELING_TOOLS,
    TIME_VARIANT_MODELING_TOOLS,
)

# The document readers: tag_sections, extract_principals, extract_assumptions,
# extract_properties. One shared tool array, held byte-equal by a contract test
# even though the corpus block each reader renders differs.
READER_TOOLS = list(DOCUMENT_TOOLS)

# extract_flow: the readers' tools plus the primitive catalog, the three
# modelling lookups, and gap reporting. The gap enum comes from
# FlowNode.gap_targets, so the node declares its own upstream.
def flow_tools(gap_targets: tuple[str, ...]) -> list:
    return [*DOCUMENT_TOOLS, *MODEL_TOOLS, *IDENTITY_MODELING_TOOLS,
            *STRUCTURE_MODELING_TOOLS, *TIME_VARIANT_MODELING_TOOLS,
            gap_tool(gap_targets)]

# extract_claims: the readers' tools plus gap reporting, and no catalog — it
# writes no .pv. Mounting report_gap is what takes it out of the reader cache
# group; that tool is how its reverse edges to assumptions and properties reach
# the node that has to change, at the cost of one extra corpus write per run.
def claims_tools(gap_targets: tuple[str, ...]) -> list:
    return [*DOCUMENT_TOOLS, gap_tool(gap_targets)]

# The scenario stage has no input-side tool: the task is a pure modelling
# rewrite and the submission's acceptance checks are the feedback loop.
SCENARIO_TOOLS: list = []
