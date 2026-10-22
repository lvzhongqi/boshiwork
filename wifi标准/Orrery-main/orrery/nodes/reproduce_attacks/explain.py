"""The explanations: one session per reproduced cell, and one summary over
them.

A cell's session reads the script the step built (``msc.json``), rendered as
text, and may page the re-run's own output and the file that ran. It writes an
opening (what the scenario gives the attacker), one note per step, and a
conclusion. Nothing it writes is taken on trust beyond what can be checked:
the notes must match the script's steps one for one, and anything in
backticks must be found in the script, the trace or the model.

The summary session reads only the conclusions and groups them by the problem
behind them; every cell must land in exactly one group.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from orrery.agent.compose import localized, render_prompt, render_system, resume_user
from orrery.agent.runner import Prompt, SubmitSpec, run_agent
from orrery.agent.tools.context import ToolContext
from orrery.agent.tools.registry import ToolDef, page
from orrery.infra.llm.client import Effort, FunctionParameter
from orrery.modules.attacks.script import ATTACKER
from orrery.modules.attacks.terms import display
from orrery.services.store.atomic import write_json
from orrery.services.transcript.resume import resume_messages
from orrery.services.transcript.writer import TranscriptWriter

NODE = "reproduce_attacks"
EFFORT = Effort.MEDIUM
EXPLANATION = "explanation.json"
SUMMARY = "summary.json"
_QUOTE = re.compile(r"`([^`\n]+)`")

EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "opening": {
            "type": "string", "minLength": 1,
            "description": "what this scenario gives the attacker beyond an "
                           "ordinary network attacker, or that it gives nothing more"},
        "steps": {
            "type": "array",
            "description": "one note for each step number of the script",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer",
                          "description": "the step number, as the script numbers it"},
                    "note": {"type": "string", "minLength": 1,
                             "description": "what happens at this step and why it "
                                            "matters for the attack"},
                },
                "required": ["n", "note"],
                "additionalProperties": False,
            },
        },
        "conclusion": {
            "type": "string", "minLength": 1,
            "description": "which goal fails, why, and what the failure rests on"},
    },
    "required": ["opening", "steps", "conclusion"],
    "additionalProperties": False,
}

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array", "minItems": 1,
            "description": "one entry per distinct problem",
            "items": {
                "type": "object",
                "properties": {
                    "problem": {"type": "string", "minLength": 1,
                                "description": "the one problem these cells come down to"},
                    "cells": {"type": "array", "minItems": 1,
                              "items": {"type": "string"},
                              "description": "the cells it covers, named exactly "
                                             "as the input names them"},
                },
                "required": ["problem", "cells"],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string", "minLength": 1,
                    "description": "a short paragraph over all the groups"},
    },
    "required": ["groups", "summary"],
    "additionalProperties": False,
}


# ── the script as text ───────────────────────────────────────────────────

def render_script(script: dict) -> str:
    """The script the way the prompt shows it: sessions as S1, S2, …, the
    attacker as X, one line per step with what explains it indented below."""
    name = {ATTACKER: "X"}
    lines = ["sessions:"]
    for i, lane in enumerate(script["lanes"], 1):
        name[lane["id"]] = f"S{i}"
        role = lane["role"] or "unnamed process"
        params = f" ({', '.join(lane['bindings'])})" if lane["bindings"] else ""
        lines.append(f"  S{i} = {role}{params}")
    lines.append("  X = the attacker")
    if any(st["kind"] == "private" for st in script["steps"]):
        lines.append("a step marked private passes between two sessions on a "
                     "channel the attacker cannot see")
    lines.append("the attacker knows from the start: "
                 + (", ".join(script["initial"]) or "nothing beyond public names"))

    def where(lane: str) -> str:
        return name.get(lane, "the initial process")

    if script.get("setup"):
        lines.append("")
        lines.append("before the first step, the initial process defines:")
        lines += [f"  {d['name']} = {d['body']}" for d in script["setup"]]
    lines.append("")
    lines.append("long or repeated terms go by a name, defined where they are "
                 "first made (by the model's own variable names where it has "
                 "one; a prime marks a value the attacker made)")
    lines.append("")
    def said(d: dict) -> str:
        if d.get("kind") == "new":
            return f"   {where(d['lane'])} makes up {d['name']}"
        if d.get("kind") == "derive":
            return f"   {where(d['lane'])} works out {d['name']} as {d['body']}"
        return f"   {where(d['lane'])} defines {d['name']} = {d['body']}"

    for s in script["steps"]:
        for d in s.get("defs", []):
            lines.append(said(d))
        lines.append(f"{s['n']}. {name[s['src']]} -> {name[s['dst']]}  "
                     f"{s['kind']}  {s.get('label') or s['value']}")
        for note in s["notes"]:
            lines.append(f"     {name.get(note['lane'], '?')} before this: "
                         f"{{{note['point']}}} {note['word']} {note['text']}")
        if s["recipe"]:
            lines.append(f"     recipe: {s['recipe']}")
        if s["reads"]:
            lines.append(f"     reads: {'; '.join(s['reads'])}")
        if s["computed"]:
            lines.append(f"     computed: {', '.join(s['computed'])}")
    o = script["outcome"]
    lines.append("")
    if o["kind"] == "knowledge":
        for d in o.get("defs", []):
            lines.append(said(d))
        used = [c for c in o["computed"] if c != o["text"]]
        sec = o.get("secret") or {}
        if sec:
            holder = name.get(o["probe_lane"], sec["holder"])
            what = (f"{holder}'s {sec['name']}" if sec["name"]
                    else f"the value {holder} holds")
            lines.append(f"goal broken: the attacker obtains {what}"
                         + (f", which in that session is {sec['value']}"
                            if sec["value"] != sec["name"] else "")
                         + f" (read through the witness {o['text']})")
        else:
            lines.append(f"goal broken: the attacker obtains {o['text']}"
                         + (f", using {', '.join(used)}" if used else ""))
        if o["probe"]:
            holder = name.get(o["probe_lane"], "?")
            lines.append(f"  (read off the probe {o['probe']}, which {holder} "
                         f"sent after its last protocol message: the value the "
                         f"attacker obtains is {holder}'s copy)")
    elif o["kind"] == "event":
        lines.append(f"goal broken: {name.get(o['lane'], '?')} executes {o['text']}")
        want = o.get("expected") or {}
        if want.get("status"):
            rule = ("each end needs a begin of its own saying the same thing"
                    if want["injective"] else
                    "every end needs a begin saying the same thing")
            raised = f", raised by {', '.join(want['roles'])}" if want["roles"] else ""
            what = {"missing": f"{want['event'] or 'the matching begin'} never ran{raised}",
                    "differs": f"{want['event'] or 'the matching begin'} ran, but not "
                               f"about the same thing",
                    "reused": f"{want['event'] or 'the matching begin'} ran once and "
                              f"answered two ends"}[want["status"]]
            lines.append(f"  the goal holds when {rule}; here {what}")
        if not o["counterparts"]:
            lines.append("  no matching begin event was executed")
        for c in o["counterparts"]:
            differ = c["differ"]
            where = ("with different arity" if differ is None else
                     "differs at argument " + ", ".join(str(i + 1) for i in differ)
                     if differ else "with the same arguments")
            lines.append(f"  compare {c['event']} ({{{c['point']}}}), {where}")
    elif o["kind"] == "guess":
        g = o["guess"]
        test = (f"{g['left']} fails" if g["test"] == "fail"
                else f"{g['left']} = {g['right']}")
        lines.append(f"goal broken: the attacker can test a guess of {o['text']} "
                     f"offline. Writing {g['name']} for the guess, it checks "
                     f"whether {test}")
        if g["known"]:
            lines.append(f"  knowing {'; '.join(g['known'])}")
        lines.append(f"  the outcome tells whether {g['name']} = {o['text']}")
    else:
        lines.append(f"goal broken: {o['text']}")
    for note in o["notes"]:
        lines.append(f"  {name.get(note['lane'], '?')} after the last step: "
                     f"{{{note['point']}}} {note['word']} {note['text']}")
    for left in script["omitted"]:
        what = left.get("value") or left.get("role") or left["lane"]
        lines.append(f"left out: {what} ({left['why']})")
    return "\n".join(lines)


def _flat(text: str) -> str:
    return "".join(text.split())


def unfound_quotes(texts: list[str], sources: list[str]) -> list[str]:
    """The backticked pieces of ``texts`` that none of ``sources`` contains,
    comparing with whitespace removed and with ProVerif's instance suffixes
    dropped on either side."""
    haystack = [_flat(s) for s in sources] + [_flat(display(s)) for s in sources]
    out = []
    for text in texts:
        for q in _QUOTE.findall(text):
            needle = _flat(q)
            if not any(needle in h or _flat(display(q)) in h for h in haystack):
                if q not in out:
                    out.append(q)
    return out


# ── tools ────────────────────────────────────────────────────────────────

_RANGE = {
    "from_line": FunctionParameter(type=["integer", "null"],
                                   description="first line, 1-based and inclusive; default 1"),
    "to_line": FunctionParameter(type=["integer", "null"],
                                 description="last line, inclusive; default as much as fits"),
}


def cell_tools(trace: Path, model: Path) -> list[ToolDef]:
    """Two readers bound to one cell's files. Their definitions are the same
    for every cell, so the tool block stays byte-identical across sessions."""
    def reader(path: Path, label: str):
        def handler(ctx: ToolContext, from_line: int | None = None,
                    to_line: int | None = None) -> str:
            return page(path.read_text(encoding="utf-8"), from_line=from_line,
                        to_line=to_line, budget=ctx.tool_return_chars, label=label)
        return handler

    return [
        ToolDef(
            name="read_trace",
            description=(
                "Read ProVerif's output for the re-run behind this attack, a "
                "window of lines at a time. Under the long display it shows "
                "every step with the values bound and the outcome of every "
                "comparison; read it when the script does not show why a "
                "session accepted a message."),
            parameters=FunctionParameter(type="object", properties=_RANGE,
                                         required=["from_line", "to_line"]),
            handler=reader(trace, "trace")),
        ToolDef(
            name="read_model",
            description=(
                "Read the ProVerif model that ran, a window of lines at a time: "
                "the roles, what each one checks, and the goal's queries."),
            parameters=FunctionParameter(type="object", properties=_RANGE,
                                         required=["from_line", "to_line"]),
            handler=reader(model, "model")),
    ]


# ── prompts ──────────────────────────────────────────────────────────────

def build_explain_prompt(*, protocol: str, scenario: str, assumptions: str,
                         goal: str, script: str, replay: bool,
                         tools: list[ToolDef], step_messages: str = "",
                         lang: str = "en") -> Prompt:
    """One cell's request. No I/O and no LLM, so the prompt preview renders
    exactly what a run sends."""
    return Prompt(
        system=render_system(__file__, localized("explain.sys.md", lang),
                             cut_after=[]),
        user=render_prompt(__file__, localized("explain.user.md", lang),
                           protocol=protocol, scenario=scenario,
                           assumptions=assumptions, goal=goal, script=script,
                           replay=replay, step_messages=step_messages),
        tools=tuple(tools),
        submit=SubmitSpec(kind="tool", schema=EXPLAIN_SCHEMA),
        label="reproduce_attacks.explain",
    )


def build_summary_prompt(*, protocol: str, cells: str, pending: int,
                         lang: str = "en") -> Prompt:
    return Prompt(
        system=render_system(__file__, localized("summary.sys.md", lang),
                             cut_after=[]),
        user=render_prompt(__file__, localized("summary.user.md", lang),
                           protocol=protocol, cells=cells, pending=pending),
        submit=SubmitSpec(kind="tool", schema=SUMMARY_SCHEMA),
        label="reproduce_attacks.summary",
    )


# ── sessions ─────────────────────────────────────────────────────────────

class ExplainError(RuntimeError):
    """A session that ended without an explanation."""


def unit_of(layout, home: Path) -> str:
    """The unit a session's events carry: its directory under the step, or,
    for one asked for after the run (``_attacks/``), under the run itself."""
    step = layout.find_node_dir(NODE)
    if step is not None and home.is_relative_to(step):
        return str(home.relative_to(step))
    return layout.rel(home)


async def _session(env, prompt: Prompt, transcript: Path, accept, *,
                   unit: str) -> dict:
    resume = resume_messages(transcript)
    writer = TranscriptWriter(transcript)
    if resume is None:
        writer.meta(node=NODE, model=env.config["llm"].get("model", "?"),
                    effort=EFFORT)
        user = prompt.user
    else:
        user = resume_user(prompt.submit)
    ctx = ToolContext(node=NODE, artifacts_root=env.layout.run_dir,
                      tool_return_chars=env.config["agent"]["tool_return_chars"],
                      prompt_lang=env.config.get("prompt_lang", "en"))
    result = await run_agent(
        env.llm(), system=prompt.system, user=user, tools=list(prompt.tools),
        ctx=ctx, submit=prompt.submit, accept=accept, budget=env.budget(),
        writer=writer, resume_from=resume, effort=EFFORT,
        emitter=env.emitter(NODE, unit=unit))
    if result.status != "ok":
        raise ExplainError(f"{result.status}: {result.failure}")
    return result.submission


async def explain_cell(env, *, home: Path, scenario: str, goal: str,
                       assumptions: str, goal_text: str, replay: bool) -> dict:
    """Explain one reproduced cell into ``home/explanation.json``; an
    explanation already there is read back instead."""
    done = home / EXPLANATION
    if done.is_file():
        return json.loads(done.read_text(encoding="utf-8"))
    script = json.loads((home / "msc.json").read_text(encoding="utf-8"))
    text = render_script(script)
    trace, model = home / "trace.txt", home / "trace.pv"
    numbers = [s["n"] for s in script["steps"]]
    prompt = build_explain_prompt(
        protocol=env.protocol_id, scenario=scenario, assumptions=assumptions,
        goal=goal_text, script=text, replay=replay,
        tools=cell_tools(trace, model),
        step_messages=env.facts(NODE),
        lang=env.config.get("prompt_lang", "en"))

    async def accept(sub, _fences) -> list[str]:
        problems = []
        got = [s["n"] for s in sub["steps"]]
        missing = [n for n in numbers if n not in got]
        extra = sorted({n for n in got if n not in numbers})
        twice = sorted({n for n in got if got.count(n) > 1})
        if missing:
            problems.append(f"these steps have no note: {missing}")
        if extra:
            problems.append(f"the script has no step {extra}; remove those notes")
        if twice:
            problems.append(f"these steps have more than one note: {twice}; "
                            f"keep one each")
        texts = [sub["opening"], sub["conclusion"], *(s["note"] for s in sub["steps"])]
        sources = [text, trace.read_text(encoding="utf-8"),
                   model.read_text(encoding="utf-8")]
        unfound = unfound_quotes(texts, sources)
        if unfound:
            problems.append(
                f"these backticked pieces appear in neither the script, the "
                f"trace nor the model: {unfound}. Copy them exactly as they "
                f"appear there, or take the backticks off a paraphrase.")
        return problems

    sub = await _session(env, prompt, home / "transcript.jsonl", accept,
                         unit=unit_of(env.layout, home))
    sub = {**sub, "steps": sorted(sub["steps"], key=lambda s: s["n"])}
    write_json(done, sub)
    return sub


async def summarize(env, *, home: Path, cells: list[tuple[str, dict]],
                    pending: int) -> dict:
    """Group the explained cells' conclusions into ``home/summary.json``.
    ``cells`` is ``(name, explanation)`` with names ``<scenario>/<goal>``."""
    names = [name for name, _ in cells]
    text = "\n\n".join(f"{name}\n{exp['conclusion']}" for name, exp in cells)
    prompt = build_summary_prompt(protocol=env.protocol_id, cells=text,
                                  pending=pending,
                                  lang=env.config.get("prompt_lang", "en"))

    async def accept(sub, _fences) -> list[str]:
        listed = [c for g in sub["groups"] for c in g["cells"]]
        problems = []
        unknown = sorted({c for c in listed if c not in names})
        missing = [n for n in names if n not in listed]
        twice = sorted({c for c in listed if listed.count(c) > 1})
        if unknown:
            problems.append(f"these are not cells in the input: {unknown}")
        if missing:
            problems.append(f"these cells are in no group: {missing}")
        if twice:
            problems.append(f"these cells are in more than one group: {twice}")
        return problems

    home.mkdir(parents=True, exist_ok=True)
    request = {"covered": names, "pending": pending}
    done, asked = home / SUMMARY, home / "request.json"
    if asked.is_file():
        previous = json.loads(asked.read_text(encoding="utf-8"))
        if previous == request and done.is_file():
            return json.loads(done.read_text(encoding="utf-8"))
        if previous != request:
            # A summary over other cells: kept, under a number, and not resumed.
            _archive(home, ("request.json", SUMMARY, "transcript.jsonl"))
    write_json(asked, request)
    sub = await _session(env, prompt, home / "transcript.jsonl", accept,
                         unit=unit_of(env.layout, home))
    doc = {**request, **sub}
    write_json(done, doc)
    return doc


def _archive(home: Path, names: tuple[str, ...]) -> None:
    """Move these files aside as ``<stem>-<k><suffix>``, one k for the set."""
    k = 1
    while any((home / f"{Path(n).stem}-{k}{Path(n).suffix}").exists()
              for n in names):
        k += 1
    for n in names:
        if (home / n).exists():
            (home / n).rename(home / f"{Path(n).stem}-{k}{Path(n).suffix}")
