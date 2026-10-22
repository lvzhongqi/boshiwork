"""primitive.ideal: the named cryptographic object behaves ideally, which the
equational theory already gives — a no-op realizer that writes and checks
nothing.
"""

from orrery.nodes.apply.realizers.base import NoopRealizer


class Ideal(NoopRealizer):
    axis = "primitive"
    obj = "crypto_object"
    subtype = "ideal"
    instance_key = "family"
    structural = False
    stronger_than = ("weak_member",)
    params = {
        "family": {"kind": "primitive", "required": False,
                   "note": "which object, when the dimension names one"},
    }
    description = ('The named cryptographic object behaves ideally — the symbolic '
     'default: no inversion, no weak member, no guessable value (the flow '
     'state).')
