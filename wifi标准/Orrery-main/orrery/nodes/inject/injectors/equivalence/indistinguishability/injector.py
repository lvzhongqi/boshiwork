"""Equivalence.indistinguishability: kept in the property vocabulary, not wired
up in the injection layer. Declaring it is an explicit error."""
from orrery.nodes.inject.injectors.equivalence.base import EquivalenceType


class Indistinguishability(EquivalenceType):
    subtype = "indistinguishability"
    unimplemented = True
    description = "Indistinguishability. Not implemented in the injection layer."
    reason = ("indistinguishability needs an equivalence query rather than a "
              "reachability query; the injection layer is not implemented")
