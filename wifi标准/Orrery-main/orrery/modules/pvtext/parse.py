"""Regex extraction of the structurally unambiguous parts of `.pv` text.

Not a full parser, and it never reads meaning out of a naming convention: it
extracts who the processes are, what their signatures are and what is declared,
and raises on anything it cannot extract reliably. Block boundaries rely on a
process definition starting in column 0 while a ``let x = ... in`` inside a body
is indented; an un-indented inner ``let`` misplaces the boundary and shows up in
the signature check.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_RE_PROC = re.compile(r"(?m)^let\s+(\w+)\s*(?:\(([^)]*)\))?\s*=")
_RE_MAIN = re.compile(r"(?m)^process\b")
_RE_FREE = re.compile(r"(?m)^\s*free\s+([\w,\s]+?)\s*:\s*(\w+)\s*(\[[^\]]*\])?\s*\.")
_RE_QUERY = re.compile(r"(?m)^\s*query\b[^.]*\.")
_RE_EVENT_DECL = re.compile(r"(?m)^\s*event\s+(\w+)\s*\(([^)]*)\)\s*\.")
_RE_QUERY_OWNER_TAG = re.compile(
    r"^[ \t]*\(\*[ \t]*([A-Za-z0-9_.-]+)[ \t]*\*\)[ \t]*$"
)
_RE_ATTACKER_NAME = re.compile(
    r"\battacker(?:_p\d+)?\s*\(\s*(?:new\s+)?([A-Za-z_]\w*)"
)


@dataclass(frozen=True)
class Block:
    """Where one process definition sits in the source. ``body`` excludes the
    signature and the closing period."""

    name: str                       # process name, e.g. processA
    role: str                       # with the process prefix removed, e.g. A
    params: tuple[tuple[str, str], ...]
    start: int                      # offset of `let`
    body_start: int                 # first character after `=`
    body_end: int                   # offset of the closing period (exclusive)
    end: int                        # just after the closing period


def blank_comments(text: str) -> str:
    """Replace the contents of ``(* ... *)`` with the same length of whitespace,
    nesting included. Offsets are unchanged, so the result can be used directly
    for locating things."""
    out = list(text)
    depth = 0
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("(*", i):
            depth += 1
            out[i] = out[i + 1] = " "
            i += 2
            continue
        if text.startswith("*)", i) and depth:
            depth -= 1
            out[i] = out[i + 1] = " "
            i += 2
            continue
        if depth and out[i] != "\n":
            out[i] = " "
        i += 1
    return "".join(out)


def parse_params(inner: str | None) -> tuple[tuple[str, str], ...]:
    """``"A: host, B: host"`` → ``(("A","host"), ("B","host"))``. No parameters
    gives an empty tuple."""
    if not inner or not inner.strip():
        return ()
    out = []
    for part in inner.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise PvTextError(f"process parameter has no type annotation: {part!r}")
        name, typ = part.split(":", 1)
        out.append((name.strip(), typ.strip()))
    return tuple(out)


class PvTextError(RuntimeError):
    """The `.pv` text does not have the structure this module expects."""


def process_blocks(text: str) -> dict[str, Block]:
    """Every ``let <name>(...) =`` process definition, indexed by role name, i.e.
    with the ``process`` prefix removed."""
    blanked = blank_comments(text)
    matches = list(_RE_PROC.finditer(blanked))
    main_m = _RE_MAIN.search(blanked)
    hard_end = main_m.start() if main_m else len(blanked)

    out: dict[str, Block] = {}
    for i, m in enumerate(matches):
        if m.start() >= hard_end:
            continue
        nxt = matches[i + 1].start() if i + 1 < len(matches) else hard_end
        body_start = m.end()
        dot = blanked.rfind(".", body_start, nxt)
        if dot < 0:
            raise PvTextError(f"process {m.group(1)!r}: no closing period found")
        name = m.group(1)
        role = name[len("process"):] if name.startswith("process") else name
        out[role] = Block(
            name=name, role=role, params=parse_params(m.group(2)),
            start=m.start(), body_start=body_start, body_end=dot, end=dot + 1,
        )
    return out


def block_body(text: str, blk: Block) -> str:
    """The body text of ``blk``, without the signature or the closing period."""
    return text[blk.body_start:blk.body_end]


def event_raisers(text: str) -> dict[str, list[str]]:
    """``{event name: [process that raises it, …]}``, over the process
    definitions; the declarations at the top are not raisers."""
    blanked = blank_comments(text)
    out: dict[str, list[str]] = {}
    for blk in process_blocks(blanked).values():
        for m in re.finditer(r"\bevent\s+(\w+)\s*\(", block_body(blanked, blk)):
            out.setdefault(m.group(1), []).append(blk.name)
    return out


def injective_events(text: str) -> set[str]:
    """The events a query asks about injectively (``inj-event(e(…))``), which
    is the difference between "some begin matched" and "one each"."""
    out = set()
    for q in queries(text):
        out.update(re.findall(r"\binj-event\s*\(\s*(\w+)\s*\(", q))
    return out


def role_signatures(text: str) -> dict[str, tuple[tuple[str, str], ...]]:
    """``{role: ((parameter name, type), …)}``. The role-signature invariant is
    checked against this."""
    return {r: b.params for r, b in process_blocks(text).items()}


def main_keyword_start(text: str) -> int:
    """Offset of the ``process`` keyword that opens the main process; raises
    :class:`PvTextError` if there is none. Everything a `.pv` declares sits in
    front of it, so this is also where a generated declaration is inserted."""
    m = _RE_MAIN.search(blank_comments(text))
    if not m:
        raise PvTextError("no main process found (a top-level `process`)")
    return m.start()


def main_block(text: str) -> tuple[int, int]:
    """The span ``(start, end)`` from just after the main ``process`` keyword to
    the end of the text; raises if there is none."""
    return main_keyword_start(text) + len("process"), len(text)


def free_decls(text: str) -> list[tuple[str, str, bool]]:
    """``free`` declarations as ``[(name, type, is private)]``, with several
    names on one line expanded."""
    out: list[tuple[str, str, bool]] = []
    for names, typ, opts in _RE_FREE.findall(blank_comments(text)):
        private = bool(opts and "private" in opts)
        for nm in (n.strip() for n in names.split(",") if n.strip()):
            out.append((nm, typ, private))
    return out


def queries(text: str) -> list[str]:
    """Every ``query ….`` statement, verbatim."""
    return [q.strip() for q in _RE_QUERY.findall(blank_comments(text))]


def query_owner_hints(text: str, goal_ids) -> dict[str, list[str]]:
    """Direct-query target names mapped to owners from trailing id comments.

    A direct secrecy query has no generated name to carry its goal id, so the id
    sits in a same-line comment (``query attacker(new K). (* secrecy_k *)``) that
    ProVerif drops from its RESULT line; the target name recorded here is what
    attributes the result afterwards. Only pure-id comments count as markers.
    """
    known = set(goal_ids)
    blanked = blank_comments(text)
    out: dict[str, list[str]] = {}
    for m in _RE_QUERY.finditer(blanked):
        line_end = text.find("\n", m.end())
        if line_end < 0:
            line_end = len(text)
        tag = _RE_QUERY_OWNER_TAG.fullmatch(text[m.end():line_end])
        if tag is None or tag.group(1) not in known:
            continue
        target = _RE_ATTACKER_NAME.search(m.group(0))
        if target is None:
            continue
        owners = out.setdefault(target.group(1), [])
        if tag.group(1) not in owners:
            owners.append(tag.group(1))
    return out


def query_spans(text: str) -> list[tuple[int, int]]:
    """Query spans, including a same-line pure-id ownership comment."""
    out: list[tuple[int, int]] = []
    for m in _RE_QUERY.finditer(blank_comments(text)):
        end = m.end()
        line_end = text.find("\n", end)
        if line_end < 0:
            line_end = len(text)
        if _RE_QUERY_OWNER_TAG.fullmatch(text[end:line_end]):
            end = line_end
        out.append((m.start(), end))
    return out


def strip_queries(text: str) -> str:
    """The same text with every top-level ``query`` line removed.

    Shares ``_RE_QUERY`` with :func:`queries`, so what is removed is exactly what
    would have been listed. Matched on the comment-blanked text and cut from the
    original, so a query that only appears inside a comment stays."""
    out = text
    for start, end in reversed(query_spans(text)):
        out = out[:start] + out[end:]
    return out


def query_owners(query: str, goal_ids,
                 owner_hints: dict[str, list[str]] | None = None) -> list[str]:
    """Which goals own this query, by generated name or direct-query hint.

    One ``model.pv`` holds queries for several goals, so verdicts are split back
    by the ``goal.id`` the injector embeds verbatim in every name it introduces;
    order of appearance is no good, since ProVerif rewrites queries. Ids can be
    substrings of one another (``auth_b_to_a`` inside ``auth_b_to_a_noninj``) and
    the longer one wins. ``owner_hints`` covers direct queries, which carry no
    generated name. Returns zero, one or several ids; both zero and more than one
    are hard errors, decided by the caller.
    """
    hits = [gid for gid in goal_ids if gid in query]
    hinted: list[str] = []
    if owner_hints:
        target = _RE_ATTACKER_NAME.search(query)
        if target is not None:
            rendered = target.group(1)
            # ProVerif alpha-renames a queried binder when another local binder
            # shares its source name (``Kab`` becomes ``Kab_2``), so an exact
            # name wins and only otherwise is one numeric suffix stripped: a
            # real source binder ``Kab_2`` keeps its own owner either way.
            owners = owner_hints.get(rendered, [])
            if not owners:
                source = re.sub(r"_\d+$", "", rendered)
                owners = owner_hints.get(source, [])
            for gid in owners:
                if gid in goal_ids and gid not in hinted:
                    hinted.append(gid)
    # A query may genuinely mention both a long and a short goal, so containment
    # alone does not decide: mask out the long id's occurrences and keep the
    # short one only if it still appears on its own.
    out = []
    for g in hits:
        masked = query
        for o in hits:
            if o != g and g in o:
                masked = masked.replace(o, "\x00" * len(o))
        if g in masked:
            out.append(g)
    for gid in hinted:
        if gid not in out:
            out.append(gid)
    return out


def declared_events(text: str) -> dict[str, tuple[str, ...]]:
    """``event name(argument types…)`` declarations → ``{name: (types…)}``."""
    out: dict[str, tuple[str, ...]] = {}
    for name, args in _RE_EVENT_DECL.findall(blank_comments(text)):
        types = tuple(a.strip() for a in args.split(",") if a.strip())
        out[name] = types
    return out


def bound_names(body: str) -> list[str]:
    """Names bound in a body: ``new x: T``, ``let x = ``, ``let (a: T, b: T) = ``,
    ``in(ch, x: T)``.

    Purely lexical, for lints such as "bound and never used". It errs on the
    side of catching less: a missed name only under-reports, while catching the
    wrong thing produces a false report.
    """
    src = blank_comments(body)
    names: list[str] = []
    for m in re.finditer(r"\bnew\s+(\w+)\s*:", src):
        names.append(m.group(1))
    for m in re.finditer(r"\blet\s+(\w+)\s*(?::\s*\w+\s*)?=", src):
        names.append(m.group(1))
    for m in re.finditer(r"\blet\s*\(([^)]*)\)\s*=", src):
        names.extend(_tuple_names(m.group(1)))
    for m in re.finditer(r"\bin\s*\(\s*[\w()]+\s*,\s*\(([^)]*)\)\s*\)", src):
        names.extend(_tuple_names(m.group(1)))
    for m in re.finditer(r"\bin\s*\(\s*[\w()]+\s*,\s*(\w+)\s*:\s*\w+\s*\)", src):
        names.append(m.group(1))
    for m in re.finditer(r"\bget\s+\w+\s*\(([^)]*)\)", src):
        names.extend(_tuple_names(m.group(1)))
    seen: list[str] = []
    for n in names:
        if n not in seen:
            seen.append(n)
    return seen


def _tuple_names(inner: str) -> list[str]:
    out = []
    for part in inner.split(","):
        part = part.strip()
        if not part or part.startswith("="):
            continue                                    # `=x` is a check, not a binding
        nm = part.split(":", 1)[0].strip()
        if re.fullmatch(r"\w+", nm):
            out.append(nm)
    return out


def count_reads(body: str, name: str) -> int:
    """How many times ``name`` appears as an identifier in the body, including
    its own binding site."""
    return len(re.findall(rf"\b{re.escape(name)}\b", blank_comments(body)))

def duplicate_destructor_declarations(declarations: list[str]) -> list[str]:
    """Symbols declared as both constructors and rewrite destructors.

    ProVerif introduces the outer symbol on a ``reduc`` left-hand side, so a
    separate ``fun`` declaration for that same symbol is a duplicate definition.
    Checked here so the model does not pay for a ProVerif run to learn it.
    """
    funs: set[str] = set()
    destructors: set[str] = set()
    for declaration in declarations:
        if match := re.match(r"\s*fun\s+(\w+)\s*\(", declaration):
            funs.add(match.group(1))
        if match := re.match(
                r"(?s)\s*reduc\b.*?;\s*(\w+)\s*\(", declaration):
            destructors.add(match.group(1))
    return sorted(funs & destructors)


def parallel_branches(text: str, blk: Block) -> list[tuple[int, int]] | None:
    """The spans of ``blk``'s top-level parallel branches, or ``None`` when the
    body is not a parallel composition.

    A parallel body is ``( A | B | C )`` and nothing else at its top level, so
    the shape is decidable by paren depth: the first non-blank character opens
    the group and the ``|`` at depth 1 separate the branches. Anything else is a
    single branch and gets ``None``. Comments are blanked first, so a ``|``
    inside a comment cannot change the answer; the spans are offsets into
    ``text``.
    """
    blanked = blank_comments(text)
    body = blanked[blk.body_start:blk.body_end]
    i = 0
    while i < len(body) and body[i].isspace():
        i += 1
    if i >= len(body) or body[i] != "(":
        return None
    depth = 0
    start = i
    parts: list[tuple[int, int]] = []
    closed_at: int | None = None
    for j in range(i, len(body)):
        c = body[j]
        if c == "(":
            depth += 1
            if depth == 1:
                start = j + 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                parts.append((start, j))
                closed_at = j
                break
        elif c == "|" and depth == 1:
            parts.append((start, j))
            start = j + 1
    # "and nothing else at its top level": a group followed by more text
    # (``( A | B ) | C``, ``( A | B ); 0``) is not the shape, and reading only
    # the group would hide the branches after it from every check downstream.
    if closed_at is None or body[closed_at + 1:].strip():
        return None
    if len(parts) < 2:
        return None
    off = blk.body_start
    return [(off + a, off + b) for a, b in parts]
