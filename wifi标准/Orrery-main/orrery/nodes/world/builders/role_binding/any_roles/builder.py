"""role_binding.any_roles: this principal may occupy any seat the model
instantiates with a listed principal, both ends of a session included.

One entry per principal: admission to the other seats is asymmetric in practice
— an authentication server is never a peer — so the target names the principal
and only the named ones enter the enumeration. The expansion re-seats the input
model's principals over the input model's material, leaving the inventory of
identities and long-term values unchanged; a pairwise shared value is one value
in every lookup order.
"""

from orrery.nodes.world.builders.base import Builder


class AnyRoles(Builder):
    axis = "role_binding"
    subtype = "any_roles"
    instance_key = "of"
    build_order = 2
    preserves_inventory = True
    params = {"of": {"kind": "entity",
                     "note": "the principal, named as principals.json spells it"}}
    description = ('The principal may occupy any seat the model instantiates with '
                   'a listed principal, self-pairing included.')
