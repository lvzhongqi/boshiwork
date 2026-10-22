"""The tool contracts: one definition per tool name, and one shared array for
the document readers.

Both promises fail silently when broken — the run still works, it just costs
more or drifts — so each gets its own test. A name like ``read_section`` maps to
the same shape everywhere it is mounted, with ``report_gap`` the one exception,
since its enum is the mounting node's own legal targets. The prefix cache runs
tools → system → messages, so a single differing byte in a reader's tools array
costs the whole cached corpus sitting behind it.
"""

import json

import pytest

from orrery.agent.tools import (
    READER_TOOLS, SCENARIO_TOOLS, claims_tools, flow_tools,
)
from orrery.nodes.assumptions.node import build_prompt as assumptions_prompt
from orrery.nodes.claims.node import GAP_TARGETS as CLAIMS_GAP_TARGETS
from orrery.nodes.flow.node import GAP_TARGETS
from orrery.nodes.preprocess.section_tagger import build_prompt as tag_prompt
from orrery.nodes.principals.node import build_prompt as principals_prompt
from orrery.nodes.properties.node import build_prompt as properties_prompt

# Every node that reads the protocol document and writes one artifact out of
# it. Listed by hand rather than derived, because "these four are meant to
# match" is the claim under test; a derived list would agree with any drift.
READERS = {
    "tag_sections": tag_prompt,
    "extract_principals": principals_prompt,
    "extract_assumptions": assumptions_prompt,
    "extract_properties": properties_prompt,
}


def _wire(tools) -> str:
    """The tools serialised exactly as they go on the wire, which is what the
    prefix cache keys on; ToolDef identity says nothing about those bytes."""
    return json.dumps([t.to_function_tool().to_dict() for t in tools],
                      sort_keys=True)


@pytest.mark.parametrize("name", sorted(READERS))
def test_every_document_reader_mounts_the_shared_array(name):
    """One reader per case: its tools must be READER_TOOLS byte for byte."""
    assert _wire(READERS[name](corpus="doc", protocol="P").tools) == _wire(READER_TOOLS), (
        f"{name} no longer mounts READER_TOOLS unchanged. The document readers "
        f"share cached corpus groups, and tools sit ahead of each corpus — a "
        f"tool added here costs those groups their cache.")


def test_the_readers_are_byte_identical_to_each_other():
    """The same claim from the other side: the four readers' arrays must all
    serialise to one string, so they share a cache prefix."""
    wires = {n: _wire(f(corpus="doc", protocol="P").tools)
             for n, f in READERS.items()}
    assert len(set(wires.values())) == 1, (
        f"the document readers' tool arrays have diverged: "
        f"{ {n: len(w) for n, w in wires.items()} }")


def test_the_readers_mount_no_gap_reporting_and_no_catalog():
    """The tools that would break the reader group, named one by one so a
    failure says which promise went rather than that some bytes moved."""
    for name, f in READERS.items():
        mounted = {t.name for t in f(corpus="doc", protocol="P").tools}
        assert "report_gap" not in mounted, f"{name} mounts report_gap"
        assert "lookup_function_signature" not in mounted, f"{name} mounts the catalog"
        assert "lookup_identity_modeling" not in mounted, f"{name} mounts identity modelling"


def test_flow_mounts_each_modelling_library_once():
    """The three curated libraries, one lookup each, and only on this node.

    They are why extract_flow sits outside the reader cache group, so a second
    copy of one, or one of them reaching a reader, changes what the cache spans.
    """
    mounted = [t.name for t in flow_tools(GAP_TARGETS)]
    for name in ("lookup_identity_modeling", "lookup_structure_modeling",
                 "lookup_time_variant_modeling"):
        assert mounted.count(name) == 1, f"{name} mounted {mounted.count(name)} times"


def test_one_definition_per_tool_name():
    """Across every array a node can mount, a name maps to exactly one shape —
    except report_gap, whose enum is per node on purpose."""
    shapes: dict[str, set[str]] = {}
    for tools in (READER_TOOLS, flow_tools(GAP_TARGETS),
                  claims_tools(CLAIMS_GAP_TARGETS), SCENARIO_TOOLS):
        for t in tools:
            shapes.setdefault(t.name, set()).add(
                json.dumps(t.to_function_tool().to_dict(), sort_keys=True))
    drifted = {n: len(s) for n, s in shapes.items()
               if len(s) > 1 and n != "report_gap"}
    assert not drifted, (
        f"the same tool name is mounted with different shapes: {drifted}. "
        f"Assemble every list from the same ToolDef objects.")


def test_the_scenario_stage_mounts_nothing():
    """The apply stage runs with an empty tool array: the only candidate is
    report_gap, which from inside a scenario has no reachable target."""
    assert SCENARIO_TOOLS == []
