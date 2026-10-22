"""role_binding.fixed_roles: this principal occupies the one seat the model
instantiates it in. The closed flow model's own shape."""

from orrery.nodes.world.builders.base import NoopBuilder


class FixedRoles(NoopBuilder):
    axis = "role_binding"
    subtype = "fixed_roles"
    instance_key = "of"
    build_order = 2
    params = {"of": {"kind": "entity",
                     "note": "the principal, named as principals.json spells it"}}
    description = ('The principal occupies only the seat the model instantiates '
                   'it in (the flow state).')
