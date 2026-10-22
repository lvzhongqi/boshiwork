"""Pinned steps: what a run was handed, it cannot usefully re-enter.

A supplied artifact makes its node a no-op that writes the same bytes back, so
three places have to agree the step is closed: the node stands aside, the gap
tool stops offering it as a fallback target, and the console greys it out. All
three read pinned_nodes, which is what these tests hold still.
"""

import pytest

from orrery.nodes.base import PINNED_BY, RunEnv, pinned_nodes


def test_nothing_supplied_pins_nothing():
    assert pinned_nodes({}) == frozenset()
    assert pinned_nodes({k: None for k in PINNED_BY}) == frozenset()


def test_each_input_pins_its_own_node():
    for key, node in PINNED_BY.items():
        assert pinned_nodes({key: "/some/path"}) == frozenset({node}), key


def test_the_mother_model_alone_leaves_the_document_steps_alive():
    """extract_assumptions and extract_properties still read the corpus, so the
    tags still have a reader. Pinning the document steps here would leave a
    large protocol's readers with only a table of contents."""
    pinned = pinned_nodes({"flow": "f.pv", "principals": "p.json",
                           "world": "w.json"})
    assert pinned == frozenset({"extract_flow", "extract_principals"})
    assert "tag_sections" not in pinned
    assert "load_document" not in pinned


def test_every_reader_supplied_pins_the_document_steps_too():
    """Nobody asks for the corpus again, so tagging it would be a model call
    whose product has no reader."""
    pinned = pinned_nodes({k: "x" for k in PINNED_BY})
    assert pinned == frozenset(PINNED_BY.values()) | {"load_document",
                                                      "tag_sections"}


def test_one_reader_left_unsupplied_keeps_the_document_steps():
    # Sparing a node, not a key: extract_principals writes both principals and
    # world, so its two inputs have to go missing together — withholding one
    # would still pin the node by the other.
    for spared in set(PINNED_BY.values()):
        supplied = {k: "x" for k, node in PINNED_BY.items() if node != spared}
        assert "tag_sections" not in pinned_nodes(supplied), spared


def _env(**supplied) -> RunEnv:
    return RunEnv(protocol_dir=None, layout=None, config={},
                  node_names=("load_document", "tag_sections",
                              "extract_principals", "extract_flow",
                              "extract_assumptions", "extract_properties",
                              "extract_claims", "build_world"),
                  **supplied)


def test_a_pinned_node_is_not_a_legal_gap_target():
    """report_gap asks an upstream step to redo its work. A step holding a file
    somebody handed it has no work to redo, so the round trip would land
    exactly where it started."""
    env = _env(flow_input="f.pv", principals_input="p.json",
               )
    upstream = env.upstream("extract_claims")
    assert "extract_flow" not in upstream
    assert "extract_principals" not in upstream
    # the steps that still extract stay reachable
    assert "extract_assumptions" in upstream
    assert "extract_properties" in upstream


def test_with_nothing_supplied_every_upstream_step_stays_reachable():
    env = _env()
    assert env.upstream("extract_claims") == (
        "load_document", "tag_sections", "extract_principals", "extract_flow",
        "extract_assumptions", "extract_properties")


def test_env_reports_what_it_was_handed_under_run_json_names():
    """The keys are run.json's field names, which are also run()'s parameter
    names; that shared spelling lets one table serve the engine, the console
    and re-entry."""
    env = _env(claims_input="c.json")
    assert set(env.supplied()) == set(PINNED_BY)
    assert env.pinned() == frozenset({"extract_claims"})
