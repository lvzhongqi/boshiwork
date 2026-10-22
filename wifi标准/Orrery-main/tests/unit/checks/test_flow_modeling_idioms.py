"""Tests for ``flow_modeling_idioms`` on the identity axis: a marker in the
flow text has to match the library card it names and the structure that card
describes, and it has to be one the extraction session was actually offered."""

import pytest

import orrery.checks.rules.flow  # noqa: F401
from orrery.checks.registry import run_checks


async def _check(pv, offered=None, roles=()):
    # `roles` is part of the payload the node always builds; these cases declare
    # none, so the role-body-structure half of the check has nothing to read.
    [result] = await run_checks(["flow_modeling_idioms"], {
        "pv": pv, "offered_identity_idioms": offered, "roles": list(roles),
    })
    return result


@pytest.mark.asyncio
async def test_registry_marker_requires_closed_registry_structure():
    marker = "(* @orrery-idiom identity.key_registry/v1 scope=peer_auth *)\n"
    bad = await _check(marker, {("identity.key_registry", 1)})
    assert not bad.passed
    assert any("declares no table" in x for x in bad.findings)

    pv = marker + """table keys(host, pkey).
let role(A: host) =
  get keys(=A, K: pkey) in
  0.
process
  new A: host;
  new K: pkey;
  insert keys(A, K);
  role(A)
"""
    good = await _check(pv, {("identity.key_registry", 1)})
    assert good.passed, good.findings


@pytest.mark.asyncio
async def test_flow_cannot_select_an_idiom_the_tool_never_offered():
    pv = """(* @orrery-idiom identity.private_provisioning/v1 scope=peer_auth *)
fun id(pkey): bitstring [private].
process 0
"""
    result = await _check(pv, {("identity.key_registry", 1)})
    assert not result.passed
    assert any("never shown" in x for x in result.findings)


@pytest.mark.asyncio
async def test_supplied_flow_uses_its_durable_marker_without_session_state():
    pv = """(* @orrery-idiom identity.private_provisioning/v1 scope=peer_auth *)
fun id(pkey): bitstring [private].
process 0
"""
    result = await _check(pv, None)
    assert result.passed, result.findings


@pytest.mark.asyncio
async def test_unmanaged_table_lookup_is_not_a_legacy_identity_form():
    pv = """table keys(host, pkey).
let role(A: host) =
  get keys(=A, K: pkey) in
  0.
process 0
"""
    result = await _check(pv, set())
    assert not result.passed
    assert any("no modelling marker" in x for x in result.findings)


@pytest.mark.asyncio
async def test_a_library_coverage_miss_blocks_submission():
    [result] = await run_checks(["flow_modeling_idioms"], {
        "pv": "process 0", "offered_identity_idioms": set(), "roles": [],
        "identity_modeling_miss": True,
    })
    assert not result.passed
    assert any("coverage gap" in x for x in result.findings)
