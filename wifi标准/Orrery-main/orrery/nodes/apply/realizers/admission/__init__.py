"""Axis admission (obj: identity_scope): who may obtain a recognised identity
inside one identity scope, ordered open < closed.

The instance is the ``scope`` on the flow model's ``@orrery-idiom`` marker,
and the machinery is projected from that marker. One shared registry is a
single scope taking a single answer; separate client/server stores are
separate scopes that may take different answers.
"""
from orrery.nodes.apply.realizers.admission.open.realizer import AdmissionOpen
from orrery.nodes.apply.realizers.admission.closed.realizer import AdmissionClosed

__all__ = ["AdmissionOpen", "AdmissionClosed"]
