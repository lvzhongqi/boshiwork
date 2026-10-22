"""Secrecy.weak_secret_guessing_resistance: ProVerif ``weaksecret`` analysis.

Offline-guessing resistance for a weak secret (password / PIN class). The
question is not derivability — the secret is never sent, so
``query attacker(pi)`` is trivially true — but whether any public value lets a
candidate guess be verified offline. ``weaksecret pi.`` is a
substitution-equivalence check, a different solving machine from reachability.
The assumption side hoists the low-entropy value to a top-level private free;
this injector adds only the ``weaksecret`` declaration.
"""
from orrery.nodes.inject.injectors.secrecy.base import SecrecyType


class WeakSecretGuessingResistance(SecrecyType):
    subtype = "weak_secret_guessing_resistance"
    # ProVerif reports ``Weak secret <value>`` without a goal id, so each goal
    # needs its own file for that unnamed verdict to be attributable.
    one_goal_per_file = True
    description = ("Offline-guessing resistance for a weak secret (password / "
                   "PIN class): the public transcript gives the attacker no "
                   "successful offline test for the secret. Realized by "
                   "ProVerif's weaksecret mode.")
    requires_assumption = {
        "axis": "primitive",
        "subtypes": ("broken",),
        "why": (
            "Guessing resistance is only a meaningful question for a "
            "low-entropy value: the goal asks whether the public transcript "
            "hands the attacker an offline test for the secret, and "
            "enumeration is only a threat when the candidate space is small "
            "(a password or PIN). Without the entropy assumption in the "
            "claim, the goal degenerates into ordinary secrecy of a value "
            "that is never sent — trivially true and saying nothing."),
    }
