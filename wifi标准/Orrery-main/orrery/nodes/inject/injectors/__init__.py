"""The injector registry: collects every leaf injector class and builds the goal
PropertyVocabulary ``PROP_VOCAB`` from their declarations.

One subtype is one directory (injectors/<type>/<subtype>/) holding
``injector.py``, a one-line ``__init__.py`` facade and ``rules.sys.md``. Every
``requires_assumption`` is cross-checked against the assumption vocabulary at
import, so a typo'd axis fails here instead of producing a gate that stops
nothing."""

from __future__ import annotations

from orrery.modules.kbase.properties.catalog import (
    PropertyVocabulary, check_requires_refs,
)
from orrery.nodes.apply.realizers import VOCAB
from orrery.nodes.inject.injectors.authentication.aliveness import Aliveness
from orrery.nodes.inject.injectors.authentication.injective_agreement import (
    InjectiveAgreement,
)
from orrery.nodes.inject.injectors.authentication.non_injective_agreement import (
    NonInjectiveAgreement,
)
from orrery.nodes.inject.injectors.authentication.weak_agreement import (
    WeakAgreement,
)
from orrery.nodes.inject.injectors.base import Injector
from orrery.nodes.inject.injectors.equivalence.indistinguishability import (
    Indistinguishability,
)
from orrery.nodes.inject.injectors.equivalence.observational_equivalence import (
    ObservationalEquivalence,
)
from orrery.nodes.inject.injectors.equivalence.strong_secrecy import StrongSecrecy
from orrery.nodes.inject.injectors.privacy.unlinkability import Unlinkability
from orrery.nodes.inject.injectors.secrecy.basic import Basic
from orrery.nodes.inject.injectors.secrecy.forward_secrecy import ForwardSecrecy
from orrery.nodes.inject.injectors.secrecy.post_compromise import PostCompromise
from orrery.nodes.inject.injectors.secrecy.weak_secret_guessing_resistance import (
    WeakSecretGuessingResistance,
)

# Declaration order is the vocabulary's order: subtypes grouped by type.
_CLASSES: list[type[Injector]] = [
    Basic, ForwardSecrecy, PostCompromise, WeakSecretGuessingResistance,
    Aliveness, WeakAgreement, NonInjectiveAgreement, InjectiveAgreement,
    ObservationalEquivalence, StrongSecrecy, Indistinguishability,
    Unlinkability,
]

def _decl(cls: type[Injector]) -> dict:
    """One class → one vocabulary entry. The leaf directory is the coordinate:
    its name is the subtype, its parent's name is the goal type lowercased (the
    vocabulary spells types Capitalised). A misfiled or renamed leaf raises
    here, at import."""
    leaf = cls._dir()
    if cls.subtype != leaf.name or cls.gtype.lower() != leaf.parent.name:
        raise RuntimeError(
            f"[injectors] {cls.__name__} declares {cls.gtype}.{cls.subtype} but "
            f"lives at {leaf.parent.name}/{leaf.name} — the class fields and the "
            f"directory path must name the same type and subtype")
    return {
        "gtype": cls.gtype, "subtype": cls.subtype, "parties": cls.parties,
        "realization": cls.realization, "description": cls.description,
        "requires_assumption": cls.requires_assumption,
        "is_stub": cls.unimplemented,
    }


INJECTORS: dict[tuple[str, str], type[Injector]] = {}
for _c in _CLASSES:
    _key = (_c.gtype, _c.subtype)
    if _key in INJECTORS:
        raise RuntimeError(f"[injectors] duplicate (gtype, subtype): {_key}")
    INJECTORS[_key] = _c
    # An implemented injector needs its system rules block, rules.sys.md, in
    # whichever directory the class points ``rules_dir`` at.
    if not _c.unimplemented and not (_c.rules_dir() / "rules.sys.md").is_file():
        raise RuntimeError(
            f"[injectors] {_c.gtype}.{_c.subtype}: no prompt file — expected "
            f"rules.sys.md in {_c.rules_dir()}")

PROP_VOCAB = PropertyVocabulary([_decl(c) for c in _CLASSES])
check_requires_refs(PROP_VOCAB, VOCAB)


def injector_for(gtype: str, subtype: str) -> Injector:
    """Instantiate the injector for one (gtype, subtype). Raises RuntimeError if
    the subtype is in the vocabulary but its injection layer is a stub."""
    inj = INJECTORS[(gtype, subtype)]()
    if inj.unimplemented:
        raise RuntimeError(
            f"[injectors] {gtype}.{subtype} is declared in the vocabulary but its "
            f"injection layer is not implemented"
        )
    return inj


__all__ = ["INJECTORS", "PROP_VOCAB", "injector_for", "Injector"]
