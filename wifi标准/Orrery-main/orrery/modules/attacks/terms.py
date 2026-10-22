"""ProVerif terms as a trace prints them, parsed only as far as lining an
attacker's recipe up against the value it evaluated to.

A trace prints every message the attacker sends as ``recipe = value``: the
recipe says how the attacker built it (``aenc(adec(~M_19,~M_1),~M_3)``) and the
value what came out (``aenc(I_B_2,pk(SKB_2))``). Walking the two together, a
position where both carry the same function is one the attacker assembled; a
position where they differ is one it computed, and the value there is something
the attacker derived. That is the only reading made of a term: no equational
theory, no destructor list, nothing model-specific.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: A symbol as ProVerif prints it in a trace: names with instance suffixes
#: (``I_A_3``), attacker slots (``~M_14``), projections (``1-proj-2-tuple``),
#: the weak-secret guess (``@weaksecretcst``), primed variables.
_SYMBOL = re.compile(r"[~@A-Za-z0-9_'.-]+")
_SLOT = re.compile(r"~M(?:_\d+)?")
#: One instance suffix on a name that starts with a letter. A slot (``~M_3``)
#: or a projection (``2-proj-3-tuple``) is not a name and keeps its digits.
_INSTANCE = re.compile(r"(?<![~\w-])([A-Za-z][A-Za-z0-9_']*?)_\d+\b(?!-)")


class TermError(ValueError):
    """A term the trace printed that this reader cannot parse."""


@dataclass(frozen=True)
class Term:
    """``head`` is the function or name, ``""`` for a tuple; ``args`` is
    ``None`` for a bare name and a tuple otherwise (empty for ``f()``)."""

    head: str
    args: tuple["Term", ...] | None = None

    def __str__(self) -> str:
        if self.args is None:
            return self.head
        inner = ",".join(str(a) for a in self.args)
        return f"({inner})" if self.head == "" else f"{self.head}({inner})"

    @property
    def is_slot(self) -> bool:
        """An attacker knowledge slot, ``~M`` or ``~M_k``."""
        return self.args is None and _SLOT.fullmatch(self.head) is not None


def parse(text: str) -> Term:
    """Parse one printed term. Raises TermError on anything else."""
    s = "".join(text.split())
    if not s:
        raise TermError("empty term")
    term, end = _term(s, 0)
    if end != len(s):
        raise TermError(f"unexpected {s[end:]!r} after {s[:end]!r}")
    return term


def _term(s: str, i: int) -> tuple[Term, int]:
    if i < len(s) and s[i] == "(":
        args, i = _args(s, i + 1, ")")
        # A one-element parenthesis is grouping, not a tuple.
        return (args[0] if len(args) == 1 else Term("", args)), i
    m = _SYMBOL.match(s, i)
    if m is None:
        raise TermError(f"expected a name at {s[i:i + 20]!r}")
    head, i = m.group(0), m.end()
    if i < len(s) and s[i] in "([":
        close = ")" if s[i] == "(" else "]"
        args, i = _args(s, i + 1, close)
        return Term(head, args), i
    return Term(head), i


def _args(s: str, i: int, close: str) -> tuple[tuple[Term, ...], int]:
    args: list[Term] = []
    if i < len(s) and s[i] == close:
        return (), i + 1
    while True:
        t, i = _term(s, i)
        args.append(t)
        if i >= len(s):
            raise TermError(f"unclosed {close!r} in {s!r}")
        if s[i] == ",":
            i += 1
            continue
        if s[i] == close:
            return tuple(args), i + 1
        raise TermError(f"unexpected {s[i]!r} in {s!r}")


def split_top(text: str, sep: str = "=") -> tuple[str, str] | None:
    """Split at the first ``sep`` outside any bracket; None when there is none."""
    depth = 0
    for i, c in enumerate(text):
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == sep and depth == 0:
            return text[:i].strip(), text[i + 1:].strip()
    return None


def slots(term: Term) -> list[str]:
    """Every attacker slot the term reads, in order of first appearance."""
    out: list[str] = []

    def walk(t: Term) -> None:
        if t.is_slot:
            if t.head not in out:
                out.append(t.head)
        for a in t.args or ():
            walk(a)

    walk(term)
    return out


def computed(recipe: Term, value: Term) -> list[tuple[Term, Term]]:
    """The positions where the attacker computed rather than assembled, as
    ``(sub-recipe, value it gave)``, outermost first.

    A slot is a message the attacker already holds and a bare name is one it
    knows, so neither is a computation. Two applications of the same function
    with the same arity are assembly, and the walk goes inside. Anything else is
    a computation: the recipe applied something the value no longer shows."""
    if recipe.args is None:
        return []
    if (value.args is not None and recipe.head == value.head
            and len(recipe.args) == len(value.args)):
        out: list[tuple[Term, Term]] = []
        for r, v in zip(recipe.args, value.args):
            out.extend(computed(r, v))
        return out
    return [(recipe, value)]


def display(text: str, keep: frozenset[str] = frozenset()) -> str:
    """A printed term with ProVerif's instance suffixes dropped, for reading:
    ``aenc((I_A_3,A_3),pk(SKB_2))`` reads ``aenc((I_A,A),pk(SKB))``. Slots and
    projections keep their digits, and so does every name in ``keep`` — the
    names the attacker made up (``a``, ``a_1``), which differ only by them.
    Only for showing a person; every lookup uses the printed form."""
    def drop(m: re.Match) -> str:
        return m.group(0) if m.group(0) in keep else m.group(1)
    return _INSTANCE.sub(drop, text)


def names(term: Term) -> set[str]:
    """Every bare name in the term that is not a slot."""
    out: set[str] = set()

    def walk(t: Term) -> None:
        if t.args is None:
            if not t.is_slot:
                out.add(t.head)
            return
        for a in t.args:
            walk(a)

    walk(term)
    return out
