"""Axis key_reuse (obj: secret_value) — what a second use of this key gives
the attacker, without the attacker ever holding the key.

Rungs weak to strong: oracle < observed < separated. The data axis asks a
different question about the same value (does the attacker come to hold it),
and both answers can hold at once about one key, so the two stay separate.
"""
from orrery.nodes.apply.realizers.key_reuse.observed.realizer import Observed
from orrery.nodes.apply.realizers.key_reuse.oracle.realizer import Oracle
from orrery.nodes.apply.realizers.key_reuse.separated.realizer import Separated

__all__ = ["Observed", "Oracle", "Separated"]
