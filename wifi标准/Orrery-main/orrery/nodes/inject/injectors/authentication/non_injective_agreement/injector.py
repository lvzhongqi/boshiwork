"""Injector for Authentication.non_injective_agreement: identity only, the logic
and the rules file both live in the type's base."""
from orrery.nodes.inject.injectors.authentication.base import AuthenticationType


class NonInjectiveAgreement(AuthenticationType):
    subtype = "non_injective_agreement"
    description = ("Non-injective agreement — both roles agree on the goal's "
                   "complete values vector, but without a one-to-one "
                   "correspondence, so replay is possible.")
