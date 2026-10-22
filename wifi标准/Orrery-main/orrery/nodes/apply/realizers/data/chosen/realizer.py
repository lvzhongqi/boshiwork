"""data.chosen: the named value is selected by the attacker — write access,
the top of the data axis; control includes knowledge, so it sits above
``disclosed``. The value has to be one the world settles: a role parameter or
a role's own draw. For a value the protocol transmits and cryptographically
binds, the channel and the primitives decide and the solver answers.

The lifetime projection (pvtext.lifetime) picks the writing. ``long_lived``
takes ``lifted_parameter``: main's binding for the role parameter becomes a
receive from the public channel — the Lowe man-in-the-middle world on a
credential, the downgrade world on a negotiated parameter. ``per_session``
takes ``replaced_new``: the role's own draw becomes attacker input, the
rigged-RNG world. Both replace the value's source in place under its existing
name.
"""

from orrery.nodes.apply.realizers.base import Realizer


class Chosen(Realizer):
    axis = "data"
    obj = "value"
    subtype = "chosen"
    instance_key = "of"
    structural = True
    writings = ("lifted_parameter", "replaced_new")
    writings_by_lifetime = {"long_lived": "lifted_parameter",
                            "per_session": "replaced_new"}
    params = {
        "of": {"kind": "value_name",
               "note": ("which value, named as the model spells it: a role "
                        "parameter the world configured, or a value the role "
                        "draws itself. A value the protocol sends and binds "
                        "cryptographically is not this assumption's to answer")},
    }
    description = ('The named value is selected by the attacker instead of being '
     'drawn or fixed by its honest holder — the weakest guarantee on this '
     'axis, below `disclosed`, which only lets the attacker read. A configured '
     'value is lifted to attacker input with the honest reference kept for the '
     'goal side; a value the role draws has its draw replaced.')
