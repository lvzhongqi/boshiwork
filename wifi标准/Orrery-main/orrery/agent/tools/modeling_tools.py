"""The flow-only lookups for curated modelling guidance.

Three libraries, two shapes. Identity returns 1-3 mutually exclusive
abstractions of one deployment fact, and the flow marks its choice in the text.
Time-variant parameters and role-body structure each return exactly one method,
because each has a single right shape rather than a menu of alternatives.
"""

from __future__ import annotations

import re

from orrery.agent.tools.context import ToolContext
from orrery.agent.tools.registry import ToolDef
from orrery.infra.llm.client import FunctionParameter
from orrery.modules.kbase.modeling_idioms import (
    identity_lead, search_identity_idioms, select_structure_idiom,
    select_time_variant_idiom, structure_lead, time_variant_lead,
)

_RESULT_HEADER = re.compile(r"\[identity-modeling-candidates:\s*([^\]]+)\]")
_STRUCTURE_HEADER = re.compile(r"\[structure-modeling:\s*([^\]]+)\]")
_MISS_HEADER = "[identity-modeling-coverage-gap]"


def _lookup(ctx: ToolContext, query: str) -> str:
    try:
        hits = search_identity_idioms(query)
    except ValueError as e:
        raise RuntimeError(str(e)) from None
    if not hits:
        ctx.identity_modeling_miss = True
        return (
            f"{_MISS_HEADER}\nNo identity-modelling method matches this description. This is a "
            "modelling-library coverage gap: do not invent a CA, registry, or "
            "pre-provisioning mechanism and do not silently flatten the binding "
            "into role parameters.")
    keys = ",".join(f"{x.id}@{x.version}" for x in hits)
    lead = identity_lead()
    blocks = [f"[identity-modeling-candidates: {keys}]", lead]
    for index, item in enumerate(hits, 1):
        blocks.append(
            f"\n{index}. {item.id}/v{item.version}\n"
            f"{item.prompt}")
    out = "\n".join(blocks)
    if len(out) > ctx.tool_return_chars:
        # A ValueError, not a RuntimeError: dispatch hands a RuntimeError back
        # to the model as the tool's answer, and this is a config fault (the
        # budget is below the card) the model cannot act on. It ends the step.
        raise ValueError(
            f"identity modeling guidance is {len(out)} characters, over this "
            f"session's tool_return_chars={ctx.tool_return_chars}; the binding "
            "rules may not be truncated")
    ctx.offered_identity_idioms.update(x.key for x in hits)
    ctx.identity_modeling_miss = False
    return out


IDENTITY_MODELING_TOOLS = [
    ToolDef(
        name="lookup_identity_modeling",
        description=(
            "Look up 1-3 curated ProVerif methods for an identity, credential, "
            "CA, certificate, or public-key binding described by the protocol. "
            "The query must state operational facts: what identity/credential "
            "is received, where the peer key comes from, whether lookup happens "
            "at run time, whether certificate validation is protocol-visible, "
            "and whether the document leaves the binding mechanism unspecified."),
        parameters=FunctionParameter(type="object", properties={
            "query": FunctionParameter(
                type="string",
                description="Operational description of this identity-binding mechanism, including what the document explicitly omits"),
        }, required=["query"]),
        handler=_lookup,
    ),
]


def offered_identity_idioms_from_messages(messages) -> set[tuple[str, int]]:
    """Restore successful offers from replayable tool results on resume."""
    out: set[tuple[str, int]] = set()
    for message in messages or ():
        content = getattr(message, "content", "")
        if not isinstance(content, str):
            continue
        for match in _RESULT_HEADER.finditer(content):
            for raw in match.group(1).split(","):
                ident, sep, version = raw.strip().partition("@")
                if sep and version.isdigit():
                    out.add((ident, int(version)))
    return out


def identity_modeling_miss_from_messages(messages) -> bool:
    """Whether the last identity lookup result in a resumed session missed."""
    missed = False
    for message in messages or ():
        content = getattr(message, "content", "")
        if not isinstance(content, str):
            continue
        if _MISS_HEADER in content:
            missed = True
        if _RESULT_HEADER.search(content):
            missed = False
    return missed


