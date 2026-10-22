"""The realizer registry: it collects the leaves under ``<axis>/<subtype>/``,
validates their declarations at import time, and builds ``VOCAB`` from them.

What the classes declare is the object-level assumption vocabulary; there is
no separate vocabulary file. Subtypes of one axis are mutually exclusive
answers about a single object instance named by ``instance_key``, so a
scenario holds at most one per object. World-level assumptions (role binding,
population, session multiplicity) belong to nodes/world instead.
"""

from __future__ import annotations

from orrery.modules.kbase.assumptions.catalog import Vocabulary
from orrery.nodes.apply.realizers.base import (
    NoopRealizer, Realizer, StubRealizer,
)
from orrery.nodes.apply.realizers.data.chosen import Chosen
from orrery.nodes.apply.realizers.data.disclosed import Disclosed
from orrery.nodes.apply.realizers.data.leaked_after_session import LeakedAfterSession
from orrery.nodes.apply.realizers.data.leaked_in_other_instances import LeakedInOtherInstances
from orrery.nodes.apply.realizers.data.leaked_after_correct_session import LeakedAfterCorrectSession
from orrery.nodes.apply.realizers.data.none import NoAccess
from orrery.nodes.apply.realizers.data.assumed_secure import AssumedSecure
from orrery.nodes.apply.realizers.key_reuse.observed import Observed
from orrery.nodes.apply.realizers.key_reuse.oracle import Oracle
from orrery.nodes.apply.realizers.key_reuse.separated import Separated
from orrery.nodes.apply.realizers.channel.public import Public
from orrery.nodes.apply.realizers.channel.authentic import Authentic
from orrery.nodes.apply.realizers.channel.confidential import Confidential
from orrery.nodes.apply.realizers.channel.secure_nonbinding import SecureNonbinding
from orrery.nodes.apply.realizers.channel.secure import Secure
from orrery.nodes.apply.realizers.admission.open import AdmissionOpen
from orrery.nodes.apply.realizers.admission.closed import AdmissionClosed
from orrery.nodes.apply.realizers.primitive.broken import Broken
from orrery.nodes.apply.realizers.primitive.weak_member import WeakMember
from orrery.nodes.apply.realizers.primitive.ideal import Ideal

# Declaration order is the vocabulary's order; within one axis the subtypes
# run weakest first (Vocabulary validates that).
_CLASSES: list[type[Realizer]] = [
    Chosen, Disclosed, LeakedAfterSession, LeakedInOtherInstances,
    LeakedAfterCorrectSession,
    NoAccess, AssumedSecure,
    Oracle, Observed, Separated,
    Public, Authentic, Confidential, SecureNonbinding, Secure,
    AdmissionOpen, AdmissionClosed,
    Broken, WeakMember, Ideal,
]

_LIFETIMES = ("long_lived", "per_session")


def _decl(cls: type[Realizer]) -> dict:
    """One class -> one vocabulary entry. The coordinate is read off the
    directory path (realizers/<axis>/<subtype>/), and the class's own
    axis/subtype fields must match those two segments, so a misfiled or
    renamed leaf raises RuntimeError here at import."""
    leaf = cls._dir()
    axis_dir, sub_dir = leaf.parent.name, leaf.name
    if cls.axis != axis_dir or cls.subtype != sub_dir:
        raise RuntimeError(
            f"[realizers] {cls.__name__} declares {cls.axis}.{cls.subtype} but "
            f"lives at {axis_dir}/{sub_dir} — the class fields and the "
            f"directory path must name the same axis and subtype")
    if not isinstance(cls.structural, bool):
        raise RuntimeError(
            f"[realizers] {cls.axis}.{cls.subtype}: structural is not declared "
            f"(True when it reshapes the main-process form; unsure -> True)")
    if cls.instance_key is ...:
        raise RuntimeError(
            f"[realizers] {cls.axis}.{cls.subtype}: instance_key is not "
            f"declared — name the param that identifies the object this axis "
            f"answers about, or None for a global axis")
    return {
        "obj": cls.obj, "axis": cls.axis, "subtype": cls.subtype,
        "instance_key": cls.instance_key,
        "structural": cls.structural, "stronger_than": tuple(cls.stronger_than),
        "params": dict(cls.params), "description": cls.description,
        "is_stub": cls.is_stub,
    }


REALIZERS: dict[tuple[str, str], type[Realizer]] = {}
for _c in _CLASSES:
    _key = (_c.axis, _c.subtype)
    if _key in REALIZERS:
        raise RuntimeError(f"[realizers] duplicate (axis, subtype): {_key}")
    REALIZERS[_key] = _c

# Built once from the declarations; the constructor runs the partial-order,
# param-kind and description checks.
VOCAB = Vocabulary([_decl(c) for c in _CLASSES])

# The flow state per axis: the one subtype whose realizer is a noop, i.e. what
# an unmentioned axis defaults to in resolve.world_of. Exactly one per axis.
FLOW_STATE: dict[str, str] = {}
for _c in _CLASSES:
    if _c.is_noop:
        if _c.axis in FLOW_STATE:
            raise RuntimeError(
                f"[realizers] axis {_c.axis!r} declares two noop subtypes, "
                f"{FLOW_STATE[_c.axis]!r} and {_c.subtype!r}; the flow state "
                f"must be unique for 'unmentioned' to mean one thing")
        FLOW_STATE[_c.axis] = _c.subtype
