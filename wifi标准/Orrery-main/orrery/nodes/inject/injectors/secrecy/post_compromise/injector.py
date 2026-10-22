"""Secrecy.post_compromise: kept in the property vocabulary, not wired up in the
injection layer. Declaring it is an explicit error."""
from orrery.nodes.inject.injectors.secrecy.base import SecrecyType


class PostCompromise(SecrecyType):
    subtype = "post_compromise"
    unimplemented = True
    description = ("Post-compromise security: recovery after one party is "
                   "compromised. Not implemented in the injection layer.")
    reason = ("post-compromise security: recovery after one party is compromised. "
              "Needs phase splitting and post-compromise re-negotiation modelling; "
              "neither the prompt nor the checks are written yet")
