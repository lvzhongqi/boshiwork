"""Injector for Authentication.aliveness: identity only, the logic and the rules
file both live in the type's base."""
from orrery.nodes.inject.injectors.authentication.base import AuthenticationType


class Aliveness(AuthenticationType):
    subtype = "aliveness"
    description = "Aliveness — the subject has run at some point. The weakest level."
