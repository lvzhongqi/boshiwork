"""Privacy.unlinkability: a one-goal biprocess analysed for observational
equivalence.

Identity confidentiality — can an eavesdropper learn who is running — is a
different goal, expressed as Secrecy of the identity credential."""
from orrery.nodes.inject.injectors.privacy.base import PrivacyType


class Unlinkability(PrivacyType):
    subtype = "unlinkability"
    perturbs_model = True
    one_goal_per_file = True
    description = ("Unlinkability — an attacker cannot distinguish two sessions "
                   "of the same subject from sessions of different subjects.")
