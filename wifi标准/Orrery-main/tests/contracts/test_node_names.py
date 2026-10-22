"""Every report_gap enum must be a set the framework would actually accept.

``agent/`` may not import ``pipeline/``, so each node carries its own copy of
its legal targets in ``Node.gap_targets`` and ``gap_tools.gap_tool`` builds the
enum the model sees out of that copy. The bound is what both checks in
``pipeline/control/gaps.verify`` accept: upstream of the reporter, and
model-driven. A node may declare fewer targets than the bound but never one
outside it, which is what keeps self-targets and downstream targets unreachable.
"""

import pytest

from orrery.agent.tools.gap_tools import gap_tool
from orrery.pipeline.table import build_table


def _bound(table, name: str) -> set[str]:
    names = [n.name for n in table]
    upstream = names[:names.index(name)]
    model_driven = {n.name for n in table if n.model_driven}
    return {n for n in upstream if n in model_driven}


@pytest.mark.parametrize("node", build_table(), ids=lambda n: n.name)
def test_declared_gap_targets_are_inside_the_structural_bound(node):
    """One node per case: its declared targets must all be upstream and
    model-driven."""
    table = build_table()
    illegal = set(node.gap_targets) - _bound(table, node.name)
    assert not illegal, (
        f"{node.name} declares gap targets the framework would reject: "
        f"{sorted(illegal)}. Legal here: {sorted(_bound(table, node.name))}")


def test_a_node_never_targets_itself_or_downstream():
    """The half of the bound that matters most, checked on its own so a failure
    names the offending pair instead of a set difference."""
    table = build_table()
    names = [n.name for n in table]
    for node in table:
        for t in node.gap_targets:
            assert names.index(t) < names.index(node.name), (
                f"{node.name} may report against {t!r}, which is itself or "
                f"downstream of it — report_gap only ever looks backwards")


def test_the_tool_refuses_an_empty_target_set():
    """A node with nothing model-driven upstream must not mount the tool: an
    empty enum can only ever be answered illegally, so gap_tool raises."""
    with pytest.raises(ValueError, match="at least one legal target"):
        gap_tool(())


def test_the_enum_is_exactly_what_the_node_declared():
    """The joint between a node's declared targets and the schema the model
    sees: the enum is exactly the declared tuple, in order."""
    from orrery.nodes.flow.node import GAP_TARGETS
    tool = gap_tool(GAP_TARGETS)
    assert tool.parameters.properties["target"].enum == list(GAP_TARGETS)
