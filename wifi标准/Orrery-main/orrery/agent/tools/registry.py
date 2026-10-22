"""Tool definitions, dispatch, and the truncation convention for tool returns.

One tool is one ToolDef with one schema, shared by every node that mounts it:
the caller's list decides which tools are mounted, never their shape. A handler
takes a ToolContext, may be sync or async, and returns a str.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass

from orrery.infra.llm.client import FunctionParameter, FunctionTool


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    parameters: FunctionParameter
    handler: Callable  # (ctx, **args) -> str | GapReport; may be async
    terminal: bool = False  # ends the agent task instead of gathering evidence

    def to_function_tool(self) -> FunctionTool:
        return FunctionTool(
            name=self.name, description=self.description, parameters=self.parameters
        )


def to_function_tools(defs: list[ToolDef]) -> list[FunctionTool]:
    return [d.to_function_tool() for d in defs]


async def dispatch(defs: list[ToolDef], ctx, tool_call: dict) -> object:
    """Find the handler for tool_call by name and run it, awaiting an async one.

    An unknown tool name or non-dict arguments come back as diagnostic text for
    the model to correct itself with; every other exception propagates.
    """
    by_name = {d.name: d for d in defs}
    d = by_name.get(tool_call.get("name"))
    if d is None:
        # "tool " first, like every other diagnosis here: the ledger reads a
        # return that starts that way as a failed call (runner.ToolReturned).
        return (f"tool {tool_call.get('name')!r} is unknown; "
                f"available: {sorted(by_name)}")
    args = tool_call.get("arguments_json")
    if not isinstance(args, dict):
        return (f"tool {d.name}: arguments are not a valid JSON object: "
                f"{tool_call.get('arguments')!r}")
    try:
        # Only a signature-binding failure counts as bad arguments. A TypeError
        # raised inside the handler is a bug and must propagate with its stack.
        inspect.signature(d.handler).bind(ctx, **args)
    except TypeError as e:
        return f"tool {d.name}: bad arguments: {e}"
    try:
        result = d.handler(ctx, **args)
        if inspect.isawaitable(result):
            result = await result
        return result
    except RuntimeError as e:
        # A handler's RuntimeError is addressed to the model (a section number
        # that does not exist, a wrong document id), so hand it back instead of
        # raising. Infrastructure failures use other exception types.
        return f"tool {d.name} failed: {e}"


def clip(text: str, budget: int, *, hint: str) -> str:
    """Truncate text at budget, say how much was left out, and append hint,
    which names the calling tool's own paging parameter. Text that fits within
    the budget is returned unchanged."""
    if len(text) <= budget:
        return text
    return (f"{text[:budget]}\n\n[truncated: {len(text)} chars total, "
            f"{len(text) - budget} not shown. {hint}]")


def page(text: str, *, from_line: int | None, to_line: int | None,
         budget: int, label: str) -> str:
    """Return lines from_line..to_line, 1-based and inclusive at both ends, headed
    by the range shown and followed by the line to continue from. The character
    budget applies inside the window and cuts at a line boundary; a single line
    over budget is returned whole, so paging always advances."""
    lines = text.splitlines()
    total = len(lines)
    start = max(1, from_line or 1)
    if start > total:
        return (f"{label}: {total} line(s) in total, so from_line={start} is "
                f"past the end")
    if to_line is not None and to_line < start:
        # An empty window would come back headed "lines 3-2" with an
        # invitation to read on from 3, which the model would take again.
        return (f"{label}: to_line={to_line} is before from_line={start}; "
                f"nothing to show")
    end = total if to_line is None else min(to_line, total)
    shown: list[str] = []
    used = 0
    for line in lines[start - 1:end]:
        if shown and used + len(line) + 1 > budget:
            break
        shown.append(line)
        used += len(line) + 1
    last = start + len(shown) - 1
    head = f"[{label}: lines {start}-{last} of {total}]\n"
    if last >= total:
        return head + "\n".join(shown)
    return (head + "\n".join(shown)
            + f"\n\n[{total - last} more line(s). Read on with "
              f"from_line={last + 1}.]")
