"""The role-body-structure contract: one process per principal, with the party's
several ways in as parallel branches inside that one body and a marker saying
how many and which.

These cover the mechanical half only. Whether the branches really are
independent exchanges is a reading of the document, and the branch's first token
does not say — an entry may open with `in(...)`, with `new`/`out(...)`, or with
a `get` on a table.
"""
from __future__ import annotations

import pytest

import orrery.checks.rules.flow  # noqa: F401  registers the checks
from orrery.checks.registry import run_checks
from orrery.modules.kbase.modeling_idioms import select_structure_idiom

OFFERED = frozenset({("structure.independent_entries", 1)})

GOOD = """\
let processAS(x: bitstring) =
  (* @ROLE AS *)
  (* @orrery-idiom structure.independent_entries/v1 entries=grant,token,refresh *)
  (
    ( (* @ENTRY grant *)   in(c, m1: bitstring); event reached_AS() )
  | ( (* @ENTRY token *)   in(c, m2: bitstring); event reached_AS() )
  | ( (* @ENTRY refresh *) in(c, m3: bitstring); event reached_AS() )
  ).
"""


async def _check(pv, offered=OFFERED, roles=("AS",)):
    [result] = await run_checks(["flow_modeling_idioms"], {
        "pv": pv, "offered_identity_idioms": None, "roles": list(roles),
        "offered_structure_idioms": offered,
    })
    return result


@pytest.mark.asyncio
async def test_the_shape_the_card_describes_passes():
    assert (await _check(GOOD)).passed


@pytest.mark.asyncio
async def test_an_entry_the_party_itself_starts_is_still_an_entry():
    """An entry may open with `new`/`out(...)` instead of `in(...)`; the check
    does not require a branch to begin by receiving."""
    pv = GOOD.replace("(* @ENTRY refresh *) in(c, m3: bitstring);",
                      "(* @ENTRY refresh *) new n: bitstring; out(c, n);")
    assert (await _check(pv)).passed


@pytest.mark.asyncio
async def test_a_branch_that_neither_sends_nor_receives_is_not_an_exchange():
    pv = GOOD.replace("(* @ENTRY refresh *) in(c, m3: bitstring);",
                      "(* @ENTRY refresh *) new n: bitstring;")
    result = await _check(pv)
    assert not result.passed
    assert any("neither sends nor receives" in x for x in result.findings)


@pytest.mark.asyncio
async def test_the_declared_entries_have_to_match_the_branches():
    result = await _check(GOOD.replace("entries=grant,token,refresh", "entries=grant,token"))
    assert not result.passed
    assert any("composes 3 parallel branches" in x for x in result.findings)


@pytest.mark.asyncio
async def test_every_branch_names_which_entry_it_is():
    result = await _check(GOOD.replace("(* @ENTRY token *)", ""))
    assert not result.passed
    assert any("`(* @ENTRY <name> *)` marker(s)" in x for x in result.findings)


@pytest.mark.asyncio
async def test_every_entry_marks_its_own_honest_end():
    """One query covers the whole role, so each entry still needs its own event:
    the probe removal that produces flow.pv reads them one per entry."""
    pv = GOOD.replace("in(c, m2: bitstring); event reached_AS()", "in(c, m2: bitstring); 0")
    result = await _check(pv)
    assert not result.passed
    assert any("0 time(s)" in x for x in result.findings)


@pytest.mark.asyncio
async def test_a_parallel_body_without_a_marker_is_sent_to_the_library():
    """The marker is required: without it the later checks cannot tell a right
    shape from a wrong one, so the body is sent back to the library."""
    pv = "\n".join(l for l in GOOD.splitlines() if "@orrery-idiom" not in l)
    result = await _check(pv)
    assert not result.passed
    assert any("call lookup_structure_modeling" in x for x in result.findings)


@pytest.mark.asyncio
async def test_a_marker_the_session_was_never_shown_is_refused():
    result = await _check(GOOD, offered=frozenset())
    assert not result.passed
    assert any("never shown" in x for x in result.findings)


@pytest.mark.asyncio
async def test_a_supplied_mother_model_carries_its_marker_alone():
    """`None` offered means there was no extraction session to offer anything;
    the durable in-text marker is then the whole contract."""
    assert (await _check(GOOD, offered=None)).passed


@pytest.mark.asyncio
async def test_an_ordinary_linear_body_is_untouched():
    pv = "let processAS(x: bitstring) =\n  in(c, m: bitstring);\n  event reached_AS().\n"
    assert (await _check(pv)).passed


@pytest.mark.asyncio
async def test_one_entry_is_not_this_shape():
    pv = GOOD.replace("entries=grant,token,refresh", "entries=grant")
    result = await _check(pv)
    assert not result.passed
    assert any("one entry is an ordinary linear body" in x for x in result.findings)


def test_the_library_always_answers():
    """`select_structure_idiom` returns a card for any query, so a miss here is
    not the coverage gap an identity miss is."""
    assert select_structure_idiom("token endpoint also answers refresh requests").key == (
        "structure.independent_entries", 1)
    assert select_structure_idiom("something entirely unrelated").key == (
        "structure.independent_entries", 1)
