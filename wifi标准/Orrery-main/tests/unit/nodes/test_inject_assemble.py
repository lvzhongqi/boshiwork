"""inject.assemble: edits splice at their anchors, declarations go to the
declaration area, and a declaration smuggled into edits is caught before
assembly. The framework composes no syntax of its own; the wenc pair is the
model's to declare, since its type follows the secret's type."""
import pytest
from types import SimpleNamespace

from orrery.modules.pvtext.anchored import Edit, EditError
from orrery.modules.pvtext.parse import (
    PvTextError,
    duplicate_destructor_declarations,
)
from orrery.nodes.inject.node import (
    assemble,
    authentication_contract_problems,
    open_guard_before_else_problems,
    stray_declarations,
)

PV = """\
free c: channel.

let processA(A: host, K: key) =
  out(c, senc(A, K));
  0.

process
  new K: key; !processA(A, K)
"""

PAIR = [
    "fun wenc(bitstring, key): bitstring.",
    "reduc forall x: bitstring, y: key; wdec(wenc(x, y), y) = x.",
]


def test_declarations_land_in_declaration_area():
    out = assemble(
        PV,
        [Edit(anchor="out(c, senc(A, K));", position="after",
              text="  out(c, wenc(w_secrecy_k_A, K));")],
        PAIR + ["free w_secrecy_k_A: bitstring [private].",
                "query attacker(w_secrecy_k_A)."],
    )
    # every declaration sits before the first process, in submission order
    for line in PAIR:
        assert out.index(line) < out.index("let processA")
    assert out.index("query attacker") < out.index("let processA")
    assert out.count("fun wenc(") == 1


def test_no_declarations_added_on_their_own():
    out = assemble(PV, [Edit(anchor="out(c, senc(A, K));", position="before",
                             text="  event begin_auth_x(A);")], [])
    assert "wenc" not in out


def test_authentication_can_pass_a_stable_observation_identity_into_a_role():
    out = assemble(
        PV,
        [
            Edit(
                anchor="let processA(A: host, K: key) =",
                position="replace",
                text="let processA(A: host, B: host, K: key) =",
            ),
            Edit(
                anchor="!processA(A, K)",
                position="replace",
                text="!processA(A, B, K)",
            ),
        ],
        [],
    )
    assert "let processA(A: host, B: host, K: key) =" in out
    assert "!processA(A, B, K)" in out


def test_observation_membership_table_can_scope_a_witness():
    out = assemble(
        PV,
        [
            Edit(
                anchor="out(c, senc(A, K));",
                position="after",
                text=("  get honest_secrecy_k(=A) in\n"
                      "  out(c, wenc(w_secrecy_k_A, K));"),
            ),
            Edit(
                anchor="new K: key; !processA(A, K)",
                position="replace",
                text=("new K: key;\n"
                      "  insert honest_secrecy_k(A);\n"
                      "  !processA(A, K)"),
            ),
        ],
        PAIR + [
            "table honest_secrecy_k(host).",
            "free w_secrecy_k_A: bitstring [private].",
            "query attacker(w_secrecy_k_A).",
        ],
    )
    assert out.index("table honest_secrecy_k(host).") < out.index("let processA")
    assert "insert honest_secrecy_k(A);" in out
    assert "get honest_secrecy_k(=A) in" in out


def test_edit_error_propagates():
    with pytest.raises(EditError):
        assemble(PV, [Edit(anchor="no such line", position="after", text="x")], [])


def test_stray_declarations_caught():
    bad = [
        Edit(anchor="0.", position="before",
             text="query attacker(w_x)."),
        Edit(anchor="0.", position="before",
             text="free w_x: bitstring [private]."),
        Edit(anchor="0.", position="before",
             text="fun wenc(bitstring, key): bitstring."),
        Edit(anchor="0.", position="before",
             text="event end_auth_x(pkey)."),          # declaration: trailing period
    ]
    found = stray_declarations(bad)
    assert len(found) == 4


