"""session_multiplicity.single_session: the world runs one session per role —
the one-shot ceremony setting, where cross-session interleaving is out of the
threat model. The writing speaks about the world as a whole: it drops the
replication in front of the session group, one construct shared by every role.

Extraction trigger: a ceremony the document describes as happening once.
"""

from orrery.nodes.world.builders.base import Builder


class SingleSession(Builder):
    axis = "session_multiplicity"
    subtype = "single_session"
    instance_key = None
    build_order = 3
    preserves_inventory = True
    params = {}
    description = ('The world runs exactly one session per role; cross-session '
                   'interleaving is out of the threat model.')
