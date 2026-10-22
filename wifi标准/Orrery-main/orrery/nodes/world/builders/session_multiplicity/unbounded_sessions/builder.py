"""session_multiplicity.unbounded_sessions: sessions run concurrently without
bound — the axis's flow state, since the closed flow model's main process
already replicates, so nothing is applied."""

from orrery.nodes.world.builders.base import NoopBuilder


class UnboundedSessions(NoopBuilder):
    axis = "session_multiplicity"
    subtype = "unbounded_sessions"
    instance_key = None
    build_order = 3
    params = {}
    description = 'Sessions run concurrently without bound (the flow state).'
