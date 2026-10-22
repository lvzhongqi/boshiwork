"""Axis primitive (obj: crypto_object) — in what state does a cryptographic
object fail? One axis for every primitive, primitive family, or enumerable
value; the object itself rides in the target, named by ``family``.

Rungs weak to strong: broken (fails outright, no downgrade needed) <
weak_member (the deployed family still holds a negotiable weak member) <
ideal (the flow model state).
"""
from orrery.nodes.apply.realizers.primitive.broken.realizer import Broken
from orrery.nodes.apply.realizers.primitive.weak_member.realizer import WeakMember
from orrery.nodes.apply.realizers.primitive.ideal.realizer import Ideal

__all__ = ["Broken", "WeakMember", "Ideal"]
