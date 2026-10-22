"""Stand-in names for the long or repeated terms of an attack script.

ProVerif prints every message fully expanded: a certificate is spelt out each
time it is sent, and a TLS flight runs to thousands of characters. Here such a
term is given a name once, in a definition drawn on the lifeline of whoever
made it, and every later occurrence carries the name alone. Nothing is
rewritten: expanding every name gives back ProVerif's term character for
character.

A name comes from the model first. A session that ran ``let binding_A =
sign(…)`` bound that very value, so the value is called ``binding_A``. What
the model never bound is named here: a whole message ``msg<n>`` after the step
that first carries it, anything inside one after its outermost function,
``hash1``, ``hash2``. A value the attacker made has no source of its own; when
the session it was sent to bound it, it takes that session's name with its
``_recv`` marker dropped and a prime added — ``SUCI′`` is the attacker's SUCI,
not the UE's.

A term is named when the model named it, or when it is still long with the
names inside it standing in, or occurs more than once; the short and the
single-use stay written out. A name the model uses for two different values
is told apart by primes, as a textbook tells a second session of A as A′.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from orrery.modules.attacks.terms import Term, TermError, parse, split_top

#: A term this long or longer, written out, is named even if it occurs once.
LONG = 30

_TYPE = re.compile(r":\s*[A-Za-z_]\w*")
_INSTANCE = re.compile(r"_\d+$")
_RECEIVED = re.compile(r"_(recv|rcv|received)$")
SETUP = ""                          #: the lane of what the initial process made


@dataclass
class Definition:
    lane: str                       #: whose lifeline it is drawn on; SETUP before any session
    name: str
    body: str                       #: the term, names inside it standing in
    value: str                      #: the term written out, display form
    #: ``name`` stands in for a term; ``derive`` is a value the attacker
    #: worked out, ``body`` how; ``new`` is a name the attacker made up.
    kind: str = "name"


def bindings(rows_by_node, lane_of: Callable[[str], str | None]
             ) -> dict[str, list[tuple[float, str, str]]]:
    """Every composite value, tuples included, a ``let`` bound, as ``printed
    value → [(time, lane, variable)]``; ``rows_by_node`` is ``(node time, node
    path, rows)``. A pattern ``let (x, y) = (a, b)`` binds each part."""
    out: dict[str, list[tuple[float, str, str]]] = {}
    for time, path, rows in rows_by_node:
        lane = lane_of(path)
        for r in rows:
            if r.word != "let":
                continue
            parts = split_top(r.text)
            if parts is None:
                continue
            try:
                pattern, value = parse(_TYPE.sub("", parts[0])), parse(parts[1])
            except TermError:
                continue

            def bind(p: Term, v: Term) -> None:
                if p.args is None:
                    if v.args is not None:
                        out.setdefault(str(v), []).append(
                            (time, SETUP if lane is None else lane,
                             _INSTANCE.sub("", p.head)))
                    return
                if p.head == v.head and v.args and len(p.args) == len(v.args):
                    for a, b in zip(p.args, v.args):
                        bind(a, b)

            bind(pattern, value)
    return out


def _subterms(t: Term):
    yield t
    for a in t.args or ():
        yield from _subterms(a)


def stand_ins(steps: list[tuple[int, str, bool, str]],
              sources: dict[str, list[tuple[float, str, str]]],
              show: Callable[[str], str], read: list[str] = ()
              ) -> tuple[list[str], list[list[Definition]], list[Definition],
                         dict[str, str]]:
    """Name the terms of ``steps``, each ``(n, sender lane, attacker made it,
    printed value)``; ``read`` is every value the attacker's recipes read, an
    occurrence as much as a message is. Returns each step's label, the
    definitions each step brings in (drawn with it), those the initial process
    made (drawn before the first step), and every name as ``printed value →
    name``."""
    terms = [parse(v) for _, _, _, v in steps]
    seen = Counter(str(x) for t in terms for x in _subterms(t) if x.args)
    seen.update(v for v in read if parse(v).args)
    names: dict[str, str] = {}                  # printed value → name
    taken: set[str] = set()
    setup: list[Definition] = []
    coined: Counter = Counter()

    def unique(base: str) -> str:
        name = base
        while name in taken:
            name += "′"
        taken.add(name)
        return name

    def source(value: str, sender: str, attacker: bool) -> tuple[str, str] | None:
        """``(lane, name)`` from the model: bound where it was made — the
        sending session, or the initial process — or, for a value the
        attacker made, where it was received."""
        found = sources.get(value, [])
        own = [b for b in found if b[1] in (sender, SETUP)] if not attacker else \
              [b for b in found if b[1] == SETUP]
        if own:
            _, lane, var = min(own)
            return lane, var
        if attacker and found:
            _, _, var = min(found)
            return sender, _RECEIVED.sub("", var) + "′"
        return None

    labels: list[str] = []
    brought: list[list[Definition]] = []
    for (n, sender, attacker, _), term in zip(steps, terms):
        defs: list[Definition] = []

        def write(t: Term, whole: bool) -> str:
            v = str(t)
            if t.args is None:
                return show(v)
            if v in names:
                return names[v]
            inner = ",".join(write(a, False) for a in t.args)
            body = f"{t.head}({inner})" if t.head else f"({inner})"
            named = source(v, sender, attacker)
            worth = len(body) >= LONG or seen[v] > 1
            if named is None and not (worth and (t.head or whole)):
                return body
            if named is not None:
                lane, base = named
            else:
                lane = sender
                if whole:
                    base = f"msg{n}"
                else:
                    coined[t.head] += 1
                    base = f"{t.head}{coined[t.head]}"
            names[v] = unique(base)
            d = Definition(lane, names[v], body, show(v))
            (setup if lane == SETUP else defs).append(d)
            return names[v]

        labels.append(write(term, True))
        brought.append(defs)
    return labels, brought, setup, names