def offered_structure_idioms_from_messages(messages) -> set[tuple[str, int]]:
    """Restore successful offers from replayable tool results on resume.

    This library has no miss state, so every recorded header is an offer.
    """
    out: set[tuple[str, int]] = set()
    for message in messages or ():
        content = getattr(message, "content", "")
        if not isinstance(content, str):
            continue
        for match in _STRUCTURE_HEADER.finditer(content):
            ident, sep, version = match.group(1).strip().partition("@")
            if sep and version.isdigit():
                out.add((ident, int(version)))
    return out


def _lookup_time(ctx: ToolContext, query: str) -> str:
    try:
        item = select_time_variant_idiom(query)
    except ValueError as e:
        raise RuntimeError(str(e)) from None
    lead = time_variant_lead()
    out = (f"[time-variant-modeling: {item.id}@{item.version}]\n{lead}\n\n"
           f"{item.id}/v{item.version}\n{item.prompt}")
    if len(out) > ctx.tool_return_chars:
        # A ValueError, not a RuntimeError: dispatch hands a RuntimeError back
        # to the model as the tool's answer, and this is a config fault (the
        # budget is below the card) the model cannot act on. It ends the step.
        raise ValueError(
            f"time-variant modeling guidance is {len(out)} characters, over this "
            f"session's tool_return_chars={ctx.tool_return_chars}; the encoding "
            "rules may not be truncated")
    return out


def _lookup_structure(ctx: ToolContext, query: str) -> str:
    try:
        item = select_structure_idiom(query)
    except ValueError as e:
        raise RuntimeError(str(e)) from None
    lead = structure_lead()
    out = (f"[structure-modeling: {item.id}@{item.version}]\n{lead}\n\n"
           f"{item.id}/v{item.version}\n{item.prompt}")
    if len(out) > ctx.tool_return_chars:
        # A ValueError, not a RuntimeError: dispatch hands a RuntimeError back
        # to the model as the tool's answer, and this is a config fault (the
        # budget is below the card) the model cannot act on. It ends the step.
        raise ValueError(
            f"structure modeling guidance is {len(out)} characters, over this "
            f"session's tool_return_chars={ctx.tool_return_chars}; the shape "
            "rules may not be truncated")
    ctx.offered_structure_idioms.add(item.key)
    return out


STRUCTURE_MODELING_TOOLS = [
    ToolDef(
        name="lookup_structure_modeling",
        description=(
            "Look up the one curated ProVerif shape for a participant the "
            "document gives more than one way to be entered: a token endpoint "
            "that also answers refresh requests, a rekey or re-authentication "
            "exchange beside the initial one, a resumption handshake. The query "
            "must state operational facts: which exchanges this party answers, "
            "whether a later one may start at any time rather than only after "
            "an earlier one in the same run, what distinguishes the requests "
            "from each other, and what one exchange consumes that another "
            "issued. Call it before writing such a role body, not after."),
        parameters=FunctionParameter(type="object", properties={
            "query": FunctionParameter(
                type="string",
                description="Operational description of this party's several exchanges, including what makes them independent of one another"),
        }, required=["query"]),
        handler=_lookup_structure,
    ),
]


TIME_VARIANT_MODELING_TOOLS = [
    ToolDef(
        name="lookup_time_variant_modeling",
        description=(
            "Look up the one curated ProVerif method for a time-variant "
            "parameter the protocol carries: a timestamp, a ticket lifetime or "
            "validity period, or a sequence number. The query must state "
            "operational facts: who mints the value, who receives it, what the "
            "document says the receiver does with it, whether the document "
            "defines any behaviour for the stale case, and whether the value "
            "travels inside integrity protection."),
        parameters=FunctionParameter(type="object", properties={
            "query": FunctionParameter(
                type="string",
                description="Operational description of this time-variant parameter, including what the document leaves undefined"),
        }, required=["query"]),
        handler=_lookup_time,
    ),
]
