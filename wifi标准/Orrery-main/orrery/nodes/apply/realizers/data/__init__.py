"""Axis data (obj: value) — whether, and when, the attacker comes to hold one
secret value; the target's ``of`` names that value and nothing else does.

The ladder, weakest guarantee first: chosen < disclosed <
leaked_after_session < leaked_after_correct_session < none < assumed_secure,
with leaked_in_other_instances beside the leak rungs. Which leak rung a value
can take follows from its lifetime, computed from the model text
(modules/pvtext/lifetime): long-lived values leak after the sessions,
per-session values only in other instances.

Being used is key_reuse, a separate axis. "Party P may be malicious" is not a
subtype either: a corrupt DY participant is ``disclosed`` over each of its
long-lived secrets, one entry per secret.
"""
from orrery.nodes.apply.realizers.data.chosen.realizer import Chosen
from orrery.nodes.apply.realizers.data.disclosed.realizer import Disclosed
from orrery.nodes.apply.realizers.data.leaked_after_session.realizer import LeakedAfterSession
from orrery.nodes.apply.realizers.data.leaked_in_other_instances.realizer import LeakedInOtherInstances
from orrery.nodes.apply.realizers.data.leaked_after_correct_session.realizer import LeakedAfterCorrectSession
from orrery.nodes.apply.realizers.data.none.realizer import NoAccess
from orrery.nodes.apply.realizers.data.assumed_secure.realizer import AssumedSecure

__all__ = ["Chosen", "Disclosed", "LeakedAfterSession",
           "LeakedInOtherInstances", "LeakedAfterCorrectSession",
           "NoAccess", "AssumedSecure"]
