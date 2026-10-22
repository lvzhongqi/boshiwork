"""The inventory-conservation gate for re-seating world builders: a builder that
only re-seats principals may change instances and table rows, never the binder
inventory, so minting a fresh reverse-direction key counts as a violation."""

from orrery.nodes.world.build import binder_inventory, inventory_violations
from orrery.nodes.world.builders import builder_for

BASE = """
table key_binding(host, host, key).
free c: channel.

let processA(A: host, B: host) =
  get key_binding(=A, =B, K: key) in 0.

process
  new A: host;
  new B: host;
  new K_AB: key;
  insert key_binding(A, B, K_AB);
  ( !processA(A, B) )
"""

MINTED = BASE.replace(
    "insert key_binding(A, B, K_AB);",
    "new K_BA: key;\n  insert key_binding(A, B, K_AB);\n"
    "  insert key_binding(B, A, K_BA);")

SAME_VALUE = BASE.replace(
    "insert key_binding(A, B, K_AB);",
    "insert key_binding(A, B, K_AB);\n  insert key_binding(B, A, K_AB);")


def test_minted_reverse_key_is_rejected():
    b = builder_for("role_binding", "any_roles")
    probs = inventory_violations(b, BASE, MINTED)
    assert probs and "K_BA" in probs[0]


def test_same_value_reverse_row_passes():
    b = builder_for("role_binding", "any_roles")
    assert inventory_violations(b, BASE, SAME_VALUE) == []


def test_private_free_mint_is_caught():
    b = builder_for("role_binding", "any_roles")
    probs = inventory_violations(b, BASE, BASE + "\nfree K_BA: key [private].\n")
    assert probs and "K_BA" in probs[0]


def test_dropped_binding_is_caught():
    b = builder_for("role_binding", "any_roles")
    probs = inventory_violations(b, BASE.replace("free c: channel.\n", "free c: channel.\nconst tag: bitstring.\n"), BASE)
    assert probs and "tag" in probs[0]


def test_restructuring_builder_is_exempt():
    b = builder_for("population", "unbounded")
    assert inventory_violations(b, BASE, MINTED) == []


def test_single_session_strip_passes():
    b = builder_for("session_multiplicity", "single_session")
    base = BASE.replace("( !processA(A, B) )", "!( processA(A, B) )")
    new = BASE.replace("( !processA(A, B) )", "( processA(A, B) )")
    assert inventory_violations(b, base, new) == []


def test_added_instances_pass():
    b = builder_for("role_binding", "any_roles")
    new = BASE.replace("( !processA(A, B) )", "( !processA(A, B) | !processA(B, A) )")
    assert inventory_violations(b, BASE, new) == []
