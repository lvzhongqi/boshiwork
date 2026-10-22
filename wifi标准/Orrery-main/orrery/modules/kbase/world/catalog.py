"""The shape of the world vocabulary: what a model's domain may be.

The truth source is the builder declarations in nodes/world/builders; their
registry builds one WorldVocabulary at import time and passes it down as a
parameter. Subtypes on an axis are alternative domains with no strength order,
so an axis carries just one flow state (the value an unmentioned axis takes)
and one build order.
"""
from __future__ import annotations

from orrery.modules.kbase.assumptions.catalog import VALID_PARAM_KINDS, _canon


class WorldVocabulary:
    """The world vocabulary as an immutable value.

    Built from one entry per subtype (keys axis, subtype, instance_key, noop,
    build_order, params, description), in declaration order. Construction checks
    what only the whole set shows: one instance_key, one flow state and one build
    order per axis, and build orders unique across axes.
    """

    def __init__(self, entries: list[dict]):
        self._subs: dict[tuple[str, str], dict] = {}
        self._order: dict[str, list[str]] = {}
        self._key: dict[str, tuple[str, ...] | None] = {}
        self._flow: dict[str, str] = {}
        self._build: dict[str, int] = {}
        for e in entries:
            axis, sub = e["axis"], e["subtype"]
            if (axis, sub) in self._subs:
                raise ValueError(f"[world vocabulary] duplicate (axis, subtype): {(axis, sub)}")
            ik = e["instance_key"]
            ik = None if ik is None else ((ik,) if isinstance(ik, str) else tuple(ik))
            if axis in self._key and self._key[axis] != ik:
                raise ValueError(
                    f"[world vocabulary] axis {axis!r}: instance_key is an "
                    f"axis-level property, but its subtypes declare "
                    f"{self._key[axis]!r} and {ik!r}")
            self._key[axis] = ik
            for f, spec in (e["params"] or {}).items():
                if not isinstance(spec, dict) or spec.get("kind") not in VALID_PARAM_KINDS:
                    raise ValueError(
                        f"[world vocabulary] {axis}.{sub}: params.{f} needs a "
                        f"valid kind, one of {sorted(VALID_PARAM_KINDS)}")
            if not str(e["description"]).strip():
                raise ValueError(f"[world vocabulary] {axis}.{sub}: description is empty")
            if e["noop"]:
                if axis in self._flow:
                    raise ValueError(
                        f"[world vocabulary] axis {axis!r} declares two flow "
                        f"states: {self._flow[axis]!r} and {sub!r}")
                self._flow[axis] = sub
            if axis in self._build and self._build[axis] != e["build_order"]:
                raise ValueError(
                    f"[world vocabulary] axis {axis!r}: build_order is an "
                    f"axis-level property, but its subtypes declare "
                    f"{self._build[axis]} and {e['build_order']}")
            self._build[axis] = e["build_order"]
            self._subs[(axis, sub)] = e
            self._order.setdefault(axis, []).append(sub)

        for axis in self._order:
            if axis not in self._flow:
                raise ValueError(
                    f"[world vocabulary] axis {axis!r} declares no flow state; "
                    f"exactly one subtype per axis is the closed model's shape")
        if len(set(self._build.values())) != len(self._build):
            raise ValueError(
                f"[world vocabulary] build_order must be unique across axes, "
                f"got {self._build}")

    def axes(self) -> list[str]:
        """The axes in build order. The order matters: population reshapes the
        main process and later builders write onto what it left."""
        return sorted(self._order, key=self._build.get)

    def subtypes(self, axis: str) -> list[str]:
        return list(self._order.get(axis, ()))

    def flow_state(self, axis: str) -> str:
        return self._flow[axis]

    def is_noop(self, axis: str, subtype: str) -> bool:
        return self._flow.get(axis) == subtype

    def instance_key(self, axis: str) -> tuple[str, ...] | None:
        return self._key.get(axis)

    def instance_of(self, axis: str, target) -> tuple | None:
        """The object instance a target names, as a canonicalised tuple of the
        axis's instance_key fields; None when the axis is global."""
        key = self._key.get(axis)
        if not key:
            return None
        t = target or {}
        return tuple(_canon(t.get(f)) for f in key)

    def params(self, axis: str, subtype: str) -> dict:
        return dict(self._subs[(axis, subtype)]["params"] or {})

    def required_params(self, axis: str, subtype: str) -> set[str]:
        return {f for f, spec in self.params(axis, subtype).items()
                if spec.get("required", True)}

    def description(self, axis: str, subtype: str) -> str:
        return self._subs[(axis, subtype)]["description"]

    def entries(self) -> list[dict]:
        return [dict(e) for e in self._subs.values()]
