"""The two artifact tools: list_artifacts / read_artifact. They see only the
current state, and visibility is enforced in the context."""

from __future__ import annotations

from orrery.agent.tools.context import ToolContext
from orrery.agent.tools.registry import ToolDef, page
from orrery.infra.llm.client import FunctionParameter


def _list_artifacts(ctx: ToolContext) -> str:
    files = ctx.visible_artifacts()
    if not files:
        return "no artifacts on disk yet"
    return "\n".join(files)


def _read_artifact(ctx: ToolContext, path: str, from_line: int | None = None,
                   to_line: int | None = None) -> str:
    p = ctx.resolve_artifact(path)
    if not p.exists():
        return f"artifact {path!r} does not exist; run list_artifacts first"
    if not p.is_file():
        # A RuntimeError goes back to the model as the tool's answer; anything
        # else out of read_text (IsADirectoryError) would end the session.
        raise RuntimeError(
            f"artifact {path!r} is a directory, not a file; list_artifacts "
            f"shows the files in it")
    return page(p.read_text(encoding="utf-8"), from_line=from_line,
                to_line=to_line, budget=ctx.tool_return_chars, label=path)


ARTIFACT_TOOLS = [
    ToolDef(
        name="list_artifacts",
        description="List this run's artifact tree as it stands (relative paths).",
        parameters=FunctionParameter(type="object", properties={}),
        handler=_list_artifacts,
    ),
    ToolDef(
        name="read_artifact",
        description="Read any finished artifact (by relative path; see list_artifacts). Long files come back one window of lines at a time, and the return says how many lines are left and which line to continue from -- what is not shown is deferred, never lost.",
        parameters=FunctionParameter(type="object", properties={
            "path": FunctionParameter(type="string", description="relative path"),
            "from_line": FunctionParameter(type=["integer", "null"],
                                           description="first line, 1-based and inclusive; default 1"),
            "to_line": FunctionParameter(type=["integer", "null"],
                                         description="last line, inclusive; default the end of the file"),
        }, required=["path", "from_line", "to_line"]),
        handler=_read_artifact,
    ),
]
