"""population.named_set: the world holds exactly the principals the model
names, and no others. The closed flow model's own shape."""

from orrery.nodes.world.builders.base import NoopBuilder


class NamedSet(NoopBuilder):
    axis = "population"
    subtype = "named_set"
    instance_key = None
    build_order = 1
    params = {}
    description = ('The world holds exactly the named principals and no others '
                   '(the flow state).')
