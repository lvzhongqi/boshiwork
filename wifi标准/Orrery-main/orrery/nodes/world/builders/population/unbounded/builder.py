"""population.unbounded: unboundedly many honest principals exist; every
ordinary role slot draws from this population, and the same member may fill
several slots at once, self-pairing included. It speaks about the world, not
about a principal, so it has no target. The named principals stay as drawable
members under their exact names, the issuing stage adds unboundedly many
further members beside them, and infrastructure principals the protocol
distinguishes stay named outside the draw.

The issuing stage is replicated, so a principal's tickets are unbounded. A
ticket is a role slot, and a fixed ticket count caps how many slots one
principal can occupy at once: trace reconstruction then finds no trace for an
attack that needs one more, and the goal comes back `cannot be proved` rather
than `is false`.
"""

from orrery.nodes.world.builders.base import Builder


class Unbounded(Builder):
    axis = "population"
    subtype = "unbounded"
    instance_key = None
    build_order = 1
    params = {}
    description = ('Unboundedly many honest principals exist: the named principals '
                   'stay as drawable members, keeping their stable values under '
                   'their exact names, and unboundedly many further members join '
                   'them. The same member may fill several slots at once, '
                   'self-pairing included; the attacker is outside the population.')
