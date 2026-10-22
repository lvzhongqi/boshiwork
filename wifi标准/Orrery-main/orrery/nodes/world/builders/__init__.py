"""The builder registry, and — since the leaves carry their own declarations —
the construction point of the world vocabulary.

The grid mirrors the realizer grid: ``builders/<axis>/<subtype>/`` with
``builder.py``, a facade ``__init__.py`` and ``rules.sys.md``. Three axes
constrain the analysis as a whole: population, role_binding and
session_multiplicity. Their subtypes are alternatives rather than a ladder, so
the only order declared is ``build_order``, the order build_world applies the
axes in.

Import time checks every declaration, so a broken leaf cannot reach a run:
axis/subtype match the directory path, ``instance_key`` names one of the leaf's
own params, ``instance_key`` and ``build_order`` agree across an axis and
``build_order`` is unique among axes, each axis holds exactly one noop subtype,
and every subtype that builds something has its ``rules.sys.md``.
"""

from __future__ import annotations

from orrery.modules.kbase.assumptions.catalog import VALID_PARAM_KINDS
from orrery.modules.kbase.world.catalog import WorldVocabulary
from orrery.nodes.world.builders.base import Builder, NoopBuilder
from orrery.nodes.world.builders.population.named_set import NamedSet
from orrery.nodes.world.builders.population.unbounded import Unbounded
from orrery.nodes.world.builders.role_binding.fixed_roles import FixedRoles
from orrery.nodes.world.builders.role_binding.any_roles import AnyRoles
from orrery.nodes.world.builders.session_multiplicity.unbounded_sessions import (
    UnboundedSessions,
)
from orrery.nodes.world.builders.session_multiplicity.single_session import (
    SingleSession,
)

# Declaration order is the vocabulary's order; each axis lists its noop first.
_CLASSES: list[type[Builder]] = [
    NamedSet, Unbounded,
    FixedRoles, AnyRoles,
    UnboundedSessions, SingleSession,
]


def _check(cls: type[Builder]) -> None:
    leaf = cls._dir()
    axis_dir, sub_dir = leaf.parent.name, leaf.name
    if cls.axis != axis_dir or cls.subtype != sub_dir:
        raise RuntimeError(
            f"[builders] {cls.__name__} declares {cls.axis}.{cls.subtype} but "
            f"lives at {axis_dir}/{sub_dir} — the class fields and the "
            f"directory path must name the same axis and subtype")
    if cls.instance_key is ...:
        raise RuntimeError(
            f"[builders] {cls.axis}.{cls.subtype}: instance_key is not declared "
            f"— name the param that identifies the object this axis speaks "
            f"about, or None for an axis about the world as a whole")
    for f in _key_tuple(cls.instance_key):
        if f not in (cls.params or {}):
            raise RuntimeError(
                f"[builders] {cls.axis}.{cls.subtype}: instance_key names {f!r}, "
                f"which is not one of its params {sorted(cls.params or {})}")
    for f, spec in (cls.params or {}).items():
        if not isinstance(spec, dict) or spec.get("kind") not in VALID_PARAM_KINDS:
            raise RuntimeError(
                f"[builders] {cls.axis}.{cls.subtype}: params.{f} needs a valid "
                f"kind, one of {sorted(VALID_PARAM_KINDS)}")
    if not str(cls.description).strip():
        raise RuntimeError(f"[builders] {cls.axis}.{cls.subtype}: description is empty")
    if not cls.noop and not (leaf / "rules.sys.md").is_file():
        raise RuntimeError(
            f"[builders] {cls.axis}.{cls.subtype}: no rules.sys.md in {leaf} — a "
            f"subtype that builds something needs the rules that build it")


def _key_tuple(ik) -> tuple[str, ...]:
    return () if ik is None else ((ik,) if isinstance(ik, str) else tuple(ik))


BUILDERS: dict[tuple[str, str], Builder] = {}
_AXIS_ORDER: dict[str, int] = {}
_AXIS_KEY: dict[str, tuple[str, ...] | None] = {}
_AXIS_SUBTYPES: dict[str, list[str]] = {}
_AXIS_NOOP: dict[str, str] = {}

