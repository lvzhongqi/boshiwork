"""read_expected: the corpus's own declared answers for this protocol.

Only the expert mounts this tool, and only when the run was given a corpus; the
nodes that build and verify the model are handed no ground-truth path at all. It
opens the corpus's own two files only, and every read lands on the ledger as one
``tool_called``.
"""

from __future__ import annotations

import json
from pathlib import Path

from orrery.agent.tools.context import ToolContext
from orrery.agent.tools.registry import ToolDef, page
from orrery.infra.llm.client import FunctionParameter

#: The two views of the corpus and what each answers, keyed by the argument the
#: model passes. Both files live outside the run directory, under a path the
#: store layout never learns, so only this tool can open them.
_VIEWS = {
    "results": ("results/results.json",
                "one expected verdict per property, over all the worlds it was "
                "claimed in"),
    "cases": ("results/cases_results.json",
              "the expected verdict per (property, world) cell — where a "
              "disagreement actually sits"),
}


def _read_expected(ctx: ToolContext, which: str = "cases",
                   from_line: int | None = None,
                   to_line: int | None = None) -> str:
    if ctx.ground_truth is None:
        raise RuntimeError(
            "this run was not given a corpus to check against, so there are no "
            "expected answers to read")
    if which not in _VIEWS:
        raise RuntimeError(
            f"which must be one of {sorted(_VIEWS)}; got {which!r}")
    rel, _ = _VIEWS[which]
    path = Path(ctx.ground_truth) / rel
    if not path.is_file():
        raise RuntimeError(
            f"{rel} does not exist under {ctx.ground_truth}; this protocol "
            f"brings no expected answers of that kind")
    # Pretty-printed: on disk these files are one long line, and a line window
    # over a single line is not a window.
    text = json.dumps(json.loads(path.read_text(encoding="utf-8")),
                      indent=1, ensure_ascii=False)
    return page(text, from_line=from_line, to_line=to_line,
                budget=ctx.tool_return_chars,
                label=f"{rel} (corpus)")


TRUTH_TOOLS = [
    ToolDef(
        name="read_expected",
        description=(
            "Read the corpus's own declared answers for this protocol: the "
            "expected verdict per property (results) or per property-and-"
            "world cell (cases). This run's own answers, and its comparison "
            "against these expected answers, are ordinary artifacts under "
            "this run's directory (results.json, cases_results.json, and "
            "the cross_check node's cross_check.json) — read them with "
            "read_artifact. Present only when the run was given a corpus to "
            "check against."),
        parameters=FunctionParameter(type="object", properties={
            "which": FunctionParameter(
                type="string", enum=sorted(_VIEWS),
                description="; ".join(f"{k}: {d}" for k, (_r, d) in _VIEWS.items())),
            "from_line": FunctionParameter(
                type=["integer", "null"],
                description="first line, 1-based and inclusive; default 1"),
            "to_line": FunctionParameter(
                type=["integer", "null"],
                description="last line, inclusive; default as much as fits"),
        }, required=["which", "from_line", "to_line"]),
        handler=_read_expected,
    ),
]