def test_event_calls_are_not_stray_declarations():
    ok = [
        Edit(anchor="0.", position="before", text="  event end_auth_x(PKA);"),
        Edit(anchor="0.", position="before",
             text="  if PKB_recv = PKB then event end_auth_x(PKA);"),
        Edit(anchor="0.", position="before",
             text="  out(c, wenc(w_x, K));"),
    ]
    assert stray_declarations(ok) == []


BRANCHED_PV = """\
free c: channel.

let processA(A: host, B: host, I: host) =
  in(c, peer: host);
  if peer = B then
    out(c, B);
    0
  else
    if peer = I then
      out(c, I);
      0.

process
  0
"""


def test_open_observation_guard_cannot_steal_existing_else():
    edits = [Edit(
        anchor="    out(c, B);\n    0",
        position="replace",
        text=("    out(c, B);\n"
              "    if peer = A || peer = B then\n"
              "      event end_auth(A, peer);\n"
              "    0"),
    )]
    found = open_guard_before_else_problems(BRANCHED_PV, edits)
    assert len(found) == 1
    assert "existing `else`" in found[0]
    assert "role A" in found[0]


def test_closed_observation_guard_preserves_existing_else():
    edits = [Edit(
        anchor="    out(c, B);\n    0",
        position="replace",
        text=("    out(c, B);\n"
              "    if peer = A || peer = B then\n"
              "      event end_auth(A, peer)\n"
              "    else\n"
              "      0"),
    )]
    assert open_guard_before_else_problems(BRANCHED_PV, edits) == []


def test_constructor_must_not_redeclare_reduction_destructor():
    declarations = [
        "fun wrap(bitstring, key): bitstring.",
        "fun unwrap(bitstring, key): bitstring.",
        ("reduc forall x: bitstring, y: key; "
         "unwrap(wrap(x, y), y) = x."),
    ]
    assert duplicate_destructor_declarations(declarations) == ["unwrap"]
    assert duplicate_destructor_declarations(PAIR) == []


def _auth_goal(**overrides):
    data = {
        "id": "auth_a_b",
        "type": "Authentication",
        "subtype": "injective_agreement",
        "values": ("A", "B", "K"),
        "parties": {"asserter": "A", "subject": "B"},
    }
    data.update(overrides)
    return SimpleNamespace(**data)


AUTH_PV = """\
event begin_auth_a_b(host, host, key).
event end_auth_a_b(host, host, key).
query a: host, b: host, k: key;
  inj-event(end_auth_a_b(a, b, k)) ==> inj-event(begin_auth_a_b(a, b, k)).

let processA(A: host, B: host, K: key) =
  event end_auth_a_b(A, B, K);
  0.

let processB(A: host, B: host, K: key) =
  event begin_auth_a_b(A, B, K);
  0.

process
  0
"""


def test_authentication_contract_accepts_values_and_parties_verbatim():
    assert authentication_contract_problems(AUTH_PV, [_auth_goal()]) == []


def test_authentication_contract_rejects_extra_begin_in_asserter():
    bad = AUTH_PV.replace(
        "  event end_auth_a_b(A, B, K);",
        "  event begin_auth_a_b(A, B, K);\n  event end_auth_a_b(A, B, K);",
    )
    found = authentication_contract_problems(bad, [_auth_goal()])
    assert any("must be called exactly once" in problem for problem in found)


def test_authentication_contract_rejects_parties_prepended_to_values():
    bad = AUTH_PV.replace("host, host, key", "host, host, host, host, key")
    found = authentication_contract_problems(bad, [_auth_goal()])
    assert any("parties add no arguments" in problem for problem in found)


def test_edits_that_leave_a_process_unterminated_are_a_cell_level_refusal():
    """An edit that ends a role body with `;` strips the process of its closing
    period. That is the same kind of mistake as a missed anchor and it says no
    the same way: assemble raises PvTextError, so the caller can put it to the
    model as a finding instead of assembling nonsense."""
    with pytest.raises(PvTextError, match="no closing period"):
        assemble(PV,
                 [Edit(anchor="  0.", position="replace",
                       text="  0;\n  out(c, wenc(w, K));")],
                 PAIR + ["free w: bitstring [private]."])