for _cls in _CLASSES:
    _check(_cls)
    _key = (_cls.axis, _cls.subtype)
    if _key in BUILDERS:
        raise RuntimeError(f"[builders] duplicate (axis, subtype): {_key}")
    BUILDERS[_key] = _cls()
    _ik = _key_tuple(_cls.instance_key) or None
    if _cls.axis in _AXIS_KEY and _AXIS_KEY[_cls.axis] != _ik:
        raise RuntimeError(
            f"[builders] axis {_cls.axis!r}: instance_key is an axis-level "
            f"property, but its subtypes declare {_AXIS_KEY[_cls.axis]!r} and "
            f"{_ik!r}")
    _AXIS_KEY[_cls.axis] = _ik
    if _cls.axis in _AXIS_ORDER and _AXIS_ORDER[_cls.axis] != _cls.build_order:
        raise RuntimeError(
            f"[builders] axis {_cls.axis!r}: build_order is an axis-level "
            f"property, but its subtypes declare {_AXIS_ORDER[_cls.axis]} and "
            f"{_cls.build_order}")
    _AXIS_ORDER[_cls.axis] = _cls.build_order
    _AXIS_SUBTYPES.setdefault(_cls.axis, []).append(_cls.subtype)
    if _cls.noop:
        if _cls.axis in _AXIS_NOOP:
            raise RuntimeError(
                f"[builders] axis {_cls.axis!r} declares two flow states: "
                f"{_AXIS_NOOP[_cls.axis]!r} and {_cls.subtype!r}")
        _AXIS_NOOP[_cls.axis] = _cls.subtype

for _axis, _subs in _AXIS_SUBTYPES.items():
    if _axis not in _AXIS_NOOP:
        raise RuntimeError(
            f"[builders] axis {_axis!r} declares no flow state; exactly one "
            f"subtype per axis is the closed model's own shape")
if len(set(_AXIS_ORDER.values())) != len(_AXIS_ORDER):
    raise RuntimeError(
        f"[builders] build_order must be unique across axes, got {_AXIS_ORDER}")

#: the world vocabulary built from the declarations above; the nodes layer
#: hands it down to libschema, which cannot import upward.
WORLD_VOCAB = WorldVocabulary([
    {"axis": c.axis, "subtype": c.subtype, "instance_key": c.instance_key,
     "noop": c.noop, "build_order": c.build_order, "params": c.params,
     "description": c.description}
    for c in _CLASSES])

#: the axes in the order build_world applies them
WORLD_AXES: tuple[str, ...] = tuple(sorted(_AXIS_ORDER, key=_AXIS_ORDER.get))
#: axis -> its subtypes, noop first
WORLD_SUBTYPES: dict[str, tuple[str, ...]] = {
    a: tuple(s) for a, s in _AXIS_SUBTYPES.items()}
#: axis -> the subtype that is the closed flow model's own shape
WORLD_FLOW_STATE: dict[str, str] = dict(_AXIS_NOOP)
#: axis -> the param(s) naming the object instance, or None for a global axis
WORLD_INSTANCE_KEY: dict[str, tuple[str, ...] | None] = dict(_AXIS_KEY)


def builder_for(axis: str, subtype: str) -> Builder:
    """The registered builder for one (axis, subtype); KeyError if unknown."""
    try:
        return BUILDERS[(axis, subtype)]
    except KeyError:
        known = sorted(WORLD_SUBTYPES.get(axis, ()))
        raise KeyError(
            f"[builders] no builder for {axis}.{subtype}; "
            + (f"axis {axis!r} has {known}" if known
               else f"the world axes are {sorted(WORLD_SUBTYPES)}")) from None


def is_world_axis(axis: str) -> bool:
    """True for an axis of the world vocabulary, false for an object-level one."""
    return axis in WORLD_SUBTYPES


def world_is_noop(axis: str, subtype: str) -> bool:
    """True for the one subtype per axis that is the flow model's own shape."""
    return WORLD_FLOW_STATE.get(axis) == subtype


__all__ = [
    "BUILDERS", "Builder", "NoopBuilder", "WORLD_VOCAB", "WORLD_AXES", "WORLD_SUBTYPES",
    "WORLD_FLOW_STATE", "WORLD_INSTANCE_KEY",
    "builder_for", "is_world_axis", "world_is_noop",
]
