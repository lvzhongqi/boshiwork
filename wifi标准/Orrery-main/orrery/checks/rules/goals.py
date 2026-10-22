"""Goal checks after injection: the ownership-anchor contract, plus a typecheck.

payload keys: pv, runner, pv_log (call it with a purpose for a log stem),
goal_ids. Every query resolves to exactly one owner via goal.id — generated
names carry the id, direct secrecy queries a same-line pure-id comment — and an
unrecognisable owner is rejected like an ambiguous one. A goal with no query at
all was silently never verified, so that is rejected too.
"""

from __future__ import annotations

import re

from orrery.checks.registry import CheckResult, register
from orrery.infra.proverif.outcome import OutcomeKind, classify
from orrery.modules.pvtext.parse import (
    blank_comments, block_body, process_blocks, queries, query_owner_hints,
    query_owners,
)


def _naming_anchor(payload) -> CheckResult:
    pv, goal_ids = payload["pv"], payload["goal_ids"]
    f: list[str] = []
    qs = queries(pv)
    if not qs:
        return CheckResult("goals_naming_anchor", "must", False,
                           ["no query at all after injection"])
    claimed: set[str] = set()
    owner_hints = query_owner_hints(pv, goal_ids)
    for q in qs:
        owners = query_owners(q, goal_ids, owner_hints)
        if len(owners) != 1:
            f.append(f"query has no unique owner (matched {owners or 'nothing'}): {q}; "
                     f"generated query names must contain goal id verbatim, while "
                     f"a direct query must end with `(* <goal id> *)`")
        else:
            claimed.add(owners[0])
    for gid in goal_ids:
        if gid not in claimed:
            f.append(f"goal {gid} has no query at all, so it would be silently unverified; it must be injected")
    return CheckResult("goals_naming_anchor", "must", not f, f)


def _opening_receive(body: str) -> int | None:
    """Where a responder's run begins: the end offset of its first
    ``in(channel_…)``, or None when the role sends before it receives.

    Named channels only. ``in(c, …)`` on the public channel is an assumption
    handing the role an attacker-supplied value, not a protocol message."""
    recv = re.search(r"\bin\(\s*channel_[^\n]*\n", body)
    send = re.search(r"\bout\(\s*channel_", body)
    if recv is None or (send is not None and send.start() < recv.start()):
        return None
    return recv.end()


def _begin_placement(payload) -> CheckResult:
    """A begin event is the subject's participation record, so it belongs inside
    the subject's run: a role that opens by receiving has no peer and no session
    until that receive returns, so a begin above it is raised by copies that ran
    nothing, and under replication one idle copy answers every end. Positions
    only; no naming convention is involved.
    """
    pv = payload["pv"]
    f: list[str] = []
    for role, blk in process_blocks(pv).items():
        body = blank_comments(block_body(pv, blk))
        opening_recv = _opening_receive(body)
        for m in re.finditer(r"\bevent\s+(begin_\w+)\s*\(", body):
            if opening_recv is not None and m.start() < opening_recv:
                f.append(
                    f"{role}: `event {m.group(1)}` sits above this role's first "
                    f"protocol receive — this role has no peer and no session "
                    f"until that receive returns, so a begin here is raised by "
                    f"copies of the role that ran nothing and every end finds a "
                    f"record without any participation behind it; move the begin "
                    f"below that receive, and below the `let` that destructures "
                    f"the value it binds")
    return CheckResult("goals_begin_placement", "must", not f, f)


#: Budget for this check's one ProVerif call. ProVerif answers the typecheck
#: question in milliseconds even on the largest injected models; everything past
#: that is the solve, which the solve node runs itself on the same file. The
#: errors this check is for live in the binding between a query and its events:
#: a wrong-arity ``inj-event(begin_a(x))``, an ``attacker(n)`` naming nothing.
_TYPECHECK_TIMEOUT_S = 5


