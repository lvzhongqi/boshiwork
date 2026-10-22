"""The two transcript tools: read_transcript / read_prompt.

They hand over an upstream session's rounds and the prompt it actually ran with,
round by round. Reading a session tells how well founded its conclusion was; the
document itself still has to be checked directly.
"""

from __future__ import annotations

from orrery.agent.tools.context import ToolContext
from orrery.agent.tools.registry import ToolDef, page
from orrery.infra.llm.client import FunctionParameter
from orrery.services.transcript.reader import TranscriptReader


def _reader(ctx: ToolContext, node: str) -> TranscriptReader:
    path = ctx.transcript_paths.get(node)
    if path is None:
        raise RuntimeError(
            f"no readable session called {node!r}; the readable ones are: "
            f"{sorted(ctx.transcript_paths)}"
        )
    return TranscriptReader(path)


def _read_transcript(ctx: ToolContext, node: str, from_round: int = 1,
                     to_round: int | None = None) -> str:
    # Thinking summaries, where the backend records them, are part of this slice.
    r = _reader(ctx, node)
    # The schema lets the model pass null for "the default", as page() takes
    # it for from_line; a null reaching slice() would compare against ints.
    from_round = from_round or 1
    text, rest = r.slice(from_round=from_round, to_round=to_round,
                         max_chars=ctx.tool_return_chars)
    if not text:
        return f"{node}: nothing in the transcript for rounds {from_round}-{to_round}"
    return text + (f"\n\n[{rest} Use from_round/to_round to fetch in parts.]" if rest else "")


def _read_prompt(ctx: ToolContext, node: str, from_line: int | None = None,
                 to_line: int | None = None) -> str:
    entries = _reader(ctx, node).entries()
    sys_txt = next((e["content"] for e in entries if e["t"] == "system"), None)
    usr_txt = next((e["content"] for e in entries if e["t"] == "user"), None)
    if sys_txt is None and usr_txt is None:
        return f"{node}: no system or user entry in the transcript"
    # The first user message goes on page one although it came second: it is the
    # short half and this call's own task, while an extraction step's system
    # prompt carries the whole document corpus.
    text = (f"[first user message of {node}]\n{usr_txt or '(none)'}\n\n"
            f"[system prompt {node} actually ran with]\n{sys_txt or '(none)'}")
    return page(text, from_line=from_line, to_line=to_line,
                budget=ctx.tool_return_chars, label=f"{node} prompt")


TRACE_TOOLS = [
    ToolDef(
        name="read_transcript",
        description="Read one session of this run in full, sliced by round. Use it to judge how well founded that step's conclusion is, not as a substitute for reading the document.",
        parameters=FunctionParameter(type="object", properties={
            "node": FunctionParameter(type="string", description="which session. A step is its own name (`extract_flow`). The scenario stage runs one session per assumption applied and per goal family injected, and each of those is named by its directory relative to the run, with the leading number dropped from the first segment: where list_artifacts shows `08_scenarios/lowe/inject/Secrecy/model.pv`, that session is `scenarios/lowe/inject/Secrecy`. A name that matches no session comes back with the full list of the ones that exist"),
            "from_round": FunctionParameter(type=["integer", "null"],
                                            description="first round, inclusive; default 1"),
            "to_round": FunctionParameter(type=["integer", "null"],
                                          description="last round, inclusive; default the final one"),
        }, required=["node", "from_round", "to_round"]),
        handler=_read_transcript,
    ),
    ToolDef(
        name="read_prompt",
        description="Read what one session actually ran with -- its first user message (that call's own task and data) followed by its system prompt (the criteria it was judged by; for a scenario-stage session, the rules for the one assumption or goal type it handled). Long prompts come back one window of lines at a time, and the return says how many lines are left and which line to continue from.",
        parameters=FunctionParameter(type="object", properties={
            "node": FunctionParameter(type="string", description="which session; same names as read_transcript"),
            "from_line": FunctionParameter(type=["integer", "null"],
                                           description="first line, 1-based and inclusive; default 1"),
            "to_line": FunctionParameter(type=["integer", "null"],
                                         description="last line, inclusive; default the end"),
        }, required=["node", "from_line", "to_line"]),
        handler=_read_prompt,
    ),
]
