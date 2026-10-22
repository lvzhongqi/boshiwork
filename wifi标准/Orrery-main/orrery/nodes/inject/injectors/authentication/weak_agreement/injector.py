"""Injector for Authentication.weak_agreement: identity only, the logic and the
rules file both live in the type's base."""
from orrery.nodes.inject.injectors.authentication.base import AuthenticationType


class WeakAgreement(AuthenticationType):
    subtype = "weak_agreement"
    description = ("Weak agreement — the subject has run with the asserter; the "
                   "identities agree, the values need not.")
