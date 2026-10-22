"""Read the dot file ``proverif -graph`` writes for one attack trace.

The file is ProVerif's own drawing of the execution, and under
``set traceDisplay = long.`` it carries everything a step-by-step account needs,
each piece tied to the process that did it:

- **Process nodes** ``P0_<path>__<t>``. ``<path>`` names one process in the
  execution tree (``P0_12_0`` is copy 0 of the twelfth parallel branch) and
  ``<t>`` its clock. A node's label is a table, one row per action, each row
  starting with the program point ``{n}`` it executed.
- **Role starts.** A row ``Beginning of process processA`` marks the node where
  a named process begins; everything below that path belongs to it.
- **Messages.** An edge from a process node to an attacker node ``P__<t>`` is a
  message: an output when plain, an input when ``dir = back``. Its label is
  ``slot = value`` for an output and ``recipe = value`` for an input. The
  attacker nodes' clock orders all messages in one line.
- **Abbreviations.** A message too long to draw is labelled with its slots
  alone, ``(~M_7,~M_8)``, and a node ``Abbrev`` lists what each slot holds
  (``~M_7 = attacker_peer_2``); the message's value is the label with those
  filled in.
- **Private messages.** An edge between two process nodes is a message one
  honest process hands another on a channel the attacker cannot see. Its label
  is always an abbreviation (``~X_3``), its direction the edge's (reversed by
  ``dir = back``), and it is drawn once for each branch of the sender that
  could have sent it, which is one message. It happens on the two nodes' own
  row, so it takes their time.
- **The goal.** The node drawn ``color = red``: an attacker node for a
  knowledge goal, a process node for an event goal.
- **The clock.** A process node's own number counts along its process only.
  What places it among everything else is the ``{rank = same; P__<t> …}``
  group it is drawn in: the attacker node there gives its time. A node holding
  actions sits between two such rows on its process, so it takes the time of
  the last row before it plus a half — after that message, before the next.
  The number runs on along a lineage, so rows drawn for the process's
  ancestors or descendants place it when it has none of its own.

Only the structure above is read. A labelled statement of any other shape is an
error, not something skipped: an account built on half a trace would read as
the whole of it.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from orrery.modules.attacks.terms import Term, TermError, parse as parse_term, split_top

_PROC = re.compile(r"P0((?:_\d+)*)__(\d+)")
_ATTACKER = re.compile(r"P__(\d+)")
_ROW = re.compile(r"<TR>(.*?)</TR>", re.S)
_POINT = re.compile(r'^\s*<FONT COLOR="darkgreen">\{(\d+)\}</FONT>')
_WORD = re.compile(r'^\s*<FONT COLOR="blue">([^<]*)</FONT>')
_BEGIN = re.compile(r'^\s*Beginning of process\s*<FONT COLOR="darkgreen">([^<]+)</FONT>\s*$')
_TAG = re.compile(r"<[^>]+>")


class GraphError(ValueError):
    """A dot file this reader does not understand."""


@dataclass(frozen=True)
class Row:
    """One executed action: its program point (None for a row without one),
    the keyword it starts with (``new``, ``let``, ``if``, ``event``, ``get``,
    ``insert``, …; empty when there is none) and the rest of the row."""

    point: int | None
    word: str
    text: str


@dataclass
class ProcNode:
    id: str
    path: str               #: the process, e.g. ``P0_12_0``
    seq: int                #: its number along its own process
    time: float = -1.0      #: where it falls on the attacker clock
    rows: list[Row] = field(default_factory=list)
    begins: str = ""        #: the named process that starts here, if any
    goal: bool = False


@dataclass(frozen=True)
class Message:
    """One message between the attacker and an honest process."""

    time: int               #: the attacker clock; orders all messages
    path: str               #: the honest process at the other end
    direction: str          #: "out" (process → attacker) | "in" (attacker → process)
    recipe: str             #: the slot(s) for an output, the attacker's recipe for an input
    value: str


@dataclass(frozen=True)
class Private:
    """A message one honest process hands another, unseen by the attacker."""

    time: float
    src: str                #: the sending process
    dst: str                #: the receiving process
    value: str


@dataclass
class Graph:
    nodes: dict[str, ProcNode]
    messages: list[Message]
    private: list[Private] = field(default_factory=list)
    goal_text: str = ""     #: the red attacker node's text, for a knowledge goal
    goal_path: str = ""     #: the red process node's path, for an event goal
    goal_node: str = ""


# ── lexing ───────────────────────────────────────────────────────────────

def _tokens(text: str):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i)
            if end < 0:
                raise GraphError("unclosed comment")
            i = end + 2
        elif c == "<":
            depth, j = 0, i
            while j < n:
                if text[j] == "<":
                    depth += 1
                elif text[j] == ">":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if depth:
                raise GraphError("unclosed HTML label")
            yield "html", text[i + 1:j]
            i = j + 1
        elif c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            yield "str", text[i + 1:j]
            i = j + 1
        elif text.startswith("->", i):
            yield "op", "->"
            i += 2
        elif c in "{}[];,=":
            yield "op", c
            i += 1
        else:
            m = re.compile(r"[A-Za-z0-9_.]+").match(text, i)
            if m is None:
                raise GraphError(f"unexpected {text[i:i + 20]!r}")
            yield "id", m.group(0)
            i = m.end()


def _statements(text: str):
    """The statements, and the node groups drawn on one row
    (``{rank = same; …}``), each as a list of node ids."""
    toks = list(_tokens(text))
    out = []
    ranks: list[list[str]] = []
    i = 0
    while i < len(toks):
        kind, val = toks[i]
        if (kind, val) == ("op", "{"):
            j = i + 1
            if toks[j:j + 3] == [("id", "rank"), ("op", "="), ("id", "same")]:
                j += 3
                members = []
                while toks[j] != ("op", "}"):
                    if toks[j][0] == "id":
                        members.append(toks[j][1])
                    j += 1
                ranks.append(members)
                i = j + 1
                continue
            i += 1
            continue
        if kind != "id":
            i += 1
            continue
        ids = [val]
        j = i + 1
        while j + 1 < len(toks) and toks[j] == ("op", "->"):
            ids.append(toks[j + 1][1])
            j += 2
        attrs: dict[str, tuple[str, str]] = {}
        if j < len(toks) and toks[j] == ("op", "["):
            j += 1
            while j < len(toks) and toks[j] != ("op", "]"):
                if toks[j][0] == "op":
                    j += 1
                    continue
                if j + 2 >= len(toks) or toks[j + 1] != ("op", "="):
                    raise GraphError(f"malformed attribute near {toks[j][1]!r}")
                attrs[toks[j][1]] = toks[j + 2]
                j += 3
            j += 1
        out.append((ids, attrs))
        i = j
    return out, ranks


# ── labels ───────────────────────────────────────────────────────────────

def _plain(fragment: str) -> str:
    """Tags removed, ``<br/>`` joined without a space (ProVerif wraps inside
    terms), entities decoded, runs of space collapsed."""
    s = re.sub(r"<br\s*/?>\s*", "", fragment)
    return " ".join(html.unescape(_TAG.sub("", s)).split())


def _rows(label: str) -> tuple[list[Row], str]:
    rows: list[Row] = []
    begins = ""
    for cell in _ROW.findall(label):
        cell = re.sub(r"^\s*<TD[^>]*>|</TD>\s*$", "", cell.strip())
        m = _BEGIN.match(cell)
        if m:
            if begins:
                raise GraphError("two process starts in one node")
            begins = m.group(1).strip()
            continue
        point = None
        m = _POINT.match(cell)
        if m:
            point = int(m.group(1))
            cell = cell[m.end():]
        word = ""
        m = _WORD.match(cell)
        if m:
            word = m.group(1).strip()
            cell = cell[m.end():]
        text = _plain(cell)
        text = re.sub(r"\s*=\s*", " = ", text)
        rows.append(Row(point, word, text))
    return rows, begins


def _abbreviations(label: str) -> dict[str, tuple[str, str]]:
    """The ``Abbrev`` node's rows as ``name → (recipe, value)``, its heading
    left out. ``~M_7 = v`` names a value the attacker holds, its recipe the
    slot itself; ``~X_1 = r = v`` names a whole message, ``r`` how the
    attacker built it and ``v`` what it is."""
    out = {}
    for cell in _ROW.findall(label):
        text = _plain(cell)
        parts = []
        while (cut := split_top(text)) is not None:
            parts.append(cut[0])
            text = cut[1]
        parts.append(text)
        if len(parts) < 2:
            if text != "Abbreviations":
                raise GraphError(f"an abbreviation {text!r} binds nothing")
            continue
        if len(parts) > 3:
            raise GraphError(f"an abbreviation {_plain(cell)!r} of {len(parts)} sides")
        name, value = ("".join(x.split()) for x in (parts[0], parts[-1]))
        recipe = "".join(parts[1].split()) if len(parts) == 3 else name
        out[name] = (recipe, value)
    return out


def _expand(text: str, abbrev: dict[str, tuple[str, str]], side: int) -> str:
    """``text`` with every abbreviated name replaced by its recipe (``side``
    0) or its value (1)."""
    def sub(t: Term) -> Term:
        if t.args is None and t.head in abbrev:
            return parse_term(abbrev[t.head][side])
        if t.args is None:
            return t
        return Term(t.head, tuple(sub(a) for a in t.args))
    try:
        return str(sub(parse_term(text)))
    except TermError as e:
        raise GraphError(f"cannot expand {text!r}: {e}") from None


def _message_text(label: str) -> tuple[str, str]:
    text = _plain(label)
    parts = split_top(text)
    if parts is None:
        # A recipe that is a bare name the attacker made up prints alone.
        return text, text
    return parts


# ── reading ──────────────────────────────────────────────────────────────

def read(path: Path) -> Graph:
    """Parse one ``traceN.dot``. Raises GraphError on a shape it does not know."""
    return parse(Path(path).read_text(encoding="utf-8"))


def parse(text: str) -> Graph:
    nodes: dict[str, ProcNode] = {}
    messages: list[Message] = []
    graph = Graph(nodes, messages)
    statements, ranks = _statements(text)
    clock: dict[str, int] = {}
    for members in ranks:
        ticks = [int(m.group(1)) for x in members if (m := _ATTACKER.fullmatch(x))]
        if not ticks:
            continue        # a layout row: the branches of a split, no action
        if len(ticks) > 1:
            raise GraphError(f"a row group with {len(ticks)} attacker nodes")
        for x in members:
            clock.setdefault(x, ticks[0])
    abbrev: dict[str, tuple[str, str]] = {}
    handed: list[tuple[tuple[str, str], str]] = []
    for ids, attrs in statements:
        kind, label = attrs.get("label", ("", ""))
        red = attrs.get("color", ("", ""))[1] == "red"
        if ids == ["Abbrev"]:
            abbrev.update(_abbreviations(label))
            continue
        if len(ids) == 1:
            node = ids[0]
            m = _PROC.fullmatch(node)
            if m:
                pn = nodes.setdefault(node, ProcNode(
                    node, "P0" + m.group(1), int(m.group(2))))
                if kind == "html" and "<TR>" in label:
                    rows, begins = _rows(label)
                    pn.rows.extend(rows)
                    pn.begins = pn.begins or begins
                pn.goal = pn.goal or red
                if red:
                    graph.goal_path, graph.goal_node = pn.path, node
            elif _ATTACKER.fullmatch(node) and red:
                graph.goal_text = _plain(label)
            continue
        if len(ids) != 2:
            raise GraphError(f"an edge chain {' -> '.join(ids)}")
        a, b = ids
        text = _plain(label) if kind == "html" else label
        if not text:
            continue                 # layout edges: process lineage, time
        if _PROC.fullmatch(a) and _PROC.fullmatch(b):
            back = attrs.get("dir", ("", ""))[1] == "back"
            handed.append(((b, a) if back else (a, b), "".join(text.split())))
            continue
        ma, mb = _PROC.fullmatch(a), _ATTACKER.fullmatch(b)
        if ma is None or mb is None:
            raise GraphError(f"a labelled edge {a} -> {b} that is not a message")
        recipe, value = _message_text(label)
        back = attrs.get("dir", ("", ""))[1] == "back"
        messages.append(Message(
            time=int(mb.group(1)), path="P0" + ma.group(1),
            direction="in" if back else "out",
            recipe="".join(recipe.split()), value="".join(value.split())))
    if abbrev:
        messages[:] = [replace(m, recipe=_expand(m.recipe, abbrev, 0),
                               value=_expand(m.value, abbrev, 1))
                       if m.recipe == m.value else m for m in messages]
    messages.sort(key=lambda msg: msg.time)
    for (a, b), _ in handed:
        for x in (a, b):
            m = _PROC.fullmatch(x)
            nodes.setdefault(x, ProcNode(x, "P0" + m.group(1), int(m.group(2))))
    _place(nodes, clock)
    seen: set[tuple] = set()
    for (a, b), label in handed:
        if label not in abbrev:
            raise GraphError(f"a private message {a} -> {b} labelled {label!r}, "
                             f"which the abbreviations do not spell out")
        src, dst = nodes[a], nodes[b]
        if src.time < 0 or dst.time < 0:
            raise GraphError(f"a private message {a} -> {b} on no row of the clock")
        key = (label, b)            # one per receiving node: a split sender
        if key in seen:             # draws the same hand-over from each branch
            continue
        seen.add(key)
        graph.private.append(Private(max(src.time, dst.time), src.path,
                                     dst.path, abbrev[label][1]))
    if not graph.goal_text and not graph.goal_path:
        raise GraphError("no goal node: the dot file marks none in red")
    return graph


def _place(nodes: dict[str, ProcNode], clock: dict[str, int]) -> None:
    """Give every node a time on the attacker clock (see the module note)."""
    ids_by_path: dict[str, list[tuple[int, str]]] = {}
    for x in clock:
        m = _PROC.fullmatch(x)
        if m:
            ids_by_path.setdefault("P0" + m.group(1), []).append((int(m.group(2)), x))
    for pn in nodes.values():
        if pn.id in clock:
            pn.time = float(clock[pn.id])
            continue
        # The clock counts along a lineage: a split's branches carry on from
        # their parent's number. A process that splits right after it begins
        # is drawn on no row of its own, so its ancestors' rows and its
        # descendants' place it.
        ticks = sorted(t for path, ts in ids_by_path.items()
                       if within(path, pn.path) or within(pn.path, path)
                       for t in ts)
        before = [clock[x] for n, x in ticks if n < pn.seq]
        after = [clock[x] for n, x in ticks if n > pn.seq]
        if before:
            pn.time = max(before) + 0.5
        elif after:
            pn.time = min(after) - 0.5
        elif pn.rows:
            raise GraphError(f"{pn.id} holds actions but its process is drawn on no row")


def within(path: str, root: str) -> bool:
    """Whether process ``path`` is ``root`` or runs below it."""
    return path == root or path.startswith(root + "_")