for _a in VOCAB.axes():
    if _a not in FLOW_STATE:
        raise RuntimeError(
            f"[realizers] axis {_a!r} has no noop subtype; every axis needs "
            f"one flow-state value for an unmentioned axis to default to")

# Declared conflicts must name real subtypes: a typo reads as "no conflict"
# and silently lets a contradictory scenario through the claims gate.
for _c in _CLASSES:
    for _other in _c.conflicts_with:
        if _other.count(".") != 1 or tuple(_other.split(".")) not in REALIZERS:
            raise RuntimeError(
                f"[realizers] {_c.axis}.{_c.subtype}: conflicts_with names "
                f"{_other!r}, which is not a declared axis.subtype")
        if _other == f"{_c.axis}.{_c.subtype}":
            raise RuntimeError(
                f"[realizers] {_c.axis}.{_c.subtype}: conflicts_with names "
                f"itself; one point is never its own contradiction")


# Prompt files must exist for every path a session can take, checked at import
# so a drifted form name or a missing file never reaches a session.
for _c in _CLASSES:
    _d = _c._dir()
    if _c.writings:
        # Multi-writing is legal only when the target value's lifetime picks
        # the form; the choice is declared as data, never coded in a method.
        if _c.form_from_lifetime is not Realizer.form_from_lifetime:
            raise RuntimeError(
                f"[realizers] {_c.axis}.{_c.subtype}: overrides a form "
                f"selector in code — declare writings_by_lifetime data instead, "
                f"so the registry can validate it and the coverage checks can "
                f"read it")
        if not _c.writings_by_lifetime:
            raise RuntimeError(
                f"[realizers] {_c.axis}.{_c.subtype}: a multi-writing subtype "
                f"must declare writings_by_lifetime")
        _mapping = _c.writings_by_lifetime
        for _v in _mapping:
            if _v not in _LIFETIMES:
                raise RuntimeError(
                    f"[realizers] {_c.axis}.{_c.subtype}: "
                    f"writings_by_lifetime names unknown lifetime {_v!r}; "
                    f"legal: {list(_LIFETIMES)}")
        if set(_mapping.values()) != set(_c.writings):
            raise RuntimeError(
                f"[realizers] {_c.axis}.{_c.subtype}: the writing mapping "
                f"reaches {sorted(set(_mapping.values()))} but writings "
                f"declares {sorted(_c.writings)} — every writing is reached "
                f"by the mapping and the mapping reaches nothing else")
        for _form in _c.writings:
            if not (_d / "writings" / f"{_form}.sys.md").is_file():
                raise RuntimeError(
                    f"[realizers] {_c.axis}.{_c.subtype}: writing {_form!r} has no "
                    f"prompt file — expected writings/{_form}.sys.md")
    elif not _c.is_noop and not _c.is_stub and not _c.is_code:
        if not (_d / "rules.sys.md").is_file():
            raise RuntimeError(
                f"[realizers] {_c.axis}.{_c.subtype}: no rules.sys.md beside the class "
                f"— a non-noop realizer's session needs its rules block")


def realizer_for(axis: str, subtype: str) -> Realizer:
    cls = REALIZERS[(axis, subtype)]
    if cls.is_stub:
        raise KeyError(
            f"[realizers] {axis}.{subtype} is a stub: the vocabulary is "
            f"declared but no realizer exists yet — implement it before a "
            f"protocol may cite it")
    return cls()


def subtype_is_noop(axis: str, subtype: str) -> bool:
    """Whether this subtype is its axis's flow state (its realizer is a noop).
    A stub is never a noop: citing one is legal here, and the failure waits at
    realizer_for, when it would have to be applied."""
    cls = REALIZERS.get((axis, subtype))
    return cls is not None and cls.is_noop


def check_writing_coverage(points, pv: str) -> None:
    """Check that every multi-writing point in ``points`` has a writing for the
    lifetime of its target value, projected off ``pv``. Raises KeyError on an
    unknown point and ValueError when such a point names no 'of' value.
    Lifetime picks syntax only; it never rejects a subtype on semantics."""
    from orrery.modules.pvtext.lifetime import value_lifetime
    for p in points:
        cls = REALIZERS.get((p.axis, p.subtype))
        if cls is None:
            raise KeyError(
                f"[realizers] unknown point {p.axis}.{p.subtype}; known axes: "
                f"{sorted({a for a, _ in REALIZERS})}")
        lifetime = None
        if cls.writings_by_lifetime:
            of = (p.target or {}).get("of")
            if not of:
                raise ValueError(
                    f"[realizers] {p.axis}.{p.subtype} depends on the target "
                    f"value's lifetime, but the point names no 'of' value")
            lifetime = value_lifetime(pv, of)
        if not cls.writings:
            continue
        cls().form_from_lifetime(lifetime)


__all__ = ["REALIZERS", "VOCAB", "FLOW_STATE", "realizer_for",
           "subtype_is_noop", "check_writing_coverage",
           "Realizer", "NoopRealizer", "StubRealizer"]
