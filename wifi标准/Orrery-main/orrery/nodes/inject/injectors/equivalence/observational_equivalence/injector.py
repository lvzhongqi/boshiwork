"""Equivalence.observational_equivalence: kept in the property vocabulary, not
wired up in the injection layer. Declaring it is an explicit error."""
from orrery.nodes.inject.injectors.equivalence.base import EquivalenceType


class ObservationalEquivalence(EquivalenceType):
    subtype = "observational_equivalence"
    unimplemented = True
    description = ("Observational equivalence (choice[...]). Not implemented in "
                   "the injection layer.")
    reason = ("observational equivalence needs a biprocess (choice[...]) rather "
              "than a reachability query; the injection layer is not implemented")
