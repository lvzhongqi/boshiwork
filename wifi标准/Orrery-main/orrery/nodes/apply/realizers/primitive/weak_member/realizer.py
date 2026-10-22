"""primitive.weak_member: the deployed family of the named primitive still
contains a weak member a session may negotiate — the downgrade setting.

One idiom for every family: the primitive becomes parameterised over a
Weak/Strong algorithm constant, the weak branch carries that family's
characteristic failure (a colliding hash, a predictable DH element, a
malleable AEAD, a padding-oracle PKE), and the choice is emitted as an event
the goal side can name as its allowed exception. Tampering with a negotiated
parameter in transit is this assumption plus a public network.
"""

from orrery.nodes.apply.realizers.base import Realizer


class WeakMember(Realizer):
    axis = "primitive"
    obj = "crypto_object"
    subtype = "weak_member"
    instance_key = "family"
    structural = False
    stronger_than = ("broken",)
    params = {
        "family": {"kind": "primitive",
                   "note": ("which negotiated family: a hash, an AEAD, a DH "
                            "group set, a PKE scheme, or the protocol's own "
                            "negotiated suite, named as the model or the "
                            "document spells it")},
    }
    description = ('The deployed family of the named primitive contains a weak '
     'member a session may still negotiate: the weak branch fails in that '
     'family\'s characteristic way, and choosing it is marked by an event '
     'the goal side may except.')
