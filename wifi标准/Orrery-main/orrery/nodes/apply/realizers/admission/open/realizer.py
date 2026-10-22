"""admission.open: the attacker obtains its own legitimate participation
information and every consumer in one recognition scope accepts it, without
impersonating a named honest party or learning its secrets. Other scopes are
untouched.

Extracted on open registration, an open PKI, a dishonest but legitimate
participant, or an attacker-held valid certificate or key. A flow may realise
admission through a registry, certificate issuance, pre-provisioned material
or checks against named honest values, so realization is one sighted LLM
session that reads the whole model and makes every producer and consumer edit.
"""

from orrery.nodes.apply.realizers.base import Realizer


class AdmissionOpen(Realizer):
    axis = "admission"
    obj = "identity_scope"
    subtype = "open"
    instance_key = "scope"
    structural = True
    stronger_than = ()
    params = {
        "scope": {"kind": "identity_scope",
                  "note": ("the lower_snake_case recognition scope to open; "
                           "the model may realise it through one mechanism or "
                           "several connected mechanisms")},
    }
    description = (
        "The attacker can obtain its own legitimate participation information "
        "and every consumer in the named recognition scope accepts it; named "
        "honest parties and their secrets remain intact."
    )
