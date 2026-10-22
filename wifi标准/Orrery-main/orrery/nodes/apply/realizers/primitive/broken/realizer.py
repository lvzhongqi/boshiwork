"""primitive.broken: the named cryptographic object fails outright, with no
downgrade needed — the attacker holds a capability the object's ideal
behaviour rules out.

Three object kinds share that semantics with their own writing shapes: a
Diffie-Hellman family or a KEM collapses to an event-gated inversion oracle,
and a low-entropy secret becomes offline-guessable, its binding hoisted to a
top-level private free so the goal side can ask ``weaksecret``.
"""

from orrery.nodes.apply.realizers.base import Realizer


class Broken(Realizer):
    axis = "primitive"
    obj = "crypto_object"
    subtype = "broken"
    instance_key = "family"
    structural = False
    stronger_than = ()
    params = {
        "family": {"kind": "primitive",
                   "note": ("which object: a primitive family (a DH group, a "
                            "KEM) or a low-entropy value, named as the model "
                            "or the document spells it")},
    }
    description = ('The named cryptographic object fails outright: a DH family or '
     'KEM the attacker can invert, or a low-entropy secret the attacker can '
     'enumerate offline. No downgrade is needed.')
