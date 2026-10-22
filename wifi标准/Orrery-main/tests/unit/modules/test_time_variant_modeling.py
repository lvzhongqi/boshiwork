"""The time-variant modeling library: two entries, one answer per query.

A plain timestamp description must land on the opaque-fresh-value method, and
the narrow finite-state exception must be reachable only by a description that
meets its gate. Encoding a timestamp as a state machine over public constants
costs ProVerif its verdict and lets the attacker mint valid timestamps.
"""

import pytest

from orrery.agent.tools import READER_TOOLS, flow_tools
from orrery.agent.tools.context import ToolContext
from orrery.agent.tools.modeling_tools import TIME_VARIANT_MODELING_TOOLS
from orrery.modules.kbase.modeling_idioms import (
    select_time_variant_idiom, time_variant_idiom, time_variant_idioms,
)
from orrery.nodes.flow.node import GAP_TARGETS

PLAIN = [
    "B mints a timestamp T_b in the ticket; the document says B checks it has not "
    "expired but gives no clock arithmetic, and S forwards the value unchanged",
    "the document carries a timestamp field but defines no clock arithmetic",
    "S stamps T into both ciphertexts and A only forwards the ticket",
    "文档带时戳字段，接收方只搬运，没有给出具体时钟算术",
]

GATED = [
    "SQN freshness with AUTS resynchronisation: there is an observable resync "
    "branch, the state word travels inside a MAC, and the levels are finite",
    "sequence number window with counter resynchronisation",
]


def test_library_is_closed():
    ids = {x.id for x in time_variant_idioms()}
    assert ids == {"time.opaque_fresh_value", "time.finite_state_window"}
    for item in time_variant_idioms():
        assert item.prompt
        assert time_variant_idiom(item.id, item.version) is item


@pytest.mark.parametrize("query", PLAIN)
def test_a_plain_timestamp_lands_on_the_opaque_fresh_value(query):
    assert select_time_variant_idiom(query).id == "time.opaque_fresh_value"


@pytest.mark.parametrize("query", GATED)
def test_the_finite_state_exception_needs_its_own_cues(query):
    assert select_time_variant_idiom(query).id == "time.finite_state_window"


def test_nothing_matching_still_returns_the_default():
    """There is always a correct way to model a timestamp, so an unmatched
    query falls back to the default instead of returning nothing."""
    assert select_time_variant_idiom("qqq zzz wwww").id == "time.opaque_fresh_value"


def test_an_empty_query_is_a_loud_error():
    with pytest.raises(ValueError):
        select_time_variant_idiom("   ")


def test_the_tool_returns_exactly_one_method_with_a_replayable_header():
    ctx = ToolContext(node="extract_flow", prompt_lang="zh")
    out = TIME_VARIANT_MODELING_TOOLS[0].handler(ctx, PLAIN[0])
    assert out.startswith("[time-variant-modeling: time.opaque_fresh_value@1]")
    assert "time.finite_state_window" not in out
    assert "new T_b" in out


def test_only_the_flow_mounts_it():
    """The four readers share one cached prefix, so a flow-only tool that
    reached READER_TOOLS would cost them the whole corpus cache."""
    assert [t.name for t in flow_tools(GAP_TARGETS)].count(
        "lookup_time_variant_modeling") == 1
    assert "lookup_time_variant_modeling" not in {t.name for t in READER_TOOLS}
