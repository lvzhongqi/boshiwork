"""Injector for Secrecy.basic. The logic lives in base; this file only declares
its identity, and the prompt is the .md of the same name."""
from orrery.nodes.inject.injectors.secrecy.base import SecrecyType


class Basic(SecrecyType):
    subtype = "basic"
    description = ("The attacker never obtains the named value as its holders "
                   "hold it — plain reachability secrecy against the Dolev-Yao "
                   "attacker.")
