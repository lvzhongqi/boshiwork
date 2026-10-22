"""Accessor for the primitive material library, kb/primitives/PRIMITIVES_KB.yaml.

Entries hold verbatim ProVerif declarations that land in the flow .pv as-is, so
this is an injection service: normalise a name, fetch declarations by delivery
layer. Load time checks that aliases are globally unique, that requires targets
exist, and that delivery is only render or lookup.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

import orrery

RENDER = "render"
LOOKUP = "lookup"

_KB_PATH = Path(orrery.__file__).parent / "kb" / "primitives" / "PRIMITIVES_KB.yaml"


@dataclass(frozen=True)
class Primitive:
    """One library entry. The decl fields are verbatim ProVerif declarations,
    trailing period included."""

    name: str
    delivery: str
    const_decls: tuple[str, ...] = ()
    fun_decls: tuple[str, ...] = ()
    reduc_decls: tuple[str, ...] = ()
    equation_decls: tuple[str, ...] = ()
    types: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    idiom: str = ""
    description: str = ""

    def all_decls(self) -> list[str]:
        """Every declaration in the order ProVerif accepts: const, fun, reduc,
        equation."""
        return [*self.const_decls, *self.fun_decls,
                *self.reduc_decls, *self.equation_decls]


def _load() -> list[Primitive]:
    raw = yaml.safe_load(_KB_PATH.read_text(encoding="utf-8"))
    out: list[Primitive] = []
    for e in raw["primitives"]:
        decls = e.get("decls", {})
        if e["delivery"] not in (RENDER, LOOKUP):
            raise RuntimeError(
                f"[primitives] {e['name']}: delivery must be render or lookup, "
                f"got {e['delivery']!r}"
            )
        out.append(Primitive(
            name=e["name"],
            delivery=e["delivery"],
            const_decls=tuple(decls.get("const", [])),
            fun_decls=tuple(decls.get("fun", [])),
            reduc_decls=tuple(decls.get("reduc", [])),
            equation_decls=tuple(decls.get("equation", [])),
            types=tuple(e.get("types", [])),
            requires=tuple(e.get("requires", [])),
            aliases=tuple(e.get("aliases", [])),
            idiom=e.get("idiom", ""),
            description=e.get("description", ""),
        ))
    return out


_PRIMITIVES: list[Primitive] = _load()

# Name and alias, lowercased, to Primitive. A collision is an error: it would
# make normalisation ambiguous.
_BY_KEY: dict[str, Primitive] = {}
for _p in _PRIMITIVES:
    for _k in (_p.name, *_p.aliases):
        _kk = _k.strip().lower()
        if _kk in _BY_KEY and _BY_KEY[_kk] is not _p:
            raise RuntimeError(
                f"[primitives] duplicate name or alias {_k!r}: "
                f"{_BY_KEY[_kk].name} collides with {_p.name}; names must be globally unique"
            )
        _BY_KEY[_kk] = _p

for _p in _PRIMITIVES:
    for _req in _p.requires:
        if _req.strip().lower() not in _BY_KEY:
            raise RuntimeError(
                f"[primitives] {_p.name}: requires references unknown primitive {_req!r}"
            )


def lookup_primitive(name: str) -> Primitive | None:
    """Look up by name or alias, case-insensitively; None on a miss."""
    if not isinstance(name, str):
        return None
    return _BY_KEY.get(name.strip().lower())


def iter_render_primitives() -> list[Primitive]:
    """Entries with delivery == render, in declaration order; these are emitted
    into the preamble at start-up."""
    return [p for p in _PRIMITIVES if p.delivery == RENDER]


def all_primitives() -> list[Primitive]:
    """Every entry in the library (render and lookup), in declaration order."""
    return list(_PRIMITIVES)


def _declared_names(decls: tuple[str, ...], prefixes: tuple[str, ...]) -> set[str]:
    """Pull declared symbol names out of verbatim decls: the value name for
    const/free, the function name for fun."""
    out: set[str] = set()
    for d in decls:
        s = d.strip()
        low = s.lower()
        for pre in prefixes:
            if low.startswith(pre):
                head = s[len(pre):].strip().split(":", 1)[0]
                head = head.split("(", 1)[0].rstrip(".").strip()
                out.update(n.strip() for n in head.split(",") if n.strip())
                break
    return out


def library_global_names() -> set[str]:
    """Every top-level symbol the library declares: const/free values plus fun
    names."""
    names: set[str] = set()
    for p in _PRIMITIVES:
        names |= _declared_names(p.const_decls, ("const ", "free "))
        names |= _declared_names(p.fun_decls, ("fun ",))
    return names


def library_function_names() -> set[str]:
    """Names the lookup_function_signature tool can hit: canonical names plus
    aliases."""
    return set(_BY_KEY.keys())
