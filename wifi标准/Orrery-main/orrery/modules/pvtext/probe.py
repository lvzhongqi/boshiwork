"""The honest-run probe: per-role events and queries asking whether each role
can run to the end of its body, plus the removal of them.

The template supplies the declarations, queries and private channels; the model
marks its own honest end, because the success path is not always the ``then``
branch and cannot be found mechanically. The checks are therefore local: the
call sits in the role's own body and is not followed by ``;``. One query per
role, so a body that splits in parallel only answers "at least one branch is
reachable". Removal comes in two pieces because the one-shot baseline runs this
probe on a model whose ``[private]`` channels are its own scenario:
:func:`remove_probe` takes the instrumentation out and leaves the channels
alone, :func:`strip_probe` adds the channel rewrite.
"""
from __future__ import annotations

import re

from orrery.modules.pvtext.channels import PUBLIC_CHANNEL
from orrery.modules.pvtext.parse import (
    Block,
    PvTextError,
    blank_comments,
    main_block,
    process_blocks,
)

_RE_FREE_CHAN = re.compile(
    r"(?m)^(\s*free\s+)([\w,\s]+?)(\s*:\s*channel\s*)(\[[^\]]*\])?(\s*\.)")

#: The template's heading for the probe block, removed with the block itself.
PROBE_SECTION = "(* -- Honest-run probe -- *)"

#: The probe asks ProVerif for a derivation, not for a trace. ``is_reached``
#: counts ``cannot_be_proved`` as reachable, so no caller reads the trace, and
#: reconstructing one over the probe's ``[private]`` channels is where the solver
#: spends its whole budget pairing internal communication across replicated role
#: processes. The Horn abstraction over-approximates in one direction only -- a
#: role can be called reachable with no concrete trace, never the reverse -- and
#: this gate only needs the "the role never runs" answer.
PROBE_SETTING = "set reconstructTrace = false."

#: The whole block as the template renders it, trailing blank line included.
_RE_PROBE_BLOCK = re.compile(
    r"(?m)^[ \t]*" + re.escape(PROBE_SECTION) + r"[ \t]*\r?\n"
    r"(?:[ \t]*(?:set|event|query)[^\n]*\r?\n)*"
    r"[ \t]*\r?\n")

#: Anything of the probe left outside that block: a declaration the model moved,
#: a query it restated, the setting it hoisted to the top of the file.
_RE_PROBE_LINE = re.compile(
    r"(?m)^[ \t]*(?:event\s+reached_\w+\s*\(\s*\)"
    r"|query\s+event\s*\(\s*reached_\w+\s*\(\s*\)\s*\)"
    r"|set\s+reconstructTrace\s*=\s*\w+)\s*\.[ \t]*\r?\n")


def event_name(role: str) -> str:
    return f"reached_{role}"


def event_decl(role: str) -> str:
    return f"event {event_name(role)}()."


def event_call(role: str) -> str:
    return f"event {event_name(role)}()"


def query_line(role: str) -> str:
    return f"query event({event_name(role)}())."


def probe_declarations(roles: list[str]) -> list[str]:
    """The probe's fixed lines, in template order: the solver setting, then one
    event per role, then one query per role."""
    return ([PROBE_SETTING] + [event_decl(r) for r in roles]
            + [query_line(r) for r in roles])


def any_call_spans(text: str, blk: Block) -> list[tuple[int, int, str]]:
    """``(start, end, role)`` for every ``event reached_<role>()`` inside
    ``blk``'s body, whichever role it names.

    The role comes out of the match rather than in as an argument, so a call to
    another role's event is reported instead of missed.
    """
    blanked = blank_comments(text)
    out = []
    for m in re.finditer(r"event\s+reached_(\w+)\s*\(\s*\)", blanked):
        if blk.body_start <= m.start() < blk.body_end:
            out.append((m.start(), m.end(), m.group(1)))
    return out


def is_followed_by_semicolon(text: str, end: int) -> bool:
    """Whether the statement ending at ``end`` is continued with ``;``.

    A call followed by ``;`` sits in the middle of a branch, where it says
    nothing about reaching the end of one and where removing it would leave
    ``0; 0``, which ProVerif does not take.
    """
    rest = blank_comments(text)[end:].lstrip()
    return rest.startswith(";")


#: The probe verdicts that mean the event can happen. ProVerif proves "the event
#: is never reached", so ``true`` is the unreachable answer. Everything that
#: reads a probe verdict reads it through here.
REACHED_VERDICTS = ("false", "cannot_be_proved")


def is_reached(verdict: str) -> bool:
    return verdict in REACHED_VERDICTS


def remove_probe(text: str) -> str:
    """The probe taken out and nothing else touched.

    Two rewrites, in this order because the first is by offset and the second
    moves offsets: every ``event reached_<role>()`` in a role body back to ``0``
    (deleting the line would leave ``out(...);`` in front of an ``else``), then
    the probe's declarations and queries dropped as whole lines. Channels are
    left exactly as the text has them, since this function cannot know whether
    ``[private]`` was instrumentation or the model's own scenario. Raises
    :class:`PvTextError` when anything probe-shaped survives.
    """
    spans = [sp for blk in process_blocks(text).values()
             for sp in any_call_spans(text, blk)]
    out = text
    for start, end, _role in sorted(spans, reverse=True):
        out = out[:start] + "0" + out[end:]
    out = _RE_PROBE_BLOCK.sub("", out)
    out = _RE_PROBE_LINE.sub("", out)
    left = blank_comments(out)
    if re.search(r"reached_\w+", left):
        raise PvTextError(
            "remove_probe failed: the text still mentions a reached_ event after "
            "the probe was removed; the probe form is not what it was taken for")
    if re.search(r"reconstructTrace", left):
        raise PvTextError(
            "remove_probe failed: the text still sets reconstructTrace after the "
            "probe was removed; that setting belongs to the honest-run probe, and "
            "the flow model downstream is solved with traces on")
    return out


def strip_probe(text: str) -> str:
    """The flow model as it goes downstream: :func:`remove_probe` plus the named
    channels made public again, since the flow model runs on a Dolev-Yao network
    and ``[private]`` was only for the honest run."""
    return publicize_named_channels(remove_probe(text))


def publicize_named_channels(text: str) -> str:
    """Drop ``[private]`` from the named channels ``channel_X_Y``, leaving any
    other option list alone. The inverse of what the template renders."""
    def _sub(m: re.Match) -> str:
        head, names, mid, opts, tail = m.groups()
        listed = [n.strip() for n in names.split(",") if n.strip()]
        if all(n == PUBLIC_CHANNEL for n in listed) or not opts:
            return m.group(0)
        kept = [o.strip() for o in opts[1:-1].split(",")
                if o.strip() and o.strip() != "private"]
        if not kept:
            return f"{head}{names}{mid.rstrip()}{tail}"
        return f"{head}{names}{mid}[{', '.join(kept)}]{tail}"

    return _RE_FREE_CHAN.sub(_sub, text)


def main_process_calls(text: str) -> list[str]:
    """The roles whose probe event is called from the main process, where a
    call would be reachable without the role body ever finishing."""
    start, end = main_block(text)
    blanked = blank_comments(text)
    return [m.group(1) for m in re.finditer(r"event\s+reached_(\w+)\s*\(\s*\)", blanked)
            if start <= m.start() < end]
