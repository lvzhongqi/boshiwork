"""The canonical apply order, and the fixed section rendered as engine points.

Assumption points are commutative — realizer write sets are disjoint by
contract — so the order carries no meaning and is fixed only for determinism.
World assumptions (assumptions.json's ``world`` section) are a separate tier
applied once by build_world, and never take part in this order.
"""

from __future__ import annotations

from orrery.modules.libschema.model import Point
from orrery.nodes.apply.realizers import VOCAB


def is_structural(p) -> bool:
    """The registry's answer as a plain predicate: the deterministic tiebreak,
    written once so callers cannot disagree about it."""
    return VOCAB.is_structural(p.axis, p.subtype)


def apply_order(points) -> list:
    """The canonical apply order: structural-form points first, then by id.

    Determinism only — the write sets are disjoint, so any order yields the
    same model. Shared by build_root and every scenario's delta. The point
    order inside Scenario, which feeds labels and directory names, is a
    different order and stays untouched.
    """
    return sorted(points, key=lambda p: (
        not is_structural(p),
        p.ref_id or p.axis, p.subtype))


def fixed_points(assumptions) -> list:
    """The fixed section as engine points, flow-state entries included; the
    caller decides what to apply and what to merely record."""
    return [Point(axis=f.axis, subtype=f.subtype, target=f.target, ref_id=f.id)
            for f in assumptions.fixed]
