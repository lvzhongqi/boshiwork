"""Type Privacy: the attacker cannot link protocol activity to a principal
across sessions.

Privacy goals verify through observational equivalence (choice[...]), a
different solving mode from Secrecy's reachability queries.
"""

from orrery.nodes.inject.injectors.base import Injector


class PrivacyType(Injector):
    gtype = "Privacy"
    parties = "subjects"
    realization = "observational_equivalence"
