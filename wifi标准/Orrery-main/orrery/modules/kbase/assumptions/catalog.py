"""The shape of the security-assumption vocabulary.

Each subtype's realizer class under nodes/apply/realizers carries its axis,
structural bit, partial-order edges, target params and description, and the
realizer registry builds one Vocabulary from all of them at import time. This
module defines that value and validates it on construction; it reads no file.

The Vocabulary travels down as a parameter: libschema sits below the nodes
layer and cannot import realizers, so the claims node passes it in.
"""
from __future__ import annotations

# The semantic domains a target param may take; validation dispatches on kind.
# ``entity`` is one principal, ``entity_pair`` an ordered two (a directed link),
# ``entity_set`` an unordered list of two or more; ``value_name`` names a model
# value, ``identity_scope`` an ``@orrery-idiom`` scope, ``primitive`` a
# cryptographic object or family.
VALID_PARAM_KINDS = {"entity", "value_name", "entity_pair",
                     "entity_set", "identity_scope", "phase", "primitive"}


def _canon(v):
    """A hashable form of a target value (a pair or set arrives as a list)."""
    return tuple(v) if isinstance(v, list) else v


class Vocabulary:
    """The assumption vocabulary as an immutable value.

    The axis grid is flat: one axis = one object class (``obj``) crossed with
    one capability question, and its subtypes are that question's mutually
    exclusive answers. Built from one entry per subtype (keys ``obj, axis,
    subtype, instance_key, structural, stronger_than, params, description,
    is_stub``) in declaration order, and construction checks all of it: no
    duplicate (axis, subtype), one object class and one instance key per axis,
    ``stronger_than`` edges naming siblings only, acyclic with exactly one
    weakest subtype, and weakest-first declaration order so the same claims
    expand to a byte-identical scenario order every run. The partial order's
    transitive closure is computed once here and frozen.
    """

    def __init__(self, entries: list[dict]):
        subs: dict[tuple[str, str], dict] = {}
        order: dict[str, list[str]] = {}
        obj: dict[str, str] = {}
        inst: dict[str, str | None] = {}
        for e in entries:
            axis, sub = e["axis"], e["subtype"]
            key = (axis, sub)
            if key in subs:
                raise ValueError(f"[vocabulary] duplicate (axis, subtype): {key}")
            if not str(e.get("obj", "")).strip():
                raise ValueError(
                    f"[vocabulary] {axis}.{sub}: obj is empty — every axis names "
                    f"the object class it constrains (the model element the "
                    f"assumption is about)")
            if axis in obj and obj[axis] != e["obj"]:
                raise ValueError(
                    f"[vocabulary] axis {axis!r} declared with two objects: "
                    f"{obj[axis]!r} and {e['obj']!r}; obj is an axis-level "
                    f"property — one axis asks one question about one object")
            obj[axis] = e["obj"]
            # One field, or several when the object needs more than one
            # coordinate; normalised to a tuple so every reader sees one shape.
            ik = e["instance_key"]
            ik = None if ik is None else (
                (ik,) if isinstance(ik, str) else tuple(ik))
            for f in (ik or ()):
                if f not in (e["params"] or {}):
                    raise ValueError(
                        f"[vocabulary] {axis}.{sub}: instance_key names {f!r}, "
                        f"which is not one of its params "
                        f"{sorted(e['params'] or {})}; the instance key names "
                        f"the field(s) that identify the object")
            if axis in inst and inst[axis] != ik:
                raise ValueError(
                    f"[vocabulary] axis {axis!r}: instance_key is an axis-level "
                    f"property, but its subtypes declare {inst[axis]!r} and "
                    f"{ik!r} — one axis answers about one kind of object")
            inst[axis] = ik
            if not isinstance(e["structural"], bool):
                raise ValueError(
                    f"[vocabulary] {axis}.{sub}: structural must be True or False "
                    f"(True when another point's encoding can depend on what it "
                    f"changes; unsure -> True), got {e['structural']!r}")
            if not str(e["description"]).strip():
                raise ValueError(f"[vocabulary] {axis}.{sub}: description is empty")
            for f, spec in (e["params"] or {}).items():
                if not isinstance(spec, dict) or spec.get("kind") not in VALID_PARAM_KINDS:
                    raise ValueError(
                        f"[vocabulary] {axis}.{sub}: params.{f} needs a valid kind, "
                        f"one of {sorted(VALID_PARAM_KINDS)}")
            subs[key] = e
            order.setdefault(axis, []).append(sub)

        for axis, names in order.items():
            edges = {s: list(subs[(axis, s)]["stronger_than"]) for s in names}
            for s, es in edges.items():
                for w in es:
                    if w not in edges:
                        raise ValueError(
                            f"[vocabulary] {axis}.{s}.stronger_than references unknown "
                            f"subtype {w!r}; this axis has: {sorted(names)}")
            state: dict[str, int] = {}

            def visit(x, path):
                if state.get(x) == 1:
                    raise ValueError(
                        f"[vocabulary] {axis}: stronger_than has a cycle: "
                        + " -> ".join(path + [x]))
                if state.get(x) == 2:
                    return
                state[x] = 1
                for y in edges[x]:
                    visit(y, path + [x])
                state[x] = 2

            for s in names:
                visit(s, [])
            weakest = [s for s, es in edges.items() if not es]
            if len(weakest) != 1:
                raise ValueError(
                    f"[vocabulary] axis {axis!r} must have exactly one weakest subtype "
                    f"(no stronger_than), got {weakest}")

        closure: dict[tuple[str, str], frozenset[str]] = {}
        for (axis, sub), e in subs.items():
            seen: set[str] = set()
            stack = list(e["stronger_than"])
            while stack:
                x = stack.pop()
                if x not in seen:
                    seen.add(x)
                    stack.extend(subs[(axis, x)]["stronger_than"])
            closure[(axis, sub)] = frozenset(seen)

        # Declaration order must be a linear extension of the partial order:
        # nothing earlier may be stronger than something later.
        for axis, names in order.items():
            for a in range(len(names)):
                for b in range(a + 1, len(names)):
                    if names[b] in closure[(axis, names[a])]:
                        raise ValueError(
                            f"[vocabulary] {axis}: subtypes must be declared weakest "
                            f"first, but {names[a]!r} is stronger than {names[b]!r} "
                            f"and comes before it")

        self._subs = subs
        self._order = order
        self._obj = obj
        self._inst = inst
        self._closure = closure

    # ── lookups; unknown names raise with the known set ─────────────────────

    def _entry(self, axis: str, subtype: str) -> dict:
        if axis not in self._order:
            raise KeyError(f"[vocabulary] unknown axis {axis!r}; known: {sorted(self._order)}")
        e = self._subs.get((axis, subtype))
        if e is None:
            raise KeyError(
                f"[vocabulary] axis {axis!r} has no subtype {subtype!r}; "
                f"known: {sorted(self._order[axis])}")
        return e

    def axes(self) -> list[str]:
        """Every axis name, in declaration order. Axis names are globally
        unique."""
        return list(self._order)

    def obj_of(self, axis: str) -> str:
        """The model element the axis constrains (a long-term key, a
        principal, a channel...), for display and documentation only. Two axes
        may share an object and ask different questions about it. Raises
        KeyError on an unknown axis."""
        if axis not in self._obj:
            raise KeyError(f"[vocabulary] unknown axis {axis!r}; known: {sorted(self._order)}")
        return self._obj[axis]

    def dimension_values(self, axis: str) -> list[str]:
        """The subtype names of one axis, in declaration order (weakest
        first). Includes stubs: the vocabulary says which values exist, not
        which are implemented."""
        if axis not in self._order:
            raise KeyError(f"[vocabulary] unknown axis {axis!r}; known: {sorted(self._order)}")
        return list(self._order[axis])

    def instance_key(self, axis: str) -> tuple[str, ...] | None:
        """Which target field(s) name the object instance this axis answers
        about, as a tuple (None = a global axis, one answer per protocol).

        This is what "one answer per object" is keyed on: only the identifying
        fields, never a qualifier like ``phase``, since keying on a qualifier
        would let two points about one object pass as two objects. Several
        fields are allowed when an object needs several coordinates."""
        if axis not in self._inst:
            raise KeyError(f"[vocabulary] unknown axis {axis!r}; known: {sorted(self._order)}")
        return self._inst[axis]

    def instance_of(self, axis: str, target) -> object:
        """The object a point is about: the instance key's value(s) as a
        tuple, or None for a global axis and for a target naming no instance.
        Two points sharing (axis, instance) are two answers to one question
        and cannot both hold."""
        key = self.instance_key(axis)
        if key is None:
            return None
        vals = tuple(_canon(( target or {}).get(f)) for f in key)
        return None if all(v is None for v in vals) else vals

    def is_structural(self, axis: str, subtype: str) -> bool:
        """True when another point's encoding can depend on what this subtype
        changes. The scenario stage consumes it for apply order."""
        return self._entry(axis, subtype)["structural"]

    def is_stub(self, axis: str, subtype: str) -> bool:
        """True when the subtype is declared vocabulary with no realizer yet."""
        return self._entry(axis, subtype)["is_stub"]

    def description(self, axis: str, subtype: str) -> str:
        """The subtype's one-sentence meaning, whitespace-collapsed. Prompts
        listing a scenario's assignment attach it to each line, because a bare
        subtype name such as ``any_roles`` says nothing about the world."""
        return " ".join(str(self._entry(axis, subtype)["description"]).split())

    def params(self, axis: str, subtype: str) -> dict:
        """The target field spec: field -> {kind, required?, note}."""
        return dict(self._entry(axis, subtype)["params"] or {})


    def domain_error(self, axis: str, subtype: str, target) -> str | None:
        """The value-domain check on a target, as a message or None.

        Only ``entity_pair`` can be checked without the model text: it is a
        two-name list of distinct endpoints. Entity and value names are open
        names that only the model text can confirm."""
        if not isinstance(target, dict):
            return None
        for f, spec in self.params(axis, subtype).items():
            if f not in target:
                continue
            kind, v = spec.get("kind"), target[f]
            if kind == "entity_pair":
                if (not isinstance(v, list) or len(v) != 2
                        or not all(isinstance(x, str) for x in v)):
                    return (f"target.{f} is {v!r}; an entity_pair field is the "
                            f"directed link as a two-name list, e.g. [\"A\", \"B\"]")
                if v[0] == v[1]:
                    return (f"target.{f} is {v!r}; a link's two endpoints are "
                            f"distinct principals")
        return None

    def required_params(self, axis: str, subtype: str) -> set[str]:
        """The required target fields — the applicability test: a subtype
        applies to a target iff the target supplies all of them."""
        return {f for f, spec in self.params(axis, subtype).items()
                if spec.get("required", True)}

    def stronger_than(self, axis: str, subtype: str) -> frozenset[str]:
        """Which subtypes this one is stronger than, as the transitive closure
        of the direct edges the declarations write. "A is stronger than B"
        means any security goal holding under B also holds under A; an empty
        result means weakest on the axis, or incomparable with the rest.
        """
        self._entry(axis, subtype)
        return self._closure[(axis, subtype)]

    def compare(self, axis: str, a: str, b: str) -> int:
        """Relative strength on one axis: 1 if a is stronger than b, -1 if b
        is stronger than a, 0 if incomparable or the same. Meaningful only
        within one axis."""
        if a == b:
            return 0
        if b in self.stronger_than(axis, a):
            return 1
        if a in self.stronger_than(axis, b):
            return -1
        return 0
