"""The three document tools: read_section / get_reference / grep_document, which
wrap the document façades."""

from __future__ import annotations

from orrery.agent.tools.context import ToolContext
from orrery.agent.tools.registry import ToolDef, clip
from orrery.infra.llm.client import FunctionParameter
from orrery.modules.document import references, search, sections


def _need_docs(ctx: ToolContext):
    if ctx.doc_set is None:
        raise RuntimeError(f"node {ctx.node}: the context has no document set")
    return ctx.doc_set


def _read_section(ctx: ToolContext, number: str, doc_id: str | None = None) -> str:
    text = sections.read_section(_need_docs(ctx), number, doc_id).text
    return clip(text, ctx.tool_return_chars,
                hint="section too long; locate it with grep_document and fetch a smaller subsection")


def _get_reference(ctx: ToolContext, number: str) -> str:
    r = references.section_references(_need_docs(ctx), number)
    if not r.resolved:
        return (f"section {number}: references are **unresolved** — this document set has "
                f"no reference annotations, which is not the same as having none. "
                f"Use grep_document to locate them if needed.")
    if not r.references:
        return f"section {number} has no outgoing references (resolved, definitely none)"
    lines = [f"- {ref.to_dict()}" for ref in r.references]
    return f"outgoing references of section {number}:\n" + "\n".join(lines)


def _grep_document(ctx: ToolContext, pattern: str, max_matches: int | None = 10) -> str:
    out = search.grep(_need_docs(ctx), pattern, max_matches=max_matches or 10)
    return clip(out, ctx.tool_return_chars, hint="lower max_matches or use a more specific pattern")


DOCUMENT_TOOLS = [
    ToolDef(
        name="read_section",
        description="Read the body of one section (of main or of a reference document). When the text is clipped, it says how much is left. To find which section holds a name, use grep_document first.",
        parameters=FunctionParameter(type="object", properties={
            "number": FunctionParameter(type="string", description="section number, e.g. '3.2' or 'A.1'"),
            "doc_id": FunctionParameter(type=["string", "null"],
                                        description="id of the document to read; omitted = main"),
        }, required=["number", "doc_id"]),
        handler=_read_section,
    ),
    ToolDef(
        name="get_reference",
        description="List what one section points at: the other sections it cites and the external documents it names. Use it when the trail you are following leaves the section you are reading — it answers where the material continues without pulling in any text. It returns references only, so follow a result with read_section to read the target; when you are looking for a name rather than following a citation, use grep_document instead. Forward direction only: it does not find the sections that reference this one, and a reference it cannot resolve is reported as unresolved rather than dropped.",
        parameters=FunctionParameter(type="object", properties={
            "number": FunctionParameter(type="string", description="section number"),
        }, required=["number"]),
        handler=_get_reference,
    ),
    ToolDef(
        name="grep_document",
        description="Locate a name or phrase in the scoped main document, then append reference sections explicitly annotated on the matching main sections. It does not directly search every reference document; use the reference-document contents in the prompt and read_section(doc_id=...) for those. Returns each main hit's section plus context lines. An aid to locating things, not a substitute for reading — follow a hit with read_section to read its whole section.",
        parameters=FunctionParameter(type="object", properties={
            "pattern": FunctionParameter(type="string", description="search term (substring match)"),
            "max_matches": FunctionParameter(type=["integer", "null"],
                                             description="maximum number of hits, default 10"),
        }, required=["pattern", "max_matches"]),
        handler=_grep_document,
    ),
]
