"""Type Equivalence: two processes are indistinguishable to the attacker
(strong secrecy / privacy / unlinkability).

Every subtype here is unimplemented. Extraction keeps the semantic label and
the injection layer rejects it explicitly, so upstream records the gap instead
of emitting a wrong query shape.
"""

from orrery.nodes.inject.injectors.base import Injector


class EquivalenceType(Injector):
    gtype = "Equivalence"
    parties = "free"
    realization = "unimplemented"
