"""The realizer family: one leaf per assumption subtype, living at
``realizers/<axis>/<subtype>/`` with its prompts beside the class.

A leaf declares its whole vocabulary entry as class attributes, and the
registry in ``__init__`` builds the Vocabulary value straight from those
declarations, so there is no second vocabulary file to keep in step. The
calling logic sits in nodes/apply/node.py.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from orrery.agent.compose import localized, render_file


class Realizer:
    """One assumption subtype: its vocabulary entry declared as class
    attributes, with the prompts beside it.

    An axis is one object class (``obj``) crossed with one capability
    question, and its subtypes are that question's mutually exclusive answers
    about the object instance ``instance_key`` names. ``stronger_than`` holds
    only the direct partial-order edges — the registry computes the closure,
    checks that the axis-level fields agree across siblings, and rejects a leaf
    that leaves ``structural`` at the ``None`` sentinel. ``description`` is
    read by the model (inject renders it), so it follows the prompt rules.
    """

    axis: str = ""
    obj: str = ""
    subtype: str = ""
    structural: bool | None = None
    stronger_than: tuple[str, ...] = ()
    params: dict[str, dict] = {}
    #: A field name, a tuple of them, or None for a global axis; the ellipsis
    #: sentinel means undeclared, which the registry refuses.
    instance_key: str | tuple[str, ...] | None | type(...) = ...
    description: str = ""
    # Which protocols use this subtype is measured off the corpus
    # (api/corpus_usage) rather than declared here.
    conflicts_with: tuple[str, ...] = ()
    is_noop: bool = False
    is_stub: bool = False
    is_code: bool = False
    writings: tuple[str, ...] = ()
    writings_by_lifetime: dict[str, str] = {}

    def apply_code(self, pv: str, target: dict | None) -> str:
        """Apply a deterministic realization without opening an LLM session."""
        raise NotImplementedError(f"[realizer {self.id}] has no code realization")
    @property
    def id(self) -> str:
        return f"{self.axis}.{self.subtype}"

    @classmethod
    def _dir(cls) -> Path:
        """The leaf's own directory: the subtype's coordinate, which the
        registry reads axis/subtype off, and the root of its prompt files."""
        return Path(inspect.getfile(cls)).parent

    def sys_prompt(self, form: str | None = None, lang: str = "en") -> str:
        """The system rules block: ``rules.sys.md``, or
        ``writings/<form>.sys.md`` for a multi-writing subtype, so exactly one
        writing's rules ever reach a session. ``lang="zh"`` reads the leaf's
        ``_zh`` counterpart; a subtype without one raises
        ``FileNotFoundError``, like any missing prompt."""
        if self.writings:
            if form not in self.writings:
                raise KeyError(
                    f"[realizer {self.id}] needs a writing form, one of "
                    f"{sorted(self.writings)}; got {form!r}")
            return render_file(self._dir() / "writings"
                               / localized(f"{form}.sys.md", lang))
        if form is not None:
            raise ValueError(f"[realizer {self.id}] is single-writing; no form applies")
        return render_file(self._dir() / localized("rules.sys.md", lang))

    def verify_applied(self, base_pv: str, new_pv: str,
                       targets: list[dict]) -> list[str]:
        """Subtype-owned verification of the assembled text, run after the
        splice and before the scenario checks; the default has nothing to
        verify. A subtype overrides it when its semantics pins a mechanically
        checkable shape. Problems returned here enter the repair round like any
        other check failure."""
        return []

    def form_from_lifetime(self, lifetime: str) -> str:
        """The writing this subtype takes for a value of the given lifetime
        (``long_lived`` / ``per_session``, computed by pvtext.lifetime).
        Raises when the subtype does not select by lifetime, or when the
        lifetime is absent from the mapping — a backend coverage gap."""
        if not self.writings_by_lifetime:
            raise NotImplementedError(
                f"[realizer {self.id}] does not select its writing by lifetime")
        try:
            return self.writings_by_lifetime[lifetime]
        except KeyError:
            raise KeyError(
                f"[realizer {self.id}] no writing for a {lifetime!r} value — "
                f"a ProVerif-backend coverage gap; covered: "
                f"{sorted(self.writings_by_lifetime)}") from None

    def conflict(self, target, other: "Realizer",
                 other_target, knowledge) -> str | None:
        """The reason this point cannot coexist with ``other`` in one scenario,
        or None when it can (the default).

        A leaf that knows a conflict overrides this; one side knowing is
        enough, because the claims gate asks both directions of every pair.
        ``knowledge`` is reserved for mechanically projected model facts, and
        callers pass an empty mapping today."""
        return None


class NoopRealizer(Realizer):
    """An axis's flow state: no session runs and the model text is left
    exactly as it stands."""

    is_noop = True


class StubRealizer(Realizer):
    """Declared vocabulary with no realization yet: LIB may cite the subtype,
    and a run that must apply it fails loudly at realizer lookup. A stub is
    admitted only for a consumer protocol already in LIB, or to complete an
    axis's documented value grid."""

    is_stub = True


def target_text(target, params: dict) -> str:
    """The target as the one line a prompt shows it on: ``of = PKB``.

    List-valued fields render without Python's brackets and quotes, and the
    kind decides the separator: an ``entity_pair`` (channel's ``link``) reads
    ``A -> B``, carrying the direction of the model's channel names, while an
    ``entity_set`` (role_binding's ``principals``) reads ``A, B``. ``params``
    is the subtype's declared spec; a list in a field it does not declare
    raises instead of being guessed at.
    """
    if not target:
        return "(this assumption carries no target; it is global)"
    return ", ".join(f"{k} = {_target_value(k, v, params)}"
                     for k, v in dict(target).items() if v is not None)


def _target_value(field: str, v, params: dict) -> str:
    if not isinstance(v, (list, tuple)):
        return str(v)
    spec = params.get(field)
    if spec is None:
        raise KeyError(
            f"[realizer] target field {field!r} carries a list but is not in "
            f"the subtype's params {sorted(params)}; a list only renders for a "
            f"declared entity_pair or entity_set")
    sep = " -> " if spec["kind"] == "entity_pair" else ", "
    return sep.join(str(x) for x in v)
