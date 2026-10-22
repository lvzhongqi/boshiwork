"""Equivalence.strong_secrecy: kept in the property vocabulary, not wired up in
the injection layer. Declaring it is an explicit error."""
from orrery.nodes.inject.injectors.equivalence.base import EquivalenceType


class StrongSecrecy(EquivalenceType):
    subtype = "strong_secrecy"
    unimplemented = True
    description = ("Strong secrecy — the attacker cannot tell what value the "
                   "secret takes (noninterf). Not implemented in the injection "
                   "layer.")
    reason = ("strong secrecy (the attacker cannot tell what value the secret "
              "takes) needs a biprocess; the injection layer is not implemented")
