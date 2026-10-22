"""The goal vocabulary, rendered for the prompt.

A closed set declared in code, so all of it fits inline. Inlining keeps this
node's tool array identical to the other document readers', which is what lets
the four share one cached copy of the corpus block.

A goal subtype may require an assumption to be meaningful — ``forward_secrecy``
without the long-term key actually leaking degenerates into plain secrecy — so
that requirement is rendered beside the subtype as a pairing the claims gate
enforces, never as a condition on naming the goal, since this node cannot see
which world a scenario will assign.
"""

from __future__ import annotations

from orrery.nodes.inject.injectors import PROP_VOCAB


def property_reference() -> str:
    """Every goal type, the parties it takes, and every subtype it offers."""
    out: list[str] = []
    for gtype in PROP_VOCAB.types():
        out.append(f"**{gtype}** (parties: {PROP_VOCAB.parties_shape(gtype)})")
        for st in PROP_VOCAB.subtypes_of(gtype):
            if PROP_VOCAB.is_stub(gtype, st):
                out.append(f"  - {st} — NOT IMPLEMENTED, never choose this one")
                continue
            out.append(f"  - {st}")
            out.append(f"      {PROP_VOCAB.description(gtype, st).strip()}")
            need = PROP_VOCAB.requires_assumption(gtype, st)
            if need:
                subs = ", ".join(need["subtypes"])
                out.append(
                    f"      REQUIRES pairing: a claim asserts this goal only in "
                    f"scenarios that assign axis {need['axis']} one of [{subs}] "
                    f"— the claims step declares that pairing. Name the goal "
                    f"whenever the document states this guarantee.")
        out.append("")
    return "\n".join(out).rstrip()
