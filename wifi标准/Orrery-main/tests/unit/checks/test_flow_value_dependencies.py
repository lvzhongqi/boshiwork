"""``flow_value_dependencies``: the flow's stable names and dependency edges,
reported but never gating.

It stays at warn level because two correct shapes look like mistakes to it — one
binding per role that computes the value, and no binding at all when the term is
passed straight into a role.
"""

import asyncio

import orrery.checks.rules.flow  # noqa: F401
from orrery.checks.registry import must_failures, run_checks


PRINCIPALS = {
    "principals": [{"name": "A", "description": "party"}],
    "values": [
        {"name": "SKA", "derived_from": [], "description": "private key"},
        {"name": "PKA", "derived_from": ["SKA"], "description": "public key"},
    ],
}


def _results(pv, principals=PRINCIPALS):
    return asyncio.run(run_checks(
        ["flow_value_dependencies"], {"pv": pv, "principals": principals}))


def _findings(pv, principals=PRINCIPALS):
    return "\n".join(f for r in _results(pv, principals) for f in r.findings)


def test_the_check_never_blocks_a_run():
    """It is a diagnosis, not a gate: nothing it finds reaches must_failures."""
    pv = """type skey. type pkey.
process new SKA: skey; new PKA: pkey; 0
"""
    results = _results(pv)
    assert [r.level for r in results] == ["warn"]
    assert results[0].passed is False and results[0].findings
    assert must_failures(results) == []


def test_a_named_let_over_every_source_is_accepted():
    pv = """type skey. type pkey.
fun pk(skey): pkey.
process new SKA: skey; let PKA: pkey = pk(SKA) in 0
"""
    assert _findings(pv) == ""


def test_a_derived_value_created_independently_is_reported():
    pv = """type skey. type pkey.
process new SKA: skey; new PKA: pkey; 0
"""
    text = _findings(pv)
    assert "creates it independently" in text
    assert "0 named `let PKA = ... in` binding(s)" in text


def test_a_binding_that_drops_a_source_is_reported():
    principals = {
        **PRINCIPALS,
        "values": PRINCIPALS["values"] + [
            {"name": "domain", "derived_from": [], "description": "domain"},
            {"name": "credential", "derived_from": ["SKA", "domain"],
             "description": "derived credential"},
        ],
    }
    pv = """type skey. type pkey.
fun pk(skey): pkey.
process new SKA: skey; let PKA = pk(SKA) in
new domain: bitstring; let credential = pk(SKA) in 0
"""
    assert "missing ['domain']" in _findings(pv, principals)
