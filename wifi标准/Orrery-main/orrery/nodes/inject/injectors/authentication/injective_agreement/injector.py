"""Injector for Authentication.injective_agreement: identity only, the logic and
the rules file both live in the type's base."""
from orrery.nodes.inject.injectors.authentication.base import AuthenticationType


class InjectiveAgreement(AuthenticationType):
    subtype = "injective_agreement"
    description = ("Injective agreement (the strongest) — one-to-one, "
                   "replay-resistant. Emits inj-event.")