#: ``if <copy> = <parameter> then``, on one line or wrapped. The trailing
#: ``then`` keeps the honest-set test out: ``if xA = A || xA = B then`` has an
#: ``||`` where this pattern wants the keyword, so it never matches.
_SETTLED = re.compile(r"\bif\s+([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\s+then")
_BEGIN_CALL = re.compile(r"\bevent\s+(begin_\w+)\s*\(([^)]*)\)")
_BARE_NAME = re.compile(r"^[A-Za-z_]\w*$")


def _begin_binding(payload) -> CheckResult:
    """A begin that binds a copy its own body has already tested equal to a
    parameter above the event. Binding the copy drags begin below the receive
    carrying it, and where that receive is the subject's last message the
    asserter has already raised its end, so the query reads false on a protocol
    that holds. Only a test above the event counts: below it the event has
    already fired, so the parameter would leave an honest-valued record behind.
    """
    pv = payload["pv"]
    f: list[str] = []
    for role, blk in process_blocks(pv).items():
        params = {name for name, _ in blk.params}
        body = blank_comments(block_body(pv, blk))
        settled: dict[str, tuple[str, int]] = {}
        for m in _SETTLED.finditer(body):
            a, b = m.group(1), m.group(2)
            for copy, param in ((a, b), (b, a)):
                if param in params and copy not in params:
                    settled.setdefault(copy, (param, m.end()))
        for m in _BEGIN_CALL.finditer(body):
            for arg in m.group(2).split(","):
                arg = arg.strip()
                if not _BARE_NAME.match(arg) or arg not in settled:
                    continue
                param, at = settled[arg]
                # Above the test the two are not yet settled: a steered run still
                # reaches the event, so only a test above it counts.
                if at >= m.start():
                    continue
                f.append(
                    f"{role}: `event {m.group(1)}` binds {arg}, which this body "
                    f"has already tested equal to its parameter {param} above "
                    f"the event — so every run that reaches the event holds the "
                    f"two equal, and switching costs nothing in value. Binding "
                    f"{arg} is what "
                    f"ties begin to the receive that carries it; where that "
                    f"receive is the subject's last message, the asserter has "
                    f"already raised its end and the query reads false on a "
                    f"protocol that holds. Bind {param} and place begin at the "
                    f"earliest point that allows")
    return CheckResult("goals_begin_binding", "must", not f, f)


async def _typecheck(payload) -> CheckResult:
    raw = await payload["runner"].run(
        payload["pv"], log_to=payload["pv_log"]("typecheck"),
        timeout_s=_TYPECHECK_TIMEOUT_S)
    out = classify(raw)
    # Only the syntax outcome is judged; the solve node collects the solving
    # result itself.
    ok = out.kind is not OutcomeKind.SYNTAX_ERROR
    # Host paths are already out of the errors (outcome.parse_diagnostics).
    errs = [] if ok else list(out.errors)
    if out.kind is OutcomeKind.OK:
        note = ""
    elif out.kind is OutcomeKind.TIMEOUT:
        # The normal pass: typechecking finished and the solve behind it was
        # cut off on purpose, which the note says out loud.
        note = (f"typechecked; the solve behind it was cut off at "
                f"{_TYPECHECK_TIMEOUT_S}s, which is this check's budget and "
                f"not a failure to decide")
    else:
        # A solver limit inside the budget: passing, but the syntax was never
        # contradicted rather than confirmed, so it is not a clean tick.
        note = out.kind.value
    return CheckResult("goals_typecheck", "must", ok, errs, note)


register("goals_naming_anchor", "must", _naming_anchor)
register("goals_begin_placement", "must", _begin_placement)
register("goals_begin_binding", "must", _begin_binding)
register("goals_typecheck", "must", _typecheck)

# Cheap textual checks first, the ProVerif run last.
GOALS_CHECK_NAMES = ["goals_naming_anchor", "goals_begin_placement",
                     "goals_begin_binding", "goals_typecheck"]
