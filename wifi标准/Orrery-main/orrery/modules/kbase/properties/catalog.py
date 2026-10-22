"""The shape of the security-goal vocabulary.

The truth source is the injector declarations in nodes/inject/injectors: a
type's base class carries the type-level facts, each subtype leaf its own. The
injector registry builds one PropertyVocabulary at import time and passes it
down to libschema, which sits below the nodes layer. Nothing here reads a file.
"""
from __future__ import annotations

VALID_PARTIES = {"holders", "asserter_subject", "free", "subjects"}
VALID_REALIZATION = {
    "exposure_driven", "correspondence", "observational_equivalence",
    "unimplemented",
}


class PropertyVocabulary:
    """The goal vocabulary as an immutable value.

    Built from one entry per subtype (keys gtype, subtype, parties, realization,
    description, requires_assumption, is_stub), in declaration order. Construction
    rejects a duplicate (type, subtype), an illegal or type-inconsistent
    parties/realization, an empty description and a malformed requires_assumption.
    """

    def __init__(self, entries: list[dict]):
        subs: dict[tuple[str, str], dict] = {}
        order: dict[str, list[str]] = {}
        type_facts: dict[str, tuple[str, str]] = {}
        for e in entries:
            gtype, sub = e["gtype"], e["subtype"]
            key = (gtype, sub)
            if key in subs:
                raise ValueError(f"[prop-vocabulary] duplicate (type, subtype): {key}")
            if e["parties"] not in VALID_PARTIES:
                raise ValueError(
                    f"[prop-vocabulary] {gtype}.{sub}: parties must be one of "
                    f"{sorted(VALID_PARTIES)}, got {e['parties']!r}")
            if e["realization"] not in VALID_REALIZATION:
                raise ValueError(
                    f"[prop-vocabulary] {gtype}.{sub}: realization must be one of "
                    f"{sorted(VALID_REALIZATION)}, got {e['realization']!r}")
            facts = (e["parties"], e["realization"])
            if gtype in type_facts and type_facts[gtype] != facts:
                raise ValueError(
                    f"[prop-vocabulary] type {gtype!r} declares two different "
                    f"(parties, realization) pairs: {type_facts[gtype]} and {facts} — "
                    f"type-level facts belong on the type base class, once")
            type_facts[gtype] = facts
            if not str(e["description"]).strip():
                raise ValueError(f"[prop-vocabulary] {gtype}.{sub}: description is empty")
            self._check_requires(gtype, sub, e.get("requires_assumption"))
            subs[key] = e
            order.setdefault(gtype, []).append(sub)
        self._subs = subs
        self._order = order
        self._type_facts = type_facts

    @staticmethod
    def _check_requires(gtype, sub, req):
        if req is None:
            return
        where = f"{gtype}.{sub}"
        if not isinstance(req, dict):
            raise ValueError(f"[prop-vocabulary] {where}.requires_assumption must be a dict")
        if not isinstance(req.get("axis"), str) or not req["axis"].strip():
            raise ValueError(f"[prop-vocabulary] {where}.requires_assumption is missing axis")
        s = req.get("subtypes")
        if not isinstance(s, (list, tuple)) or not s or not all(isinstance(x, str) for x in s):
            raise ValueError(
                f"[prop-vocabulary] {where}.requires_assumption.subtypes must be a "
                f"non-empty list of strings")
        if not str(req.get("why", "")).strip():
            raise ValueError(
                f"[prop-vocabulary] {where}.requires_assumption is missing why; the "
                f"reason is printed verbatim when this gate rejects a claim, and a "
                f"gate with no reason just gets worked around")

    def _entry(self, gtype: str, subtype: str) -> dict:
        if gtype not in self._order:
            raise KeyError(
                f"[prop-vocabulary] unknown type {gtype!r}; known: {sorted(self._order)}")
        e = self._subs.get((gtype, subtype))
        if e is None:
            raise KeyError(
                f"[prop-vocabulary] type {gtype!r} has no subtype {subtype!r}; "
                f"known: {sorted(self._order[gtype])}")
        return e

    def types(self) -> list[str]:
        return list(self._order)

    def subtypes_of(self, gtype: str) -> list[str]:
        if gtype not in self._order:
            raise KeyError(
                f"[prop-vocabulary] unknown type {gtype!r}; known: {sorted(self._order)}")
        return list(self._order[gtype])

    def parties_shape(self, gtype: str) -> str:
        """A type's parties shape: holders / asserter_subject / subjects / free."""
        if gtype not in self._type_facts:
            raise KeyError(
                f"[prop-vocabulary] unknown type {gtype!r}; known: {sorted(self._order)}")
        return self._type_facts[gtype][0]

    def realization(self, gtype: str) -> str:
        """A type's realization strategy key for the engine."""
        if gtype not in self._type_facts:
            raise KeyError(
                f"[prop-vocabulary] unknown type {gtype!r}; known: {sorted(self._order)}")
        return self._type_facts[gtype][1]

    def is_stub(self, gtype: str, subtype: str) -> bool:
        """True when the subtype is declared vocabulary with no injection layer
        wired up; callers turn using it into an explicit error."""
        return self._entry(gtype, subtype)["is_stub"]

    def description(self, gtype: str, subtype: str) -> str:
        return " ".join(str(self._entry(gtype, subtype)["description"]).split())

    def requires_assumption(self, gtype: str, subtype: str) -> dict | None:
        """The assumption a subtype must be paired with, as {axis, subtypes,
        why}, or None when none is declared. libschema.validate uses it to gate
        claims (a missing pairing is an error); user 2's traversal of the
        assumption space uses it to pin that axis out of the search.
        """
        if not subtype:
            return None
        e = self._subs.get((gtype, subtype))
        return None if e is None else e.get("requires_assumption")


def check_requires_refs(prop_vocab: PropertyVocabulary, vocab) -> None:
    """Check that every requires_assumption points at an axis and subtypes the
    assumption vocabulary really has; raises ValueError on the first miss.
    Called from the injector registry at import, the one place holding both
    vocabularies. A typo here yields a gate that stops the wrong claims."""
    axes = set(vocab.axes())
    for gtype in prop_vocab.types():
        for sub in prop_vocab.subtypes_of(gtype):
            req = prop_vocab.requires_assumption(gtype, sub)
            if not req:
                continue
            if req["axis"] not in axes:
                raise ValueError(
                    f"[prop-vocabulary] {gtype}.{sub}.requires_assumption references "
                    f"unknown axis {req['axis']!r}; known: {sorted(axes)}")
            known = set(vocab.dimension_values(req["axis"]))
            bad = [s for s in req["subtypes"] if s not in known]
            if bad:
                raise ValueError(
                    f"[prop-vocabulary] {gtype}.{sub}.requires_assumption references "
                    f"subtypes {bad} that axis {req['axis']} does not have; "
                    f"known: {sorted(known)}")
